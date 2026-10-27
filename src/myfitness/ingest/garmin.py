"""Garmin Personal API -> data/raw/garmin.

The raw layer is only ever extended. What has already been downloaded is
derived from the files on disk, so a run can be repeated or resumed at any
time without a separate state file.

Layout:
    activities/{activity_id}.json         activity details
    fit/{activity_id}.zip                 original file, ZIP bytes unchanged
    daily/{endpoint}/{start}_{end}.json   one file per date window
    heart_rate_zones/{date}.json          snapshot of the zones set in Connect
"""

import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from garmin_personal_api import (
    GarminPersonalApiClient,
    GarminPersonalApiError,
    HttpError,
    PersonalApiAuthenticator,
    resolve_api_key,
)

from myfitness.config import (
    DAILY_WINDOW_DAYS,
    RAW_ACTIVITIES,
    RAW_DAILY,
    RAW_FIT,
    RAW_HR_ZONES,
    Settings,
)

log = logging.getLogger(__name__)

API_KEY_SETTINGS_URL = "https://connect.garmin.com/app/settings/personalApiToken"
ACTIVITY_PAGE_SIZE = 50
# Re-list activities a few days before the newest one we have, in case
# the watch synced an older activity late.
ACTIVITY_OVERLAP_DAYS = 7


class MissingApiKeyError(Exception):
    """No usable API key was found."""


class RequestSkippedError(Exception):
    """A request failed in a way that should be logged, not retried (e.g. HTTP 400)."""


@dataclass
class IngestReport:
    downloaded: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)


class GarminSession:
    """Authenticated client with throttling, retries and token refresh.

    Use as a context manager. All API calls go through `call()`.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def __enter__(self) -> "GarminSession":
        try:
            # The key stays in memory only and is never logged.
            self._api_key = resolve_api_key()
        except GarminPersonalApiError as exc:
            raise MissingApiKeyError(
                f"{exc}\n\nAPI-Schlüssel erzeugen: {API_KEY_SETTINGS_URL}\n"
                "Ablegen unter ~/.config/garmin/connect-personal-api-key (chmod 600) "
                "oder in der Umgebungsvariable GARMIN_PERSONAL_API_KEY."
            ) from exc

        # The authenticator caches the bearer token in
        # ~/.config/garmin/connect-personal-api-bearer-token.json (mode 0600).
        self._authenticator = PersonalApiAuthenticator()
        token = self._authenticator.obtain_token(self._api_key)
        self.client = GarminPersonalApiClient(token.access_token)
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.client.close()
        self._authenticator.close()

    def _refresh_token(self) -> None:
        token = self._authenticator.obtain_token(self._api_key, force_refresh=True)
        self.client.update_bearer_token(token.access_token)

    def call(self, method_name: str, *args: Any, label: str, **kwargs: Any) -> Any:
        """Call a client method by name, throttled and with retries.

        429/5xx/network errors: exponential backoff (2, 4, 8 s ...).
        401: fetch a fresh token once and try again.
        Other 4xx: raise RequestSkippedError so the caller can log and continue.
        """
        method: Callable[..., Any] = getattr(self.client, method_name)
        token_refreshed = False
        attempt = 0
        while True:
            time.sleep(self.settings.request_pause_s)
            attempt += 1
            try:
                return method(*args, **kwargs)
            except HttpError as exc:
                status = exc.status_code
                if status == 401 and not token_refreshed:
                    log.info("401 bei %s, hole neuen Token", label)
                    self._refresh_token()
                    token_refreshed = True
                    attempt -= 1
                    continue
                retryable = status == 429 or status >= 500
                if not retryable:
                    raise RequestSkippedError(f"{label}: HTTP {status}") from exc
                error_text = f"HTTP {status}"
            except requests.RequestException as exc:
                error_text = type(exc).__name__

            if attempt >= self.settings.max_retries:
                raise RequestSkippedError(f"{label}: {error_text} nach {attempt} Versuchen")
            wait_s = 2**attempt
            log.warning("%s: %s, neuer Versuch in %d s", label, error_text, wait_s)
            time.sleep(wait_s)


# --- helpers ---------------------------------------------------------------


def write_atomic(path: Path, content: bytes) -> None:
    """Write to a temp file first, then rename.

    An interrupted run therefore never leaves a half-written file under the
    final name, and the "what is already there" check stays correct.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_bytes(content)
    os.replace(tmp_path, path)


def to_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8")


def date_windows(start: date, end: date, max_days: int) -> Iterator[tuple[date, date]]:
    """Split [start, end] (inclusive) into consecutive windows of at most max_days."""
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=max_days - 1), end)
        yield window_start, window_end
        window_start = window_end + timedelta(days=1)


# --- activities ------------------------------------------------------------


def downloaded_activity_ids() -> set[int]:
    """IDs for which both the detail JSON and the FIT ZIP exist."""
    json_ids = {int(p.stem) for p in RAW_ACTIVITIES.glob("*.json")}
    zip_ids = {int(p.stem) for p in RAW_FIT.glob("*.zip")}
    return json_ids & zip_ids


def activity_start_date(details: dict[str, Any]) -> date | None:
    """Start date (UTC) from a stored activity detail JSON, if present."""
    summary = details.get("summaryDTO", {})
    start_text = details.get("startTimeGMT") or summary.get("startTimeGMT")
    if not start_text:
        return None
    return datetime.fromisoformat(start_text.replace("Z", "")).date()


def newest_activity_date() -> date | None:
    start_dates = []
    for path in RAW_ACTIVITIES.glob("*.json"):
        start = activity_start_date(json.loads(path.read_text()))
        if start is not None:
            start_dates.append(start)
    return max(start_dates, default=None)


def list_activities(session: GarminSession, since: date, until: date) -> list[dict[str, Any]]:
    """All activity summaries in [since, until], page by page."""
    activities: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = session.call(
            "search_activities",
            start=offset,
            limit=ACTIVITY_PAGE_SIZE,
            start_date=since,
            end_date=until,
            label=f"search_activities offset={offset}",
        )
        page = page or []
        activities.extend(page)
        log.info("Aktivitätenliste: %d Einträge", len(activities))
        if len(page) < ACTIVITY_PAGE_SIZE:
            return activities
        offset += ACTIVITY_PAGE_SIZE


def ingest_activities(session: GarminSession, since: date | None, today: date) -> IngestReport:
    report = IngestReport()

    if since is None:
        newest = newest_activity_date()
        if newest is None:
            since = today - timedelta(days=session.settings.initial_days)
        else:
            since = newest - timedelta(days=ACTIVITY_OVERLAP_DAYS)
    log.info("Aktivitäten ab %s", since)

    activities = list_activities(session, since, today)
    already_there = downloaded_activity_ids()
    missing_ids = [a["activityId"] for a in activities if a["activityId"] not in already_there]
    report.skipped = len(activities) - len(missing_ids)

    for number, activity_id in enumerate(missing_ids, start=1):
        log.info("Aktivität %d/%d: %s", number, len(missing_ids), activity_id)
        try:
            details = session.call("get_activity", activity_id, label=f"get_activity {activity_id}")
            zip_bytes = session.call(
                "download_activity", activity_id, label=f"download_activity {activity_id}"
            )
        except RequestSkippedError as exc:
            log.warning("übersprungen: %s", exc)
            report.failed.append(str(exc))
            continue
        # ZIP first, JSON last: the JSON marks the activity as complete
        # together with the ZIP (see downloaded_activity_ids).
        write_atomic(RAW_FIT / f"{activity_id}.zip", zip_bytes)
        write_atomic(RAW_ACTIVITIES / f"{activity_id}.json", to_json_bytes(details))
        report.downloaded += 1

    return report


# --- daily values ----------------------------------------------------------


def endpoint_dir(method_name: str) -> Path:
    return RAW_DAILY / method_name.removeprefix("get_")


def latest_window_end(directory: Path) -> date | None:
    """Largest end date among files named {start}_{end}.json."""
    end_dates = [date.fromisoformat(p.stem.split("_")[1]) for p in directory.glob("*_*.json")]
    return max(end_dates, default=None)


def ingest_daily(session: GarminSession, since: date | None, today: date) -> IngestReport:
    """Load every daily endpoint in windows up to today.

    Files are only added. Windows overlap by `refetch_days`, because the
    watch syncs the last days later; the transformation keeps the value
    from the file with the latest end date.
    """
    report = IngestReport()

    for method_name, max_days in DAILY_WINDOW_DAYS.items():
        directory = endpoint_dir(method_name)
        latest_end = latest_window_end(directory)

        if since is not None:
            start = since
        elif latest_end is not None:
            start = latest_end - timedelta(days=session.settings.refetch_days - 1)
        else:
            start = today - timedelta(days=session.settings.initial_days)

        windows = list(date_windows(start, today, max_days))
        log.info("%s: %d Fenster ab %s", method_name, len(windows), start)

        for window_start, window_end in windows:
            label = f"{method_name} {window_start}..{window_end}"
            try:
                result = session.call(method_name, window_start, window_end, label=label)
            except RequestSkippedError as exc:
                log.warning("übersprungen: %s", exc)
                report.failed.append(str(exc))
                continue
            write_atomic(directory / f"{window_start}_{window_end}.json", to_json_bytes(result))
            report.downloaded += 1

    return report


# --- heart rate zones --------------------------------------------------------


def ingest_heart_rate_zones(session: GarminSession, today: date) -> IngestReport:
    """Store today's snapshot of the heart rate zones configured in Connect.

    Zones can change over time, so each update keeps a dated copy.
    """
    report = IngestReport()
    try:
        zones = session.call("get_heart_rate_zones", label="get_heart_rate_zones")
    except RequestSkippedError as exc:
        log.warning("übersprungen: %s", exc)
        report.failed.append(str(exc))
        return report
    write_atomic(RAW_HR_ZONES / f"{today}.json", to_json_bytes(zones))
    report.downloaded += 1
    return report

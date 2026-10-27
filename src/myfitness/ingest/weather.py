"""Open-Meteo historical weather -> data/raw/weather/{activity_id}.json.

Only coordinates and dates leave this machine. Coordinates are rounded to
two decimals (about 1 km): enough for hourly weather, without revealing
the exact start point.

The archive lags a few days behind today. A response whose hour of
interest is still empty is not cached, so the next update fetches it again.
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import requests

from myfitness.config import RAW_ACTIVITIES, RAW_WEATHER, Settings
from myfitness.ingest.garmin import IngestReport, to_json_bytes, write_atomic

log = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARIABLES = "temperature_2m,relative_humidity_2m,wind_speed_10m"
COORDINATE_DECIMALS = 2


def activity_start(details: dict[str, Any]) -> tuple[datetime, float, float] | None:
    """Start time (UTC) and start coordinates from an activity detail JSON.

    Returns None for activities without GPS (treadmill, strength training).
    """
    summary = details.get("summaryDTO", {})
    lat = summary.get("startLatitude")
    lon = summary.get("startLongitude")
    start_text = summary.get("startTimeGMT")
    if lat is None or lon is None or start_text is None:
        return None
    return datetime.fromisoformat(start_text), lat, lon


def nearest_hour(moment: datetime) -> datetime:
    return (moment + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


def hour_is_filled(response: dict[str, Any], hour: datetime) -> bool:
    """Has the archive already got a temperature for this hour?"""
    hourly = response.get("hourly", {})
    hour_text = hour.strftime("%Y-%m-%dT%H:%M")
    if hour_text not in hourly.get("time", []):
        return False
    position = hourly["time"].index(hour_text)
    return hourly["temperature_2m"][position] is not None


def fetch_weather(start: datetime, lat: float, lon: float) -> dict[str, Any]:
    hour = nearest_hour(start)
    params = {
        "latitude": round(lat, COORDINATE_DECIMALS),
        "longitude": round(lon, COORDINATE_DECIMALS),
        # The nearest hour can be on the next day (start at 23:40).
        "start_date": start.date().isoformat(),
        "end_date": hour.date().isoformat(),
        "hourly": HOURLY_VARIABLES,
        "timezone": "GMT",
        "wind_speed_unit": "kmh",
    }
    response = requests.get(ARCHIVE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def ingest_weather(settings: Settings) -> IngestReport:
    """Fetch weather for every activity with GPS that has no cached file yet."""
    report = IngestReport()
    RAW_WEATHER.mkdir(parents=True, exist_ok=True)
    cached_ids = {p.stem for p in RAW_WEATHER.glob("*.json")}

    for detail_path in sorted(RAW_ACTIVITIES.glob("*.json")):
        activity_id = detail_path.stem
        if activity_id in cached_ids:
            report.skipped += 1
            continue
        start_and_position = activity_start(json.loads(detail_path.read_text()))
        if start_and_position is None:
            report.skipped += 1
            continue

        start, lat, lon = start_and_position
        time.sleep(settings.request_pause_s)
        try:
            response = fetch_weather(start, lat, lon)
        except requests.RequestException as exc:
            log.warning("Wetter %s: %s", activity_id, type(exc).__name__)
            report.failed.append(f"weather {activity_id}: {type(exc).__name__}")
            continue

        if not hour_is_filled(response, nearest_hour(start)):
            log.info("Wetter %s: Archiv noch nicht so weit, später erneut", activity_id)
            continue
        write_atomic(RAW_WEATHER / f"{activity_id}.json", to_json_bytes(response))
        report.downloaded += 1

    log.info("Wetter: %d neu, %d übersprungen", report.downloaded, report.skipped)
    return report

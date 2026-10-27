"""Command line: `myfitness update | transform`."""

import argparse
import logging
import sys
from datetime import date

from myfitness.config import load_settings


def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"kein Datum im Format YYYY-MM-DD: {text}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="myfitness",
        description="Persönliche Analyse eigener Garmin-Daten.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    update = commands.add_parser("update", help="neue Daten von Garmin laden und transformieren")
    update.add_argument(
        "--since",
        type=parse_date,
        help="ab diesem Datum (YYYY-MM-DD) laden; Default: ab dem vorhandenen Stand",
    )

    commands.add_parser("transform", help="nur Rohdaten in Parquet-Tabellen umwandeln")
    return parser


def run_update(since: date | None) -> int:
    # Imported here so that `--help` works without touching the API package.
    from myfitness.ingest.garmin import (
        GarminSession,
        MissingApiKeyError,
        ingest_activities,
        ingest_daily,
        ingest_heart_rate_zones,
    )
    from myfitness.ingest.weather import ingest_weather

    settings = load_settings()
    today = date.today()
    try:
        with GarminSession(settings) as session:
            activities = ingest_activities(session, since, today)
            daily = ingest_daily(session, since, today)
            zones = ingest_heart_rate_zones(session, today)
    except MissingApiKeyError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    weather = ingest_weather(settings)

    print(
        f"Aktivitäten: {activities.downloaded} neu, {activities.skipped} vorhanden, "
        f"{len(activities.failed)} Fehler",
        file=sys.stderr,
    )
    print(f"Tageswerte: {daily.downloaded} Fenster geladen, {len(daily.failed)} Fehler", file=sys.stderr)
    print(f"Wetter: {weather.downloaded} neu, {len(weather.failed)} Fehler", file=sys.stderr)
    for message in activities.failed + daily.failed + zones.failed + weather.failed:
        print(f"  - {message}", file=sys.stderr)

    return run_transform()


def run_transform() -> int:
    from myfitness.transform import transform_all

    transform_all()
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    # The API package logs every request path; keep that quiet.
    logging.getLogger("garmin_personal_api").setLevel(logging.WARNING)

    args = build_parser().parse_args()
    if args.command == "update":
        sys.exit(run_update(args.since))
    if args.command == "transform":
        sys.exit(run_transform())

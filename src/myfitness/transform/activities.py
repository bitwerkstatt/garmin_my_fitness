"""activities.parquet: one row per activity.

Sources:
- detail JSON (summaryDTO): the values Garmin Connect shows
- FIT session: sport, timer time, cadence, RPE (see records.session_row)
- Open-Meteo cache: weather at the hour nearest to the start
"""

import json
from pathlib import Path

import polars as pl

from myfitness.config import RAW_ACTIVITIES, RAW_WEATHER

GARMIN_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%.f"


def read_details(directory: Path = RAW_ACTIVITIES) -> pl.DataFrame:
    """All detail JSONs as one flat table.

    json_normalize flattens nested objects into dotted column names,
    e.g. {"summaryDTO": {"distance": 5000}} -> column "summaryDTO.distance".
    max_level=1 stops after the first level; deeper lists stay untouched.
    """
    documents = [json.loads(path.read_text()) for path in sorted(directory.glob("*.json"))]
    return pl.json_normalize(documents, max_level=1, infer_schema_length=None)


def details_table(details: pl.DataFrame) -> pl.DataFrame:
    summary = "summaryDTO."
    return details.select(
        activity_id=pl.col("activityId").cast(pl.Int64),
        activity_type=pl.col("activityTypeDTO.typeKey"),
        name=pl.col("activityName"),
        start_utc=pl.col(summary + "startTimeGMT").str.to_datetime(
            GARMIN_TIME_FORMAT, time_zone="UTC"
        ),
        # Local wall-clock time as the watch showed it. Used for the local
        # date of an activity (PLAN.md section 6).
        start_local=pl.col(summary + "startTimeLocal").str.to_datetime(GARMIN_TIME_FORMAT),
        # Three notions of time, as Garmin Connect shows them:
        # duration = timer time ("Zeit", without pauses), elapsed = start to end,
        # moving = timer time without standing still.
        duration_s=pl.col(summary + "duration"),
        elapsed_s=pl.col(summary + "elapsedDuration"),
        moving_s=pl.col(summary + "movingDuration"),
        distance_m=pl.col(summary + "distance"),
        avg_hr=pl.col(summary + "averageHR"),
        max_hr=pl.col(summary + "maxHR"),
        avg_speed_mps=pl.col(summary + "averageSpeed"),
        elevation_gain_m=pl.col(summary + "elevationGain"),
        start_lat=pl.col(summary + "startLatitude"),
        start_lon=pl.col(summary + "startLongitude"),
        training_load=pl.col(summary + "activityTrainingLoad"),
    )


def read_weather(directory: Path = RAW_WEATHER) -> pl.DataFrame:
    """All cached Open-Meteo responses as one hourly table."""
    frames = []
    for path in sorted(directory.glob("*.json")):
        hourly = json.loads(path.read_text())["hourly"]
        frames.append(
            pl.DataFrame(hourly).with_columns(activity_id=pl.lit(int(path.stem), dtype=pl.Int64))
        )
    if not frames:
        return pl.DataFrame(
            schema={
                "activity_id": pl.Int64,
                "hour_utc": pl.Datetime("us", "UTC"),
                "temp_c": pl.Float64,
                "humidity_pct": pl.Float64,
                "wind_kmh": pl.Float64,
            }
        )
    return pl.concat(frames, how="diagonal_relaxed").select(
        "activity_id",
        hour_utc=pl.col("time").str.to_datetime("%Y-%m-%dT%H:%M", time_zone="UTC"),
        temp_c=pl.col("temperature_2m").cast(pl.Float64),
        humidity_pct=pl.col("relative_humidity_2m").cast(pl.Float64),
        wind_kmh=pl.col("wind_speed_10m").cast(pl.Float64),
    )


def build_activities(sessions: pl.DataFrame) -> pl.DataFrame:
    details = details_table(read_details())
    weather = read_weather()

    # Same rule as ingest.weather.nearest_hour: round to the nearest full hour.
    start_hour = (pl.col("start_utc") + pl.duration(minutes=30)).dt.truncate("1h")

    activities = (
        details.join(sessions, on="activity_id", how="left")
        .with_columns(hour_utc=start_hour)
        .join(weather, on=["activity_id", "hour_utc"], how="left")
        .drop("hour_utc")
        .sort("start_utc")
    )

    first_columns = ["activity_id", "sport", "sub_sport", "activity_type", "name"]
    # Unpack the list: in Polars 2 a plain list inside select() is a literal value.
    return activities.select(*first_columns, pl.exclude(first_columns))

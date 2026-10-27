"""daily.parquet: one row per calendar day.

Each daily endpoint is stored as overlapping window files
(raw/garmin/daily/{endpoint}/{start}_{end}.json). For a day that appears in
several files, the file with the latest end date wins, because it was
loaded after the watch had synced.

Sleep belongs to Garmin's calendarDate, i.e. the day of waking up.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from myfitness.config import RAW_DAILY

# Garmin marks missing values in some fields with negative numbers
# (e.g. stress level -1 or -2).
NON_NEGATIVE = ["resting_hr", "avg_stress", "body_battery_high", "body_battery_low", "steps"]


def read_endpoint(
    endpoint: str,
    entries_of: Callable[[Any], list[dict[str, Any]]],
    columns: dict[str, str],
    date_field: str = "calendarDate",
) -> pl.DataFrame:
    """Read all window files of one endpoint into one row per date.

    entries_of: extracts the list of daily entries from a file's JSON
    columns:    output name -> dotted source path after json_normalize
    """
    frames = []
    for path in sorted((RAW_DAILY / endpoint).glob("*_*.json")):
        entries = entries_of(json.loads(path.read_text()))
        if not entries:
            continue
        window_end = date.fromisoformat(path.stem.split("_")[1])
        flat = pl.json_normalize(entries, infer_schema_length=None)
        missing = [pl.lit(None).alias(source) for source in columns.values() if source not in flat.columns]
        frames.append(
            flat.with_columns(missing).select(
                date=pl.col(date_field).str.to_date(),
                window_end=pl.lit(window_end),
                **{name: pl.col(source) for name, source in columns.items()},
            )
        )
    if not frames:
        return pl.DataFrame({"date": []}, schema={"date": pl.Date})

    all_windows = pl.concat(frames, how="vertical_relaxed")
    # Keep, per date, the row from the most recently loaded window.
    latest = all_windows.sort("window_end").unique(subset="date", keep="last")
    return latest.drop("window_end")


def summaries() -> pl.DataFrame:
    return read_endpoint(
        "daily_summaries",
        lambda doc: (doc or {}).get("data", []),
        {
            "resting_hr": "heartRate.restingValue",
            "body_battery_high": "bodyBattery.maxValue",
            "body_battery_low": "bodyBattery.minValue",
        },
    )


def hrv() -> pl.DataFrame:
    return read_endpoint(
        "daily_hrv_summaries",
        lambda doc: (doc or {}).get("hrvSummaries", []),
        {"hrv_overnight_avg": "lastNightAvg", "hrv_status": "status"},
    )


def sleep() -> pl.DataFrame:
    return read_endpoint(
        "daily_sleep_summaries",
        lambda doc: doc or [],
        {
            "sleep_duration_s": "sleepTimeSeconds",
            "sleep_score": "sleepScores.overall.value",
            "sleep_deep_s": "deepSleepSeconds",
            "sleep_light_s": "lightSleepSeconds",
            "sleep_rem_s": "remSleepSeconds",
            "sleep_awake_s": "awakeSleepSeconds",
        },
    )


def stress() -> pl.DataFrame:
    return read_endpoint(
        "daily_stress", lambda doc: doc or [], {"avg_stress": "values.overallStressLevel"}
    )


def steps() -> pl.DataFrame:
    return read_endpoint("daily_steps", lambda doc: doc or [], {"steps": "totalSteps"})


def weight() -> pl.DataFrame:
    """Measured weight per day (latest measurement of the day), in kg."""
    measurements = read_endpoint(
        "weight_measurements",
        lambda doc: (doc or {}).get("dailyWeightSummaries", []),
        {"weight_g": "latestWeight.weight"},
        date_field="summaryDate",
    )
    return measurements.select("date", weight_kg=pl.col("weight_g") / 1000)


def build_daily() -> pl.DataFrame:
    sources = [summaries(), hrv(), sleep(), stress(), steps(), weight()]

    # A complete calendar from the first to the last day with any data,
    # so that missing days show up as rows with nulls.
    first_day = min(s["date"].min() for s in sources if s.height > 0)
    last_day = max(s["date"].max() for s in sources if s.height > 0)
    daily = pl.DataFrame({"date": pl.date_range(first_day, last_day, "1d", eager=True)})

    for source in sources:
        daily = daily.join(source, on="date", how="left")

    negative_to_null = [
        pl.when(pl.col(c) >= 0).then(pl.col(c)).alias(c) for c in NON_NEGATIVE
    ]
    # forward_fill depends on row order, and joins do not guarantee it.
    return daily.sort("date").with_columns(negative_to_null).with_columns(
        # Weight is measured only now and then; carry the last value forward.
        weight_kg_ffill=pl.col("weight_kg").forward_fill(),
    )

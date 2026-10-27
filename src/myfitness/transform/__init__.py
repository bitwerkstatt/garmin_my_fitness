"""Turn raw files into clean tables in data/processed/.

The tables are rebuilt from data/raw/ on every run; there is no
incremental state to keep consistent.
"""

import logging

import polars as pl

from myfitness.config import PROCESSED, RAW_FIT

log = logging.getLogger(__name__)


def write_table(frame: pl.DataFrame, name: str) -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    path = PROCESSED / f"{name}.parquet"
    frame.write_parquet(path)
    log.info("%s: %d Zeilen -> %s", name, frame.height, path.name)


def clip_to_activity(records: pl.DataFrame, activities: pl.DataFrame) -> pl.DataFrame:
    """Drop records outside [start, start + elapsed] of their activity.

    An activity trimmed in Garmin Connect keeps its original FIT file, so
    the FIT records reach beyond what Connect counts as the activity.
    """
    window = activities.select(
        "activity_id",
        window_start=pl.col("start_utc"),
        window_end=pl.col("start_utc") + pl.duration(seconds=pl.col("elapsed_s")),
    )
    inside = pl.col("timestamp_utc").is_between(pl.col("window_start"), pl.col("window_end"))
    clipped = records.join(window, on="activity_id", how="left").filter(inside)
    return (
        clipped.drop("window_start", "window_end")
        .with_columns(
            # elapsed_s restarts at 0 for the first remaining record
            elapsed_s=pl.col("elapsed_s") - pl.col("elapsed_s").min().over("activity_id"),
        )
        .sort("activity_id", "timestamp_utc")
    )


def transform_all() -> None:
    # Imported here to keep `import myfitness.transform` light.
    from myfitness.config import load_settings
    from myfitness.metrics import activity_metrics, training_load
    from myfitness.transform.activities import build_activities
    from myfitness.transform.daily import build_daily
    from myfitness.transform.records import build_fit_tables
    from myfitness.transform.zones import build_hr_zones

    settings = load_settings()
    if settings.hr_max is None or settings.sex is None:
        raise SystemExit("config.toml: hr_max und sex fehlen (Vorlage: config.example.toml)")

    log.info("FIT-Dateien dekodieren ...")
    fit_tables = build_fit_tables(sorted(RAW_FIT.glob("*.zip")))
    activities = build_activities(fit_tables.sessions)
    records = clip_to_activity(fit_tables.records, activities)
    daily = build_daily()
    write_table(records, "records")
    write_table(fit_tables.laps, "laps")
    write_table(activities, "activities")
    write_table(daily, "daily")
    write_table(build_hr_zones(), "hr_zones")

    metrics = activity_metrics(records, activities, daily, settings.hr_max, settings.sex)
    write_table(metrics, "activity_metrics")
    write_table(training_load(metrics, activities), "training_load")

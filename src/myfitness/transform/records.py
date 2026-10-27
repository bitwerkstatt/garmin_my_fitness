"""FIT files -> records, laps and session tables.

Each FIT file is decoded once; the three tables are built from the same
decoded messages. Units follow PLAN.md section 6 (column suffixes name the
unit: _s, _m, _mps, _mm, _ms, _pct, _spm, _w).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from myfitness.transform.fit import (
    FOOT_SPORTS,
    decode_fit_zip,
    semicircles_to_degrees,
    sport_of,
    steps_per_minute,
    to_frame,
    with_missing_columns,
)

Messages = dict[str, list[dict[str, Any]]]

RECORD_SOURCE_COLUMNS = [
    "timestamp",
    "distance",
    "enhanced_speed",
    "heart_rate",
    "cadence",
    "fractional_cadence",
    "step_length",
    "vertical_oscillation",
    "vertical_ratio",
    "stance_time",
    "enhanced_respiration_rate",
    "power",
    "enhanced_altitude",
    "position_lat",
    "position_long",
]

LAP_SOURCE_COLUMNS = [
    "start_time",
    "total_timer_time",
    "total_elapsed_time",
    "total_distance",
    "avg_heart_rate",
    "enhanced_avg_speed",
    "avg_running_cadence",
    "avg_cadence",
    "avg_fractional_cadence",
]


@dataclass
class FitTables:
    records: pl.DataFrame
    laps: pl.DataFrame
    sessions: pl.DataFrame


def records_frame(activity_id: int, sport: str, messages: Messages) -> pl.DataFrame:
    """One row per record (about one per second), units normalised."""
    raw = to_frame(messages.get("record_mesgs", []))
    if raw.height == 0:
        return pl.DataFrame()
    raw = with_missing_columns(raw, RECORD_SOURCE_COLUMNS)

    first_timestamp = raw["timestamp"].min()
    return raw.select(
        activity_id=pl.lit(activity_id, dtype=pl.Int64),
        timestamp_utc=pl.col("timestamp"),
        elapsed_s=(pl.col("timestamp") - first_timestamp).dt.total_seconds().cast(pl.Float64),
        distance_m=pl.col("distance").cast(pl.Float64),
        speed_mps=pl.col("enhanced_speed").cast(pl.Float64),
        heart_rate=pl.col("heart_rate").cast(pl.Float64),
        cadence_spm=steps_per_minute("cadence", "fractional_cadence", sport).cast(pl.Float64),
        step_length_mm=pl.col("step_length").cast(pl.Float64),
        vertical_oscillation_mm=pl.col("vertical_oscillation").cast(pl.Float64),
        vertical_ratio_pct=pl.col("vertical_ratio").cast(pl.Float64),
        stance_time_ms=pl.col("stance_time").cast(pl.Float64),
        respiration_rate=pl.col("enhanced_respiration_rate").cast(pl.Float64),
        power_w=pl.col("power").cast(pl.Float64),
        altitude_m=pl.col("enhanced_altitude").cast(pl.Float64),
        lat=semicircles_to_degrees("position_lat").cast(pl.Float64),
        lon=semicircles_to_degrees("position_long").cast(pl.Float64),
    )


def laps_frame(activity_id: int, sport: str, messages: Messages) -> pl.DataFrame:
    """One row per lap. Strength training and similar have no laps."""
    raw = to_frame(messages.get("lap_mesgs", []))
    if raw.height == 0:
        return pl.DataFrame()
    raw = with_missing_columns(raw, LAP_SOURCE_COLUMNS)

    # Running laps carry the per-leg cadence in avg_running_cadence,
    # walking laps only in avg_cadence.
    per_leg_cadence = pl.coalesce("avg_running_cadence", "avg_cadence")
    return raw.with_columns(per_leg_cadence=per_leg_cadence).select(
        activity_id=pl.lit(activity_id, dtype=pl.Int64),
        lap_index=pl.int_range(pl.len(), dtype=pl.Int32),
        start_utc=pl.col("start_time"),
        duration_s=pl.col("total_timer_time").cast(pl.Float64),
        elapsed_s=pl.col("total_elapsed_time").cast(pl.Float64),
        distance_m=pl.col("total_distance").cast(pl.Float64),
        avg_hr=pl.col("avg_heart_rate").cast(pl.Float64),
        avg_speed_mps=pl.col("enhanced_avg_speed").cast(pl.Float64),
        avg_cadence_spm=steps_per_minute(
            "per_leg_cadence", "avg_fractional_cadence", sport
        ).cast(pl.Float64),
    )


def session_row(activity_id: int, sport: str, messages: Messages) -> dict[str, Any]:
    """The FIT session values that the detail JSON does not provide."""
    session = (messages.get("session_mesgs") or [{}])[0]
    per_leg_cadence = session.get("avg_running_cadence") or session.get("avg_cadence")
    avg_cadence_spm = None
    if sport in FOOT_SPORTS and per_leg_cadence is not None:
        avg_cadence_spm = 2 * (per_leg_cadence + (session.get("avg_fractional_cadence") or 0))
    return {
        "activity_id": activity_id,
        "sport": sport,
        "sub_sport": session.get("sub_sport"),
        "avg_cadence_spm": avg_cadence_spm,
        "avg_respiration_rate": session.get("enhanced_avg_respiration_rate"),
        "workout_rpe": session.get("workout_rpe"),
        "workout_feel": session.get("workout_feel"),
    }


def build_fit_tables(zip_paths: Iterable[Path]) -> FitTables:
    records, laps, sessions = [], [], []
    for zip_path in zip_paths:
        activity_id = int(zip_path.stem)
        messages = decode_fit_zip(zip_path)
        sport = sport_of(messages) or "unknown"
        records.append(records_frame(activity_id, sport, messages))
        laps.append(laps_frame(activity_id, sport, messages))
        sessions.append(session_row(activity_id, sport, messages))

    # Empty frames (activities without records or laps) are left out.
    return FitTables(
        records=pl.concat([r for r in records if r.height > 0]),
        laps=pl.concat([lap for lap in laps if lap.height > 0]),
        sessions=pl.from_dicts(sessions, infer_schema_length=None),
    )

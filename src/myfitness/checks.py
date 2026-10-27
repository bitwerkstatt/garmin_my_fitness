"""Plausibility checks for the formulas in metrics.py.

Each check builds a synthetic activity whose result can be worked out by
hand and compares it with the function's output.

Run: uv run python -m myfitness.checks
"""

import math
import sys
from datetime import UTC, date, datetime, timedelta

import polars as pl

from myfitness import metrics

START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


def segment(seconds: int, speed_mps: float, heart_rate: float | None) -> list[tuple[float, float | None]]:
    return [(speed_mps, heart_rate)] * seconds


def synthetic_run(activity_id: int, segments: list[list[tuple[float, float | None]]]) -> pl.DataFrame:
    """One record per second, built from consecutive segments."""
    samples = [sample for part in segments for sample in part]
    return pl.DataFrame(
        {
            "activity_id": [activity_id] * len(samples),
            "timestamp_utc": [START + timedelta(seconds=i) for i in range(len(samples))],
            "speed_mps": [speed for speed, _ in samples],
            "heart_rate": [hr for _, hr in samples],
        },
        schema_overrides={"heart_rate": pl.Float64},
    )


# Activity 1: 60 min moving time, steady pace.
#   10 min warm-up at 2.5 m/s / 120 bpm             -> excluded (warm-up)
#   25 min at 3.0 m/s / 150 bpm, with a 2 min stop  -> stop excluded (not moving)
#   25 min at 3.0 m/s / 165 bpm, 50 s without HR    -> missing HR ignored
# 3.0 m/s = 180 m/min. EF1 = 180/150 = 1.2, EF2 = 180/165.
# Mean HR over the records with HR: (1500 x 150 + 1450 x 165) / 2950.
STEADY_RUN = synthetic_run(
    1,
    [
        segment(600, 2.5, 120),
        segment(700, 3.0, 150),
        segment(120, 0.0, 130),
        segment(800, 3.0, 150),
        segment(1450, 3.0, 165),
        segment(50, 3.0, None),
    ],
)

# Activity 2: 20 min -> too short for EF.
SHORT_RUN = synthetic_run(2, [segment(1200, 3.0, 150)])

# Activity 3: 50 min alternating 2 and 4 m/s every minute -> speed CV about
# 0.33, too uneven for decoupling; EF still exists.
UNEVEN_RUN = synthetic_run(
    3, [segment(60, 2.0 if minute % 2 == 0 else 4.0, 150) for minute in range(50)]
)


def check(name: str, actual: float | None, expected: float | None, tolerance: float = 1e-9) -> bool:
    if expected is None:
        passed = actual is None
    else:
        passed = actual is not None and math.isclose(actual, expected, abs_tol=tolerance)
    print(f"{'OK  ' if passed else 'FAIL'} {name}: erwartet {expected}, erhalten {actual}")
    return passed


def value(frame: pl.DataFrame, activity_id: int, column: str) -> float | None:
    rows = frame.filter(pl.col("activity_id") == activity_id)
    return rows[column].item() if rows.height == 1 else None


def run_checks() -> bool:
    records = pl.concat([STEADY_RUN, SHORT_RUN, UNEVEN_RUN])
    result = metrics.running_metrics(records)

    ef_first = 180 / 150
    ef_second = 180 / 165
    mean_hr = (1500 * 150 + 1450 * 165) / 2950
    results = [
        check("EF gleichmäßiger Lauf", value(result, 1, "ef"), 180 / mean_hr),
        check("EF erste Hälfte", value(result, 1, "ef_first_half"), ef_first),
        check("EF zweite Hälfte", value(result, 1, "ef_second_half"), ef_second),
        check(
            "Entkopplung in %",
            value(result, 1, "decoupling_pct"),
            (ef_first - ef_second) / ef_first * 100,
        ),
        check("EF-Basis: 50 min bewegt nach Aufwärmen", value(result, 1, "ef_moving_s"), 3000.0),
        check("kurzer Lauf ohne EF", value(result, 2, "ef"), None),
        check("ungleichmäßiger Lauf: EF vorhanden", value(result, 3, "ef"), 180 / 150, tolerance=0.01),
        check("ungleichmäßiger Lauf: keine Entkopplung", value(result, 3, "decoupling_pct"), None),
    ]
    return all(results)


# --- training load -----------------------------------------------------------

# Resting HR 60, HR_max 180: HR 120 gives HRr = (120 - 60) / (180 - 60) = 0.5.
HR_REST, HR_MAX = 60.0, 180.0
LOAD_DAY = date(2026, 1, 1)


def load_inputs() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Three activities on LOAD_DAY.

    10: records, 60 min at 120 bpm plus 10 min at 50 bpm (below rest -> 0)
    11: no records, mean HR 120 for 30 min -> fallback to the average
    12: no records and no HR -> TRIMP 0, source "none"
    """
    records = synthetic_run(10, [segment(3600, 2.0, 120), segment(600, 0.0, 50)])
    activities = pl.DataFrame(
        {
            "activity_id": [10, 11, 12],
            "sport": ["running", "cycling", "training"],
            "start_local": [datetime(2026, 1, 1, 9)] * 3,
            "duration_s": [4200.0, 1800.0, 900.0],
            "avg_hr": [120.0, 120.0, None],
        }
    )
    daily = pl.DataFrame({"date": [LOAD_DAY], "resting_hr": [HR_REST]})
    return records, activities, daily


def run_load_checks() -> bool:
    records, activities, daily = load_inputs()
    trimp = metrics.trimp(records, activities, daily, HR_MAX, "male")
    k1, k2 = metrics.TRIMP_CONSTANTS["male"]
    per_minute_at_half = 0.5 * k1 * math.exp(k2 * 0.5)

    results = [
        check("TRIMP aus Records (60 min bei HRr 0,5)", value(trimp, 10, "trimp"), 60 * per_minute_at_half),
        check("TRIMP aus Ø-HF (30 min bei HRr 0,5)", value(trimp, 11, "trimp"), 30 * per_minute_at_half),
        check("TRIMP ohne HF", value(trimp, 12, "trimp"), 0.0),
    ]
    sources = dict(trimp.select("activity_id", "trimp_source").rows())
    sources_ok = sources == {10: "records", 11: "average", 12: "none"}
    print(f"{'OK  ' if sources_ok else 'FAIL'} trimp_source: {sources}")
    results.append(sources_ok)

    # One load of 42 on the first day, then rest. From 0:
    # CTL = 42/42 = 1, ATL = 42/7 = 6; afterwards ATL decays by 6/7 per day.
    one_load = pl.DataFrame({"activity_id": [1], "trimp": [42.0]})
    one_activity = pl.DataFrame(
        {"activity_id": [1], "sport": ["running"], "start_local": [datetime(2026, 1, 1, 9)]}
    )
    series = metrics.training_load(one_load, one_activity, until=date(2026, 1, 10))

    def on(day: int, column: str) -> float:
        return series.filter(pl.col("date") == date(2026, 1, day))[column].item()

    results += [
        check("Vortag beginnt bei 0", series.filter(pl.col("date") == date(2025, 12, 31))["ctl"].item(), 0.0),
        check("CTL nach Belastung 42", on(1, "ctl"), 1.0),
        check("ATL nach Belastung 42", on(1, "atl"), 6.0),
        check("ATL nach 7 Ruhetagen", on(8, "atl"), 6 * (6 / 7) ** 7),
        check("TSB am Morgen danach = CTL - ATL des Vortags", on(2, "tsb"), 1.0 - 6.0),
    ]
    return all(results)


if __name__ == "__main__":
    print("Effizienz:")
    efficiency_ok = run_checks()
    print("\nBelastung:")
    load_ok = run_load_checks()
    sys.exit(0 if efficiency_ok and load_ok else 1)

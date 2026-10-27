"""Correlation toolkit (PLAN.md M4).

Two levels:
- between runs: one row per run with aggregated running metrics, context
  (weather, climb, weight) and daily values of the nights/days before
- within a run: moving records, optionally bundled into time windows

Lag convention (confirmed 27.10.2026): lag k = daily value of the run date
minus k days. Garmin assigns sleep and HRV to the day of waking up, so the
night values at lag 0 describe the night right before the run. Day values
(stress, steps, Body Battery) cover the whole day including the run and
therefore start at lag 1.

Typical use in a notebook:
    runs = explore.run_table()
    explore.investigate(runs, "sleep_score_lag0", "ef")
"""

from dataclasses import dataclass
from datetime import date

import polars as pl

from myfitness.config import PROCESSED
from myfitness.metrics import MOVING_SPEED_MPS

NIGHT_COLUMNS = [
    "sleep_duration_s",
    "sleep_score",
    "sleep_deep_s",
    "sleep_rem_s",
    "hrv_overnight_avg",
    "resting_hr",
]
DAY_COLUMNS = ["avg_stress", "steps", "body_battery_high", "body_battery_low"]
LAGS = (0, 1, 2)

RECORD_METRICS = [
    "speed_mps",
    "heart_rate",
    "cadence_spm",
    "step_length_mm",
    "vertical_oscillation_mm",
    "vertical_ratio_pct",
    "stance_time_ms",
    "respiration_rate",
    "power_w",
]

# Running metrics of Leitfrage 3, as named in run_table()
RUN_METRICS = [
    "pace_min_per_km",
    "moving_hr",
    "cadence_spm",
    "step_length_mm",
    "vertical_ratio_pct",
    "vertical_oscillation_mm",
    "stance_time_ms",
    "respiration_rate",
    "ef",
]


@dataclass(frozen=True)
class Filters:
    """Common filters for both levels. None means: do not filter."""

    sport: str | None = "running"
    start: date | None = None
    end: date | None = None
    min_moving_s: float | None = None
    # Garmin zone 1-5. Between runs: zone of the run's mean HR.
    # Within a run: zone of each record's (or window's) HR.
    hr_zone: int | None = None


def scan(table: str) -> pl.LazyFrame:
    """Lazy view of a processed table.

    scan_parquet reads nothing yet; Polars first collects all filters and
    selections of the query and then reads only the needed columns and rows.
    """
    return pl.scan_parquet(PROCESSED / f"{table}.parquet")


def zone_condition(column: str, zone: int) -> pl.Expr:
    zones = pl.read_parquet(PROCESSED / "hr_zones.parquet")
    bounds = zones.filter(pl.col("zone") == zone).row(0, named=True)
    above_floor = pl.col(column) >= bounds["floor_bpm"]
    if bounds["ceiling_bpm"] is None:
        return above_floor
    return above_floor & (pl.col(column) < bounds["ceiling_bpm"])


def filtered_activities(filters: Filters) -> pl.LazyFrame:
    activities = scan("activities")
    conditions = []
    if filters.sport is not None:
        conditions.append(pl.col("sport") == filters.sport)
    if filters.start is not None:
        conditions.append(pl.col("start_local").dt.date() >= filters.start)
    if filters.end is not None:
        conditions.append(pl.col("start_local").dt.date() <= filters.end)
    if filters.min_moving_s is not None:
        conditions.append(pl.col("moving_s") >= filters.min_moving_s)
    return activities.filter(*conditions) if conditions else activities


def moving_records(filters: Filters) -> pl.LazyFrame:
    """Records of the filtered activities while moving (same rule as metrics.py)."""
    activity_ids = filtered_activities(filters).select("activity_id")
    return (
        scan("records")
        .join(activity_ids, on="activity_id", how="semi")
        .filter(pl.col("speed_mps") >= MOVING_SPEED_MPS)
    )


# --- between runs -------------------------------------------------------------


def run_aggregates(filters: Filters) -> pl.LazyFrame:
    """Per run: mean of every record metric over the moving time."""
    return (
        moving_records(filters)
        .group_by("activity_id")
        .agg(
            pl.col("speed_mps").mean().alias("moving_speed_mps"),
            pl.col("heart_rate").mean().alias("moving_hr"),
            *[pl.col(c).mean() for c in RECORD_METRICS if c not in ("speed_mps", "heart_rate")],
        )
    )


def daily_lags(lags: tuple[int, ...] = LAGS) -> pl.LazyFrame:
    """Daily values shifted by k days, one column per value and lag.

    For lag k, the daily row of date d is relabelled with run_date d + k,
    so a plain join on run_date finds "the value k days before the run".
    """
    daily = scan("daily")
    lagged = None
    for lag in lags:
        columns = NIGHT_COLUMNS + (DAY_COLUMNS if lag >= 1 else [])
        shifted = daily.select(
            run_date=pl.col("date") + pl.duration(days=lag),
            *[pl.col(c).alias(f"{c}_lag{lag}") for c in columns],
        )
        lagged = shifted if lagged is None else lagged.join(shifted, on="run_date", how="full", coalesce=True)
    return lagged


def latest_weight() -> pl.LazyFrame:
    """Measured weights only, sorted - the right side of the join_asof below."""
    return (
        scan("daily")
        .filter(pl.col("weight_kg").is_not_null())
        .select(weight_date=pl.col("date"), weight_kg="weight_kg")
        .sort("weight_date")
    )


def with_ef_trend(runs: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Add the trailing 28-day mean of the EF and each run's deviation from it.

    rolling_mean_by uses a time window instead of a fixed number of rows:
    for each run it averages all runs with EF of the 28 days up to and
    including it. ef_vs_trend removes the slow fitness trend, which
    otherwise mixes with everything that changes with the seasons.
    """
    runs = runs.lazy().sort("start_local")
    trend = runs.filter(pl.col("ef").is_not_null()).select(
        "activity_id",
        ef_28d=pl.col("ef").rolling_mean_by("start_local", window_size="28d"),
    )
    # A join does not guarantee row order, so sort again afterwards.
    return (
        runs.join(trend, on="activity_id", how="left")
        .with_columns(ef_vs_trend=pl.col("ef") - pl.col("ef_28d"))
        .sort("start_local")
    )


def run_table(filters: Filters = Filters()) -> pl.DataFrame:
    """One row per run: running metrics, EF, context and daily lags."""
    context = filtered_activities(filters).select(
        "activity_id",
        "start_local",
        "name",
        "distance_m",
        "moving_s",
        "elevation_gain_m",
        "temp_c",
        "humidity_pct",
        "wind_kmh",
        "training_load",
        "workout_rpe",
        "workout_feel",
        run_date=pl.col("start_local").dt.date(),
        climb_m_per_km=pl.col("elevation_gain_m") / (pl.col("distance_m") / 1000),
    )
    metrics = scan("activity_metrics").select("activity_id", "ef", "decoupling_pct")

    runs = (
        context.join(run_aggregates(filters), on="activity_id", how="left")
        .join(metrics, on="activity_id", how="left")
        .with_columns(pace_min_per_km=1000 / 60 / pl.col("moving_speed_mps"))
        .sort("run_date")
        # join_asof: for each run take the last weight measured on or before
        # the run date ("backward"), however many days ago that was.
        .join_asof(latest_weight(), left_on="run_date", right_on="weight_date", strategy="backward")
        .join(daily_lags(), on="run_date", how="left")
        .pipe(with_ef_trend)
    )
    if filters.hr_zone is not None:
        runs = runs.filter(zone_condition("moving_hr", filters.hr_zone))
    return runs.sort("start_local").collect()


def with_training_load(runs: pl.DataFrame, rest_day_trimp: float = 10.0) -> pl.DataFrame:
    """Add the load model of the run day (from training_load.parquet).

    ctl, atl, tsb:   values of the run day; tsb is the form that morning
    trimp_prev_day:  total TRIMP of the day before the run
    rest_day_before: trimp_prev_day below rest_day_trimp (a walk is not training)
    """
    load = pl.read_parquet(PROCESSED / "training_load.parquet")
    run_day = load.select(run_date="date", ctl="ctl", atl="atl", tsb="tsb")
    previous_day = load.select(run_date=pl.col("date") + pl.duration(days=1), trimp_prev_day="trimp")
    return (
        runs.join(run_day, on="run_date", how="left")
        .join(previous_day, on="run_date", how="left")
        .with_columns(rest_day_before=pl.col("trimp_prev_day") < rest_day_trimp)
        .sort("start_local")
    )


# --- within a run -------------------------------------------------------------


def within_run_table(filters: Filters = Filters(), window: str | None = "30s") -> pl.DataFrame:
    """Moving records, bundled into time windows per run (or raw if window=None).

    group_by_dynamic cuts the time axis into fixed windows (here every 30 s)
    and aggregates each window; group_by="activity_id" restarts the windows
    for every run. Bundling smooths the second-by-second noise.
    """
    records = moving_records(filters)
    if window is not None:
        records = (
            records.sort("activity_id", "timestamp_utc")
            .group_by_dynamic("timestamp_utc", every=window, group_by="activity_id")
            .agg(*[pl.col(c).mean() for c in RECORD_METRICS], records=pl.len())
        )
    if filters.hr_zone is not None:
        records = records.filter(zone_condition("heart_rate", filters.hr_zone))
    return records.collect()


# --- correlations -------------------------------------------------------------


def correlate(frame: pl.DataFrame, x: str, y: str) -> dict[str, float | int | None]:
    """Pearson r, Spearman rho and n over the rows where both values exist."""
    if x == y:
        n = frame[x].drop_nulls().len()
        return {"x": x, "y": y, "pearson": 1.0, "spearman": 1.0, "n": n}
    pair = frame.select(x, y).drop_nulls()
    if pair.height < 3:
        return {"x": x, "y": y, "pearson": None, "spearman": None, "n": pair.height}
    stats = pair.select(
        pearson=pl.corr(x, y, method="pearson"),
        spearman=pl.corr(x, y, method="spearman"),
    ).row(0, named=True)
    return {"x": x, "y": y, **stats, "n": pair.height}


def correlations(frame: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """All pairs of columns in long format (x, y, pearson, spearman, n)."""
    rows = [correlate(frame, x, y) for x in columns for y in columns]
    return pl.DataFrame(rows, schema_overrides={"pearson": pl.Float64, "spearman": pl.Float64})


def correlation_matrix(frame: pl.DataFrame, columns: list[str], method: str = "spearman") -> pl.DataFrame:
    """Square matrix: one row per x, one column per y."""
    long = correlations(frame, columns)
    # pivot turns the long table (one row per pair) into the wide matrix.
    return long.pivot(on="y", index="x", values=method).select("x", *columns)


def lag_correlations(
    runs: pl.DataFrame, daily_value: str, run_metric: str, lags: tuple[int, ...] = LAGS
) -> pl.DataFrame:
    """Correlation of a daily value at each available lag with a run metric."""
    rows = []
    for lag in lags:
        column = f"{daily_value}_lag{lag}"
        if column in runs.columns:
            rows.append({"lag": lag, **correlate(runs, column, run_metric)})
    return pl.DataFrame(rows, schema_overrides={"pearson": pl.Float64, "spearman": pl.Float64})


def within_run_correlations(windows: pl.DataFrame, x: str, y: str, min_windows: int = 20) -> pl.DataFrame:
    """Correlation of x and y computed separately inside each run.

    Pooling the windows of all runs mixes in differences between runs (an
    easy run has both low HR and low breathing rate). Correlating per run
    and looking at the distribution answers the within-run question.
    """
    pairs = windows.select("activity_id", x, y).drop_nulls()
    return (
        pairs.group_by("activity_id")
        .agg(
            n=pl.len(),
            pearson=pl.corr(x, y, method="pearson"),
            spearman=pl.corr(x, y, method="spearman"),
        )
        .filter(pl.col("n") >= min_windows)
        .sort("activity_id")
    )


def investigate(frame: pl.DataFrame, x: str, y: str) -> dict[str, float | int | None]:
    """One-cell look at a pair: scatter with regression line plus r, rho and n."""
    from myfitness import plots

    stats = correlate(frame, x, y)
    plots.plot_pair(frame, x, y, stats)
    return stats

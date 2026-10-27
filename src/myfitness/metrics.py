"""Training metrics computed from records.

Definitions (PLAN.md M3, confirmed 27.10.2026):

- Moving time: records with speed >= MOVING_SPEED_MPS. Standing at a traffic
  light with the timer running does not count. Warm-up and minimum
  durations are measured in moving time.
- Efficiency factor (EF) = mean speed [m/min] / mean heart rate, over the
  moving time after WARMUP_S. Only for runs with at least EF_MIN_MOVING_S
  moving time (warm-up included).
- Aerobic decoupling = (EF1 - EF2) / EF1 x 100, where EF1 and EF2 are the
  EFs of the first and second half of the moving time after the warm-up.
  Only for runs with at least DECOUPLING_MIN_MOVING_S moving time and an
  even pace: coefficient of variation of speed below STEADY_SPEED_CV_MAX.

Means are time-weighted: each record counts with the seconds since the
previous record (capped at MAX_RECORD_WEIGHT_S, so a timer pause does not
count as moving time).

Training load (PLAN.md M5, parameters confirmed 27.10.2026):

- TRIMP (Banister) = sum of dt[min] x HRr x k1 x exp(k2 x HRr) with
  HRr = (HR - HR_rest) / (HR_max - HR_rest), clipped to [0, 1].
  HR_max and the sex-specific k1/k2 come from config.toml; HR_rest is the
  resting HR of the activity's local date (or the last known one before).
  All recorded time counts, standing included (unlike EF). Without records
  the activity's mean HR and timer duration are used; without any HR the
  TRIMP is 0 and trimp_source says "none".
- CTL / ATL: exponentially weighted daily TRIMP with time constants of
  42 and 7 days: load_t = load_t-1 + (TRIMP_t - load_t-1) / tau.
  Days without training count as 0; the series starts at 0 on the day
  before the first activity. TSB_t = CTL_t-1 - ATL_t-1 (form on the
  morning of day t, before that day's training).
"""

from datetime import date, timedelta

import polars as pl

MOVING_SPEED_MPS = 1.0
MAX_RECORD_WEIGHT_S = 5.0
WARMUP_S = 10 * 60
EF_MIN_MOVING_S = 30 * 60
DECOUPLING_MIN_MOVING_S = 45 * 60
STEADY_SPEED_CV_MAX = 0.15

TRIMP_CONSTANTS = {"male": (0.64, 1.92), "female": (0.86, 1.67)}
CTL_DAYS = 42
ATL_DAYS = 7


def with_record_weights(records: pl.DataFrame) -> pl.DataFrame:
    """Add weight_s: seconds since the previous record of the same activity.

    diff().over("activity_id") computes the difference to the previous
    record within each activity; the first record of an activity gets null
    and counts as one second. Gaps (timer paused) are capped.
    """
    return records.sort("activity_id", "timestamp_utc").with_columns(
        weight_s=pl.col("timestamp_utc")
        .diff()
        .over("activity_id")
        .dt.total_seconds(fractional=True)
        .fill_null(1.0)
        .clip(0.0, MAX_RECORD_WEIGHT_S),
    )


def moving_records(records: pl.DataFrame) -> pl.DataFrame:
    """Moving records only, with their weight and the cumulative moving time.

    Adds:
      weight_s         seconds this record stands for
      moving_time_s    moving seconds since the start of the activity
      total_moving_s   moving seconds of the whole activity
    """
    moving = with_record_weights(records).filter(pl.col("speed_mps") >= MOVING_SPEED_MPS)
    return moving.with_columns(
        moving_time_s=pl.col("weight_s").cum_sum().over("activity_id"),
        total_moving_s=pl.col("weight_s").sum().over("activity_id"),
    )


def ef_expr(rows: pl.Expr | None = None) -> pl.Expr:
    """EF inside group_by().agg(): weighted mean speed [m/min] / weighted mean HR.

    rows: optional boolean expression to restrict the EF to part of the
    group (e.g. one half of the run). Records without heart rate are left
    out of the HR mean only.
    """
    keep = rows if rows is not None else pl.lit(True)
    weight = pl.col("weight_s").filter(keep)
    speed = pl.col("speed_mps").filter(keep)
    hr = pl.col("heart_rate").filter(keep)

    mean_speed_m_per_min = (speed * weight).sum() / weight.sum() * 60
    mean_hr = (hr * weight).sum() / weight.filter(hr.is_not_null()).sum()
    return mean_speed_m_per_min / mean_hr


def after_warmup(moving: pl.DataFrame) -> pl.DataFrame:
    return moving.filter(pl.col("moving_time_s") > WARMUP_S)


def efficiency_factor(records: pl.DataFrame) -> pl.DataFrame:
    """One row per eligible activity: ef and the moving seconds it is based on."""
    eligible = after_warmup(moving_records(records)).filter(
        pl.col("total_moving_s") >= EF_MIN_MOVING_S
    )
    return eligible.group_by("activity_id").agg(
        ef=ef_expr(),
        ef_moving_s=pl.col("weight_s").sum(),
    )


def aerobic_decoupling(records: pl.DataFrame) -> pl.DataFrame:
    """One row per long activity: EF of both halves, speed CV and decoupling.

    decoupling_pct is null if the pace was not even (speed_cv too high);
    speed_cv stays in the table so the threshold can be revisited.
    """
    eligible = after_warmup(moving_records(records)).filter(
        pl.col("total_moving_s") >= DECOUPLING_MIN_MOVING_S
    )

    # Position within the post-warm-up part: 0 at its start, 1 at its end.
    # Rows in the first half of that moving time belong to half 1.
    post_warmup_s = pl.col("total_moving_s") - WARMUP_S
    in_first_half = (pl.col("moving_time_s") - WARMUP_S) <= post_warmup_s / 2
    with_half = eligible.with_columns(half=pl.when(in_first_half).then(1).otherwise(2))

    ef_per_half = with_half.group_by("activity_id").agg(
        ef_first_half=ef_expr(pl.col("half") == 1),
        ef_second_half=ef_expr(pl.col("half") == 2),
        speed_cv=pl.col("speed_mps").std() / pl.col("speed_mps").mean(),
    )

    decoupling = (
        (pl.col("ef_first_half") - pl.col("ef_second_half")) / pl.col("ef_first_half") * 100
    )
    is_steady = pl.col("speed_cv") < STEADY_SPEED_CV_MAX
    return ef_per_half.with_columns(
        steady=is_steady,
        decoupling_pct=pl.when(is_steady).then(decoupling),
    )


def running_metrics(run_records: pl.DataFrame) -> pl.DataFrame:
    """EF and decoupling per running activity."""
    ef = efficiency_factor(run_records)
    decoupling = aerobic_decoupling(run_records)
    return ef.join(decoupling, on="activity_id", how="left").sort("activity_id")


# --- training load -------------------------------------------------------------


def trimp_expr(heart_rate: pl.Expr, minutes: pl.Expr, hr_max: float, sex: str) -> pl.Expr:
    """Banister TRIMP contribution; expects a column resting_hr in the frame."""
    k1, k2 = TRIMP_CONSTANTS[sex]
    heart_rate_reserve = (
        (heart_rate - pl.col("resting_hr")) / (hr_max - pl.col("resting_hr"))
    ).clip(0.0, 1.0)
    return minutes * heart_rate_reserve * k1 * (k2 * heart_rate_reserve).exp()


def resting_hr_per_activity(activities: pl.DataFrame, daily: pl.DataFrame) -> pl.DataFrame:
    """Resting HR of each activity's local date, or the last known value before it."""
    known = (
        daily.filter(pl.col("resting_hr").is_not_null())
        .select(resting_date="date", resting_hr=pl.col("resting_hr").cast(pl.Float64))
        .sort("resting_date")
    )
    return (
        activities.select("activity_id", activity_date=pl.col("start_local").dt.date())
        .sort("activity_date")
        # join_asof: last resting HR on or before the activity date
        .join_asof(known, left_on="activity_date", right_on="resting_date", strategy="backward")
        .select("activity_id", "resting_hr")
    )


def trimp(
    records: pl.DataFrame,
    activities: pl.DataFrame,
    daily: pl.DataFrame,
    hr_max: float,
    sex: str,
) -> pl.DataFrame:
    """TRIMP per activity with trimp_source = "records" | "average" | "none"."""
    resting = resting_hr_per_activity(activities, daily)

    from_records = (
        with_record_weights(records)
        .filter(pl.col("heart_rate").is_not_null())
        .join(resting, on="activity_id")
        .group_by("activity_id")
        .agg(
            trimp_records=trimp_expr(
                pl.col("heart_rate"), pl.col("weight_s") / 60, hr_max, sex
            ).sum()
        )
    )
    from_average = activities.join(resting, on="activity_id").select(
        "activity_id",
        trimp_average=trimp_expr(pl.col("avg_hr"), pl.col("duration_s") / 60, hr_max, sex),
    )

    combined = (
        activities.select("activity_id")
        .join(from_records, on="activity_id", how="left")
        .join(from_average, on="activity_id", how="left")
    )
    return combined.select(
        "activity_id",
        trimp=pl.coalesce("trimp_records", "trimp_average", pl.lit(0.0)),
        trimp_source=pl.when(pl.col("trimp_records").is_not_null())
        .then(pl.lit("records"))
        .when(pl.col("trimp_average").is_not_null())
        .then(pl.lit("average"))
        .otherwise(pl.lit("none")),
    ).sort("activity_id")


def ewma_load(daily_trimp: pl.Expr, days: int) -> pl.Expr:
    """load_t = load_t-1 + (TRIMP_t - load_t-1) / days, i.e. alpha = 1/days.

    adjust=False gives exactly this recursion; it starts from the first
    value, which is why the daily series begins with a 0 day.
    """
    return daily_trimp.ewm_mean(alpha=1 / days, adjust=False)


def training_load(
    activity_trimp: pl.DataFrame,
    activities: pl.DataFrame,
    sports: list[str] | None = None,
    until: date | None = None,
) -> pl.DataFrame:
    """Daily TRIMP, CTL, ATL and TSB. sports=None means all sports."""
    loads = activity_trimp.join(
        activities.select("activity_id", "sport", date=pl.col("start_local").dt.date()),
        on="activity_id",
    )
    if sports is not None:
        loads = loads.filter(pl.col("sport").is_in(sports))
    trimp_per_day = loads.group_by("date").agg(trimp=pl.col("trimp").sum())

    # Complete calendar: every day from the day before the first activity
    # (load 0) to today, so rest days appear as 0 instead of being skipped.
    first_day = activities["start_local"].min().date() - timedelta(days=1)
    last_day = until or date.today()
    calendar = pl.DataFrame({"date": pl.date_range(first_day, last_day, "1d", eager=True)})

    daily = (
        calendar.join(trimp_per_day, on="date", how="left")
        .sort("date")
        .with_columns(trimp=pl.col("trimp").fill_null(0.0))
        .with_columns(
            ctl=ewma_load(pl.col("trimp"), CTL_DAYS),
            atl=ewma_load(pl.col("trimp"), ATL_DAYS),
        )
    )
    # shift(1): form in the morning = yesterday's CTL minus yesterday's ATL
    return daily.with_columns(tsb=(pl.col("ctl") - pl.col("atl")).shift(1))


def activity_metrics(
    records: pl.DataFrame,
    activities: pl.DataFrame,
    daily: pl.DataFrame,
    hr_max: float,
    sex: str,
) -> pl.DataFrame:
    """activity_metrics.parquet: TRIMP for every activity, EF/decoupling for runs."""
    run_ids = activities.filter(pl.col("sport") == "running").select("activity_id")
    run_records = records.join(run_ids, on="activity_id", how="semi")
    load = trimp(records, activities, daily, hr_max, sex)
    return load.join(running_metrics(run_records), on="activity_id", how="left").sort("activity_id")

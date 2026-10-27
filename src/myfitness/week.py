"""Weekly review (PLAN.md M6): the last weeks up to a reference date.

Weeks run Monday to Sunday. The week containing the reference date is
counted only up to that date.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl

from myfitness.config import PROCESSED


@dataclass(frozen=True)
class Window:
    reference_date: date
    first_day: date  # Monday of the first week shown

    @property
    def days(self) -> pl.Expr:
        return pl.col("date").is_between(self.first_day, self.reference_date)


def window(reference_date: date, weeks: int = 8) -> Window:
    monday_of_reference_week = reference_date - timedelta(days=reference_date.weekday())
    return Window(reference_date, monday_of_reference_week - timedelta(weeks=weeks - 1))


def week_calendar(win: Window) -> pl.DataFrame:
    """One row per week start, so weeks without any activity still appear."""
    return pl.DataFrame(
        {"week": pl.date_range(win.first_day, win.reference_date, "1w", eager=True)}
    )


def with_week(frame: pl.DataFrame, date_column: str) -> pl.DataFrame:
    """Add the Monday of the week. dt.truncate("1w") rounds down to Monday."""
    return frame.with_columns(week=pl.col(date_column).dt.truncate("1w"))


def weekly_volume(win: Window) -> pl.DataFrame:
    """Distance, time and number of activities per week and sport (long format)."""
    activities = pl.read_parquet(PROCESSED / "activities.parquet").with_columns(
        date=pl.col("start_local").dt.date()
    )
    in_window = with_week(activities.filter(win.days), "date")
    volume = in_window.group_by("week", "sport").agg(
        km=pl.col("distance_m").sum() / 1000,
        hours=pl.col("duration_s").sum() / 3600,
        activities=pl.len(),
    )
    # Cross join: every week x every sport of the window, so missing
    # combinations become explicit zeros instead of absent rows.
    sports = in_window.select("sport").unique()
    grid = week_calendar(win).join(sports, how="cross")
    return (
        grid.join(volume, on=["week", "sport"], how="left")
        .with_columns(pl.col("km", "hours", "activities").fill_null(0))
        .sort("week", "sport")
    )


def daily_in_window(win: Window) -> pl.DataFrame:
    return pl.read_parquet(PROCESSED / "daily.parquet").filter(win.days).sort("date")


def load_in_window(win: Window) -> pl.DataFrame:
    return pl.read_parquet(PROCESSED / "training_load.parquet").filter(win.days).sort("date")


RECOVERY_COLUMNS = {
    "sleep_h": pl.col("sleep_duration_s") / 3600,
    "sleep_score": pl.col("sleep_score"),
    "hrv_ms": pl.col("hrv_overnight_avg"),
    "resting_hr": pl.col("resting_hr"),
    "weight_kg": pl.col("weight_kg_ffill"),
}


def recovery_days(win: Window) -> pl.DataFrame:
    """Daily recovery values in readable units (columns of RECOVERY_COLUMNS)."""
    return daily_in_window(win).select("date", **RECOVERY_COLUMNS)


def weekly_recovery(win: Window) -> pl.DataFrame:
    """Weekly means of sleep, HRV and resting HR; weight as the week's last value."""
    daily = with_week(recovery_days(win), "date")
    weekly = daily.group_by("week").agg(
        pl.col("sleep_h", "sleep_score", "hrv_ms", "resting_hr").mean(),
        pl.col("weight_kg").last(),
    )
    return week_calendar(win).join(weekly, on="week", how="left").sort("week")


def weekly_load(win: Window) -> pl.DataFrame:
    """TRIMP sum per week and CTL/ATL/TSB at the end of each week."""
    load = with_week(load_in_window(win), "date")
    return (
        load.group_by("week")
        .agg(
            trimp=pl.col("trimp").sum(),
            ctl_end=pl.col("ctl").last(),
            atl_end=pl.col("atl").last(),
            tsb_end=pl.col("tsb").last(),
        )
        .sort("week")
    )


def summary(win: Window) -> pl.DataFrame:
    """The reference week next to the mean of the four weeks before it."""
    volume = weekly_volume(win).group_by("week").agg(pl.col("km", "hours", "activities").sum())
    table = (
        weekly_recovery(win)
        .join(volume, on="week", how="left")
        .join(weekly_load(win), on="week", how="left")
        .sort("week")
    )
    current_week = table.tail(1)
    previous_four = table.slice(-5, 4)

    metrics = [c for c in table.columns if c != "week"]
    current = current_week.select(metrics).unpivot(variable_name="metric", value_name="this_week")
    before = previous_four.select(pl.col(metrics).mean()).unpivot(
        variable_name="metric", value_name="mean_4_weeks_before"
    )
    return current.join(before, on="metric").with_columns(
        change=pl.col("this_week") - pl.col("mean_4_weeks_before")
    )

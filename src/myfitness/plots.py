"""Plots for the notebooks.

Colours follow one rule per job: a single neutral ink for trend lines and
text, a one-hue light-to-dark ramp for magnitudes (temperature), and one
accent colour for a single series. No second y-axis.
"""

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
import seaborn as sns
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap

INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
ACCENT = "#2a78d6"
SECOND = "#eb6834"  # second categorical slot (orange)
SURFACE = "#ffffff"

# Single-hue orange ramp: darker = warmer. The lightest step still stands
# out against a white background.
TEMPERATURE_CMAP = LinearSegmentedColormap.from_list(
    "temperature", ["#f6c3a6", "#eb6834", "#8f3510"]
)

POINT_SIZE = 42  # area in pt^2, about 8 px diameter


def style_axes(ax: Axes) -> Axes:
    """Recessive frame: no top/right spines, hairline grid on y, muted ticks."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(INK_SECONDARY)
    ax.yaxis.label.set_color(INK_SECONDARY)
    ax.title.set_color(INK)
    return ax


def new_axes(ax: Axes | None, figsize: tuple[float, float] = (10, 4.5)) -> Axes:
    if ax is not None:
        return ax
    _, ax = plt.subplots(figsize=figsize)
    return ax


def ef_trend_table(activity_metrics: pl.DataFrame, activities: pl.DataFrame) -> pl.DataFrame:
    """EF per run with date, temperature, 28-day trend (explore.with_ef_trend)
    and a segment number that breaks the trend line at gaps over 28 days."""
    from myfitness.explore import with_ef_trend

    context = activities.select("activity_id", "start_local", "temp_c", "name", "distance_m")
    runs = activity_metrics.filter(pl.col("ef").is_not_null()).join(context, on="activity_id")

    starts_new_segment = (pl.col("start_local").diff() > pl.duration(days=28)).fill_null(False)
    return (
        with_ef_trend(runs)
        .with_columns(trend_segment=starts_new_segment.cum_sum())
        .collect()
    )


def plot_ef_over_time(trend: pl.DataFrame, ax: Axes | None = None) -> Axes:
    ax = style_axes(new_axes(ax))
    dates = trend["start_local"].to_numpy()

    has_temp = trend["temp_c"].is_not_null().to_numpy()
    points = ax.scatter(
        dates[has_temp],
        trend["ef"].to_numpy()[has_temp],
        c=trend["temp_c"].to_numpy()[has_temp],
        cmap=TEMPERATURE_CMAP,
        s=POINT_SIZE,
        edgecolors=SURFACE,
        linewidths=1,
        zorder=3,
    )
    if (~has_temp).any():
        ax.scatter(
            dates[~has_temp],
            trend["ef"].to_numpy()[~has_temp],
            s=POINT_SIZE,
            facecolors="none",
            edgecolors=MUTED,
            zorder=3,
            label="ohne Temperatur",
        )

    segments = trend.partition_by("trend_segment", maintain_order=True)
    for number, segment in enumerate(segments):
        ax.plot(
            segment["start_local"].to_numpy(),
            segment["ef_28d"].to_numpy(),
            color=INK_SECONDARY,
            linewidth=2,
            zorder=2,
            label="28-Tage-Mittel" if number == 0 else None,
        )
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=INK_SECONDARY)

    colorbar = ax.figure.colorbar(points, ax=ax, pad=0.08)
    colorbar.set_label("Temperatur beim Start (°C)", color=INK_SECONDARY)
    colorbar.outline.set_visible(False)
    colorbar.ax.tick_params(colors=INK_SECONDARY, labelsize=9)

    ax.set_title("Effizienzfaktor je Lauf", loc="left")
    ax.set_ylabel("EF (m/min je Herzschlag)")
    return ax


def plot_ef_vs_temperature(trend: pl.DataFrame, ax: Axes | None = None) -> Axes:
    """Scatter with a linear fit: how strongly does heat lower the EF?"""
    ax = style_axes(new_axes(ax, figsize=(6, 4.5)))
    with_temp = trend.filter(pl.col("temp_c").is_not_null())
    sns.regplot(
        x=with_temp["temp_c"].to_numpy(),
        y=with_temp["ef"].to_numpy(),
        ax=ax,
        color=ACCENT,
        scatter_kws={"s": POINT_SIZE, "edgecolors": SURFACE, "linewidths": 1},
        line_kws={"linewidth": 2},
    )
    ax.set_title("EF und Temperatur", loc="left")
    ax.set_xlabel("Temperatur beim Start (°C)")
    ax.set_ylabel("EF (m/min je Herzschlag)")
    return ax


def plot_decoupling_over_time(
    activity_metrics: pl.DataFrame, activities: pl.DataFrame, ax: Axes | None = None
) -> Axes:
    """Decoupling of the long, even runs. The 5 % line is a common rule of
    thumb for a well-developed aerobic base, not a hard limit."""
    ax = style_axes(new_axes(ax))
    steady = (
        activity_metrics.filter(pl.col("decoupling_pct").is_not_null())
        .join(activities.select("activity_id", "start_local"), on="activity_id")
        .sort("start_local")
    )
    ax.axhline(0, color=MUTED, linewidth=1, zorder=1)
    ax.axhline(5, color=MUTED, linewidth=1, linestyle=(0, (4, 3)), zorder=1)
    ax.annotate(
        "5 % Faustregel",
        xy=(1, 5),
        xycoords=("axes fraction", "data"),
        xytext=(0, 4),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color=INK_SECONDARY,
    )
    ax.scatter(
        steady["start_local"].to_numpy(),
        steady["decoupling_pct"].to_numpy(),
        s=POINT_SIZE * 1.5,
        color=ACCENT,
        edgecolors=SURFACE,
        linewidths=1,
        zorder=3,
    )
    ax.set_title("Aerobe Entkopplung der langen, gleichmäßigen Läufe", loc="left")
    ax.set_ylabel("Entkopplung (%)")
    ax.set_ylim(min(-2, np.floor(steady["decoupling_pct"].min()) - 1), None)
    return ax


# --- correlation toolkit (M4) ------------------------------------------------

# Diverging blue <-> red with a neutral grey midpoint: negative correlations
# blue, positive red, "no correlation" fades into the background.
CORRELATION_CMAP = LinearSegmentedColormap.from_list(
    "correlation", ["#184f95", "#86b6ef", "#f0efec", "#f19a99", "#b32c2b"]
)

LABELS = {
    "pace_min_per_km": "Pace (min/km)",
    "moving_hr": "HF (bpm)",
    "heart_rate": "HF (bpm)",
    "speed_mps": "Geschwindigkeit (m/s)",
    "cadence_spm": "Kadenz (spm)",
    "step_length_mm": "Schrittlänge (mm)",
    "vertical_ratio_pct": "Vert. Verhältnis (%)",
    "vertical_oscillation_mm": "Vert. Oszillation (mm)",
    "stance_time_ms": "Bodenkontakt (ms)",
    "respiration_rate": "Atemfrequenz (/min)",
    "power_w": "Leistung (W)",
    "ef": "EF",
    "ef_vs_trend": "EF − Trend",
    "decoupling_pct": "Entkopplung (%)",
    "temp_c": "Temperatur (°C)",
    "climb_m_per_km": "Anstieg (m/km)",
    "weight_kg": "Gewicht (kg)",
    "sleep_score": "Schlafwert",
    "sleep_duration_s": "Schlafdauer (s)",
    "sleep_deep_s": "Tiefschlaf (s)",
    "sleep_rem_s": "REM-Schlaf (s)",
    "hrv_overnight_avg": "HRV Nacht (ms)",
    "resting_hr": "Ruhepuls (bpm)",
    "avg_stress": "Stress",
    "steps": "Schritte",
    "body_battery_high": "Body Battery max.",
    "body_battery_low": "Body Battery min.",
}


def label(column: str) -> str:
    """Readable axis label; lagged daily columns get 'Vortag'-style suffixes."""
    if "_lag" in column:
        base, lag = column.rsplit("_lag", 1)
        when = {"0": "Nacht vor dem Lauf", "1": "Vortag", "2": "vorletzter Tag"}.get(lag, f"t−{lag}")
        return f"{LABELS.get(base, base)} ({when})"
    return LABELS.get(column, column)


def plot_correlation_heatmap(matrix: pl.DataFrame, title: str, ax: Axes | None = None) -> Axes:
    """Matrix from explore.correlation_matrix(); values printed in each cell."""
    columns = [c for c in matrix.columns if c != "x"]
    values = matrix.select(columns).to_numpy()
    ax = new_axes(ax, figsize=(1 + 0.75 * len(columns), 0.75 * len(columns)))

    image = ax.imshow(values, cmap=CORRELATION_CMAP, vmin=-1, vmax=1)
    ax.set_xticks(range(len(columns)), [label(c) for c in columns], rotation=45, ha="right")
    ax.set_yticks(range(len(columns)), [label(c) for c in matrix["x"]])
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for row in range(values.shape[0]):
        for col in range(values.shape[1]):
            value = values[row, col]
            if np.isnan(value):
                continue
            ink = SURFACE if abs(value) > 0.6 else INK
            ax.text(col, row, f"{value:.2f}", ha="center", va="center", fontsize=8, color=ink)

    colorbar = ax.figure.colorbar(image, ax=ax, shrink=0.8)
    colorbar.outline.set_visible(False)
    colorbar.ax.tick_params(colors=INK_SECONDARY, labelsize=9)
    ax.set_title(title, loc="left", color=INK)
    return ax


def plot_pair(
    frame: pl.DataFrame, x: str, y: str, stats: dict, ax: Axes | None = None
) -> Axes:
    """Scatter with linear fit and the correlation stats in the corner."""
    ax = style_axes(new_axes(ax, figsize=(6, 4.5)))
    pair = frame.select(x, y).drop_nulls()
    many_points = pair.height > 500
    sns.regplot(
        x=pair[x].to_numpy(),
        y=pair[y].to_numpy(),
        ax=ax,
        color=ACCENT,
        scatter_kws={
            "s": 10 if many_points else POINT_SIZE,
            "alpha": 0.3 if many_points else 1,
            "edgecolors": "none" if many_points else SURFACE,
            "linewidths": 0 if many_points else 1,
        },
        line_kws={"linewidth": 2, "color": INK_SECONDARY},
    )
    if stats["pearson"] is not None:
        text = f"r = {stats['pearson']:.2f}   ρ = {stats['spearman']:.2f}   n = {stats['n']}"
    else:
        text = f"zu wenige Werte (n = {stats['n']})"
    ax.text(0.01, 1.02, text, transform=ax.transAxes, fontsize=9, color=INK_SECONDARY)
    ax.set_xlabel(label(x))
    ax.set_ylabel(label(y))
    return ax


def plot_lag_correlations(
    lags: pl.DataFrame, daily_value: str, run_metric: str, ax: Axes | None = None
) -> Axes:
    """Spearman rho per lag from explore.lag_correlations(), n under each bar."""
    ax = style_axes(new_axes(ax, figsize=(5, 3.5)))
    # Each lag keeps its own x position, so panels side by side line up even
    # when a value has no lag 0 (day values start at lag 1).
    ax.bar(lags["lag"].to_numpy(), lags["spearman"].fill_null(0).to_numpy(), width=0.5, color=ACCENT)
    ax.axhline(0, color=MUTED, linewidth=1)
    names = {0: "Nacht davor", 1: "Vortag", 2: "vorletzter Tag"}
    n_per_lag = dict(lags.select("lag", "n").rows())
    tick_labels = [
        f"{names[lag]}\nn = {n_per_lag[lag]}" if lag in n_per_lag else f"{names[lag]}\n–"
        for lag in names
    ]
    ax.set_xticks(list(names), tick_labels)
    ax.set_xlim(-0.5, len(names) - 0.5)
    ax.set_ylim(-1, 1)
    ax.set_ylabel("Spearman ρ")
    ax.set_title(f"{LABELS.get(daily_value, daily_value)} → {label(run_metric)}", loc="left", fontsize=11)
    return ax


def plot_within_run_distribution(per_run: pl.DataFrame, x: str, y: str, ax: Axes | None = None) -> Axes:
    """Histogram of the per-run correlations from explore.within_run_correlations()."""
    ax = style_axes(new_axes(ax, figsize=(6, 3.5)))
    values = per_run["spearman"].drop_nulls().to_numpy()
    ax.hist(values, bins=np.linspace(-1, 1, 21), color=ACCENT, edgecolor=SURFACE, linewidth=2)
    ax.axvline(0, color=MUTED, linewidth=1)
    median = float(np.median(values))
    ax.axvline(median, color=INK_SECONDARY, linewidth=2)
    ax.annotate(
        f"Median ρ = {median:.2f}",
        xy=(median, 1),
        xycoords=("data", "axes fraction"),
        xytext=(-4, -12),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color=INK_SECONDARY,
    )
    ax.set_xlim(-1, 1)
    ax.set_xlabel("Spearman ρ innerhalb eines Laufs")
    ax.set_ylabel("Anzahl Läufe")
    ax.set_title(f"{label(x)} ↔ {label(y)}: {len(values)} Läufe", loc="left", fontsize=11)
    return ax


# --- training load (M5) -----------------------------------------------------------


def plot_training_load(load: pl.DataFrame, title: str = "Belastung") -> plt.Figure:
    """Three stacked panels with a shared time axis instead of a second y-axis:
    daily TRIMP, CTL/ATL, TSB."""
    fig, (ax_trimp, ax_load, ax_tsb) = plt.subplots(
        3, 1, figsize=(11, 8), sharex=True, gridspec_kw={"height_ratios": [1, 2, 1.3]}
    )
    dates = load["date"].to_numpy()

    style_axes(ax_trimp)
    ax_trimp.bar(dates, load["trimp"].to_numpy(), width=1.0, color=MUTED)
    ax_trimp.set_ylabel("TRIMP / Tag")
    ax_trimp.set_title(title, loc="left")

    style_axes(ax_load)
    for column, color, name in [("ctl", ACCENT, "CTL (Fitness, 42 d)"), ("atl", SECOND, "ATL (Ermüdung, 7 d)")]:
        values = load[column].to_numpy()
        ax_load.plot(dates, values, color=color, linewidth=2, label=name)
        ax_load.annotate(
            column.upper(),
            xy=(dates[-1], values[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=INK_SECONDARY,
        )
    ax_load.legend(
        frameon=False, loc="lower left", bbox_to_anchor=(0, 1), ncol=2, fontsize=9, labelcolor=INK_SECONDARY
    )
    ax_load.set_ylabel("Belastung")

    style_axes(ax_tsb)
    tsb = load["tsb"].to_numpy()
    ax_tsb.axhline(0, color=MUTED, linewidth=1)
    ax_tsb.plot(dates, tsb, color=INK_SECONDARY, linewidth=2)
    ax_tsb.fill_between(dates, tsb, 0, where=tsb < 0, color=SECOND, alpha=0.25, linewidth=0)
    ax_tsb.fill_between(dates, tsb, 0, where=tsb >= 0, color=ACCENT, alpha=0.25, linewidth=0)
    ax_tsb.set_ylabel("TSB (Form)")
    ax_tsb.annotate("frisch", xy=(0.005, 0.92), xycoords="axes fraction", fontsize=9, color=INK_SECONDARY, va="top")
    ax_tsb.annotate("ermüdet", xy=(0.005, 0.06), xycoords="axes fraction", fontsize=9, color=INK_SECONDARY)

    fig.tight_layout()
    return fig


# --- weekly review (M6) ---------------------------------------------------------

# Fixed colour per sport (categorical slots in order), so a sport keeps its
# colour no matter which sports appear in a given window.
SPORT_COLORS = {
    "running": "#2a78d6",
    "walking": "#eb6834",
    "cycling": "#1baf7a",
    "training": "#eda100",
    "meditation": "#e87ba4",
}
SPORT_NAMES = {
    "running": "Laufen",
    "walking": "Gehen",
    "cycling": "Rad",
    "training": "Training",
    "meditation": "Meditation",
}


def plot_weekly_volume(volume: pl.DataFrame) -> plt.Figure:
    """Hours and km per week, stacked by sport (from week.weekly_volume)."""
    fig, (ax_hours, ax_km) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    weeks = volume["week"].unique().sort()
    positions = np.arange(weeks.len())
    sports = [s for s in SPORT_COLORS if s in volume["sport"].unique()] + sorted(
        s for s in volume["sport"].unique() if s not in SPORT_COLORS
    )

    for ax, column, ylabel in [(ax_hours, "hours", "Stunden"), (ax_km, "km", "km")]:
        style_axes(ax)
        bottom = np.zeros(weeks.len())
        for sport in sports:
            values = (
                volume.filter(pl.col("sport") == sport)
                .sort("week")[column]
                .to_numpy()
            )
            ax.bar(
                positions,
                values,
                bottom=bottom,
                width=0.6,
                color=SPORT_COLORS.get(sport, MUTED),
                edgecolor=SURFACE,
                linewidth=1,
                label=SPORT_NAMES.get(sport, sport),
            )
            bottom += values
        ax.set_ylabel(ylabel)

    ax_hours.set_title("Wochenumfang je Sportart", loc="left", pad=22)
    ax_hours.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(sports), fontsize=9)
    ax_km.set_xticks(positions, [d.strftime("KW %V\n%d.%m.") for d in weeks.to_list()])
    fig.tight_layout()
    return fig


RECOVERY_PANELS = [
    ("sleep_h", "Schlaf (h)"),
    ("sleep_score", "Schlafwert"),
    ("hrv_ms", "HRV Nacht (ms)"),
    ("resting_hr", "Ruhepuls (bpm)"),
    ("weight_kg", "Gewicht (kg, fortgeschrieben)"),
]


def plot_recovery(daily: pl.DataFrame, weekly: pl.DataFrame) -> plt.Figure:
    """Small multiples: daily values as points, weekly means as a line.

    daily needs the columns of week.RECOVERY_COLUMNS (see week.recovery_days).
    """
    fig, axes = plt.subplots(1, len(RECOVERY_PANELS), figsize=(18, 3.4), sharex=True)
    for ax, (column, title) in zip(axes, RECOVERY_PANELS):
        style_axes(ax)
        ax.scatter(daily["date"].to_numpy(), daily[column].to_numpy(), s=12, color=GRID, edgecolors=MUTED, linewidths=0.5)
        # weekly mean drawn in the middle of its week (Thursday)
        week_middle = weekly["week"].dt.offset_by("3d").to_numpy()
        ax.plot(week_middle, weekly[column].to_numpy(), color=ACCENT, linewidth=2, marker="o", markersize=4)
        ax.set_title(title, loc="left", fontsize=10)
        ax.tick_params(axis="x", labelrotation=45)
    fig.tight_layout()
    return fig

"""Paths and personal parameters.

The data directory defaults to ./data in the project root and can be moved
with the environment variable MYFITNESS_DATA_DIR. Personal parameters come
from config.toml (gitignored); config.example.toml is the template.
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config.toml"

DATA_DIR = Path(os.environ.get("MYFITNESS_DATA_DIR", PROJECT_ROOT / "data")).expanduser()
RAW_GARMIN = DATA_DIR / "raw" / "garmin"
RAW_ACTIVITIES = RAW_GARMIN / "activities"
RAW_FIT = RAW_GARMIN / "fit"
RAW_DAILY = RAW_GARMIN / "daily"
RAW_HR_ZONES = RAW_GARMIN / "heart_rate_zones"
RAW_WEATHER = DATA_DIR / "raw" / "weather"
PROCESSED = DATA_DIR / "processed"

# Maximum number of days per call for each daily endpoint (PLAN.md 1.3).
# The keys are the method names of GarminPersonalApiClient. The limits were
# measured externally and may change; a 400 response hints at a lower limit.
DAILY_WINDOW_DAYS: dict[str, int] = {
    "get_daily_summaries": 180,
    "get_daily_hrv_summaries": 180,
    "get_daily_sleep_summaries": 28,
    "get_daily_body_battery": 28,
    "get_daily_stress": 7,
    "get_daily_steps": 7,
    "get_weight_measurements": 28,
}


@dataclass(frozen=True)
class Settings:
    hr_max: int | None = None
    sex: str | None = None  # "male" or "female", selects the TRIMP constants
    request_pause_s: float = 1.0
    max_retries: int = 3
    initial_days: int = 400
    refetch_days: int = 3


def load_settings(path: Path = CONFIG_FILE) -> Settings:
    """Read config.toml; missing file or keys fall back to the defaults."""
    if not path.exists():
        return Settings()
    with path.open("rb") as f:
        values = tomllib.load(f)

    athlete = values.get("athlete", {})
    ingest = values.get("ingest", {})
    defaults = Settings()
    return Settings(
        hr_max=athlete.get("hr_max", defaults.hr_max),
        sex=athlete.get("sex", defaults.sex),
        request_pause_s=ingest.get("request_pause_s", defaults.request_pause_s),
        max_retries=ingest.get("max_retries", defaults.max_retries),
        initial_days=ingest.get("initial_days", defaults.initial_days),
        refetch_days=ingest.get("refetch_days", defaults.refetch_days),
    )

"""hr_zones.parquet: the heart rate zones currently set in Garmin Connect.

Built from the newest snapshot in raw/garmin/heart_rate_zones/. Zone k
covers [floor_k, floor_k+1); zone 5 is open at the top.
"""

import json

import polars as pl

from myfitness.config import RAW_HR_ZONES

ZONE_COUNT = 5


def build_hr_zones() -> pl.DataFrame:
    snapshots = sorted(RAW_HR_ZONES.glob("*.json"))
    if not snapshots:
        return pl.DataFrame(
            schema={"zone": pl.Int32, "floor_bpm": pl.Float64, "ceiling_bpm": pl.Float64}
        )

    # The API returns one entry per sport; "DEFAULT" applies to all sports
    # without their own zones.
    entries = json.loads(snapshots[-1].read_text())
    default = next(e for e in entries if e.get("sport") == "DEFAULT")

    floors = [default[f"zone{k}Floor"] for k in range(1, ZONE_COUNT + 1)]
    zones = pl.DataFrame(
        {"zone": list(range(1, ZONE_COUNT + 1)), "floor_bpm": floors},
        schema={"zone": pl.Int32, "floor_bpm": pl.Float64},
    )
    # The ceiling of each zone is the floor of the next one (shift(-1)
    # looks one row ahead); zone 5 has no ceiling.
    return zones.with_columns(
        ceiling_bpm=pl.col("floor_bpm").shift(-1),
        snapshot_date=pl.lit(snapshots[-1].stem).str.to_date(),
        max_hr_used=pl.lit(default.get("maxHeartRateUsed"), dtype=pl.Float64),
    )

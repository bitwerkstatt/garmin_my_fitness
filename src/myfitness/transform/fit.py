"""Decode FIT files from the raw ZIPs.

Decoding, unit conversions shared by records and laps, and the field
inventory (PLAN.md 1.7). Findings that shape the conversions are in
PLAN.md section 10.
"""

import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import polars as pl
from garmin_fit_sdk import Decoder, Stream

INVENTORY_MESSAGES = ("record_mesgs", "lap_mesgs", "session_mesgs")

# Sports whose FIT cadence counts strides of one leg (verified for running
# and walking in 00_datencheck). Cadence of other sports is not converted.
FOOT_SPORTS = ("running", "walking", "hiking")

SEMICIRCLES_TO_DEGREES = 180 / 2**31


def semicircles_to_degrees(column: str) -> pl.Expr:
    """FIT stores coordinates as semicircles; the SDK does not convert them."""
    return pl.col(column) * SEMICIRCLES_TO_DEGREES


def steps_per_minute(cadence: str, fractional: str, sport: str) -> pl.Expr:
    """Steps per minute = 2 x (cadence + fractional_cadence) for foot sports, else null.

    A missing fractional part counts as 0.
    """
    if sport not in FOOT_SPORTS:
        return pl.lit(None, dtype=pl.Float64)
    return 2 * (pl.col(cadence) + pl.col(fractional).fill_null(0))


def with_missing_columns(frame: pl.DataFrame, columns: Iterable[str]) -> pl.DataFrame:
    """Add missing columns as null, so every file yields the same columns.

    Not every activity has every field (cycling has no step_length, ...).
    """
    missing = [pl.lit(None, dtype=pl.Float64).alias(c) for c in columns if c not in frame.columns]
    return frame.with_columns(missing)


def read_fit_bytes(zip_path: Path) -> bytes:
    """Return the single .fit file inside a raw activity ZIP."""
    with zipfile.ZipFile(zip_path) as archive:
        fit_names = [name for name in archive.namelist() if name.lower().endswith(".fit")]
        if len(fit_names) != 1:
            raise ValueError(f"{zip_path.name}: expected one .fit file, found {fit_names}")
        return archive.read(fit_names[0])


def decode_fit_zip(zip_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Decode a raw ZIP into {message_name: [message, ...]}.

    The SDK applies scale and offset and turns enums into strings
    (e.g. sport = "running"). Field names of unknown fields are numbers.
    """
    stream = Stream.from_byte_array(bytearray(read_fit_bytes(zip_path)))
    messages, errors = Decoder(stream).read()
    if errors:
        raise ValueError(f"{zip_path.name}: {errors}")
    return messages


def sport_of(messages: dict[str, list[dict[str, Any]]]) -> str | None:
    sessions = messages.get("session_mesgs", [])
    return sessions[0].get("sport") if sessions else None


def to_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """Messages -> DataFrame. Field names become strings, developer fields are dropped.

    Different messages can carry different fields; scanning all rows
    (infer_schema_length=None) gives every field its own column.
    """
    if not rows:
        return pl.DataFrame()
    cleaned = [
        {str(key): value for key, value in row.items() if key != "developer_fields"} for row in rows
    ]
    return pl.from_dicts(cleaned, infer_schema_length=None, strict=False)


def file_fill_counts(messages: dict[str, list[dict[str, Any]]], message_name: str) -> pl.DataFrame:
    """For one file: number of rows and number of filled values per field."""
    frame = to_frame(messages.get(message_name, []))
    if frame.height == 0:
        return pl.DataFrame(schema={"field": pl.String, "filled": pl.UInt32, "rows": pl.UInt32})

    # null_count() returns one row with the nulls of every column;
    # unpivot turns that wide row into a long table with one row per field.
    nulls_per_field = frame.null_count().unpivot(variable_name="field", value_name="nulls")
    rows_in_file = frame.height
    return nulls_per_field.select(
        pl.col("field"),
        filled=(rows_in_file - pl.col("nulls")).cast(pl.UInt32),
        rows=pl.lit(rows_in_file, dtype=pl.UInt32),
    )


def field_inventory(zip_paths: Iterable[Path], sport: str = "running") -> pl.DataFrame:
    """Share of filled values per message and field over all files of one sport.

    filled_share: filled values / all rows of that message type (also counting
                  rows of files where the field does not occur at all)
    files_share:  share of files in which the field has at least one value
    """
    per_file_counts = []
    file_count = 0
    for zip_path in zip_paths:
        messages = decode_fit_zip(zip_path)
        if sport_of(messages) != sport:
            continue
        file_count += 1
        for message_name in INVENTORY_MESSAGES:
            counts = file_fill_counts(messages, message_name)
            per_file_counts.append(
                counts.with_columns(message=pl.lit(message_name), file=pl.lit(zip_path.stem))
            )

    if file_count == 0:
        raise ValueError(f"no FIT files with sport={sport!r}")
    counts = pl.concat(per_file_counts)

    # Total rows per message type, over all files. The denominator must also
    # include files in which a field is missing completely.
    rows_per_file = counts.unique(["message", "file"]).select("message", "file", "rows")
    total_rows = rows_per_file.group_by("message").agg(total_rows=pl.col("rows").sum())

    inventory = (
        counts.group_by("message", "field")
        .agg(
            filled=pl.col("filled").sum(),
            files_with_values=(pl.col("filled") > 0).sum(),
        )
        .join(total_rows, on="message")
        .with_columns(
            filled_share=pl.col("filled") / pl.col("total_rows"),
            files_share=pl.col("files_with_values") / file_count,
        )
        .sort("message", "filled_share", descending=[False, True])
    )
    return inventory.select("message", "field", "filled_share", "files_share", "filled", "total_rows")

"""Single-pass ArduPilot DataFlash log parsing."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
from pymavlink import mavutil

from .coordinates import latlon_to_xy


class LogFormatError(ValueError):
    """Raised when a flight log does not contain the expected data."""


def _message_row(message: Any, ref_lat: float, ref_lon: float) -> dict[str, Any]:
    time_us = getattr(message, "TimeUS", None)
    if time_us is None:
        raise LogFormatError(f"{message.get_type()} message is missing TimeUS")

    row: dict[str, Any] = {"Time": time_us / 1_000_000}
    for field in getattr(message, "_fieldnames", ()):  # pymavlink's public data surface
        if field != "TimeUS":
            row[field] = getattr(message, field, None)

    if message.get_type() in {"GPS", "POS"}:
        lat = getattr(message, "Lat", None)
        lon = getattr(message, "Lng", None)
        if lat is not None and lon is not None:
            row["X"], row["Y"] = latlon_to_xy(lat, lon, ref_lat, ref_lon)
    return row


def _to_dataframes(rows_by_type: dict[str, list[dict[str, Any]]]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for message_type, rows in rows_by_type.items():
        frame = pd.DataFrame(rows)
        if not frame.empty:
            ordered_columns = ["Time", *sorted(column for column in frame if column != "Time")]
            frame = (
                frame.reindex(columns=ordered_columns)
                .sort_values("Time")
                .reset_index(drop=True)
            )
        frames[message_type] = frame

    gps = frames.get("GPS")
    if gps is not None and not gps.empty and {"Spd", "VZ"}.issubset(gps.columns):
        gps["Spd_3D"] = (gps["Spd"].pow(2) + gps["VZ"].pow(2)).pow(0.5)
    return frames


def parse_raw_log(
    path: str | Path,
    ref_lat: float,
    ref_lon: float,
    message_types: Iterable[str] = ("GPS", "ATT", "POS"),
) -> dict[str, pd.DataFrame]:
    """Parse selected message types from a DataFlash log in one pass.

    ``pymavlink`` is expected to expose ``Lat`` and ``Lng`` in decimal degrees.
    Raw flight-log files remain the caller's responsibility and are ignored by
    this repository's Git configuration.
    """
    log_path = Path(path)
    if not log_path.is_file():
        raise FileNotFoundError(f"flight log not found: {log_path}")

    selected_types = tuple(dict.fromkeys(item.upper() for item in message_types))
    if not selected_types:
        raise ValueError("at least one message type is required")

    rows_by_type: dict[str, list[dict[str, Any]]] = {
        message_type: [] for message_type in selected_types
    }
    try:
        log = mavutil.mavlink_connection(str(log_path))
    except (OSError, ValueError) as error:
        raise LogFormatError(f"could not open flight log {log_path}: {error}") from error

    try:
        while True:
            try:
                message = log.recv_match(type=list(selected_types), blocking=False)
            except (EOFError, OSError, ValueError) as error:
                raise LogFormatError(f"could not read flight log {log_path}: {error}") from error
            if message is None:
                break

            message_type = message.get_type()
            if message_type in rows_by_type:
                rows_by_type[message_type].append(_message_row(message, ref_lat, ref_lon))
    finally:
        close = getattr(log, "close", None)
        if callable(close):
            close()

    return _to_dataframes(rows_by_type)

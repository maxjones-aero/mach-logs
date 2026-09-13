"""Frame-rate-aligned telemetry interpolation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def _require_columns(frame: pd.DataFrame, name: str, columns: set[str]) -> None:
    if frame is None or frame.empty:
        raise ValueError(f"the log contains no {name} data")
    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"{name} data is missing required fields: {', '.join(sorted(missing))}")


@dataclass(frozen=True)
class TelemetryTimeline:
    """Telemetry sampled once for every output video frame."""

    start_time: float
    finish_time: float
    fps: int
    time: np.ndarray
    x: np.ndarray
    y: np.ndarray
    speed_metres_per_second: np.ndarray
    altitude_metres: np.ndarray
    roll_degrees: np.ndarray
    pitch_degrees: np.ndarray
    heading_radians: np.ndarray

    @property
    def frame_count(self) -> int:
        return len(self.time)

    @property
    def duration_seconds(self) -> float:
        return (self.frame_count - 1) / self.fps

    @classmethod
    def from_frames(
        cls,
        gps: pd.DataFrame,
        attitude: pd.DataFrame,
        *,
        fps: int,
        start_time: float | None = None,
        finish_time: float | None = None,
    ) -> TelemetryTimeline:
        """Build a frame-aligned timeline over the GPS/attitude overlap."""
        _require_columns(gps, "GPS", {"Time", "X", "Y", "Alt", "Spd_3D"})
        _require_columns(attitude, "ATT", {"Time", "Roll", "Pitch"})
        if fps <= 0:
            raise ValueError("fps must be greater than zero")

        gps = gps.sort_values("Time")
        attitude = attitude.sort_values("Time")
        available_start = max(float(gps["Time"].min()), float(attitude["Time"].min()))
        available_finish = min(float(gps["Time"].max()), float(attitude["Time"].max()))
        start = available_start if start_time is None else start_time
        finish = available_finish if finish_time is None else finish_time
        if not np.isfinite(start) or not np.isfinite(finish) or start >= finish:
            raise ValueError("start time must be a finite value earlier than finish time")
        if start < available_start or finish > available_finish:
            raise ValueError(
                f"requested range {start:g}-{finish:g}s is outside the shared data range "
                f"{available_start:g}-{available_finish:g}s"
            )

        frame_count = int(np.floor((finish - start) * fps)) + 1
        frame_times = start + np.arange(frame_count) / fps

        def interpolate(frame: pd.DataFrame, column: str) -> np.ndarray:
            return np.interp(frame_times, frame["Time"], frame[column])

        x_values = interpolate(gps, "X")
        y_values = interpolate(gps, "Y")
        delta_x = np.gradient(x_values)
        delta_y = np.gradient(y_values)
        heading = np.unwrap(np.arctan2(delta_y, delta_x))

        return cls(
            start_time=start,
            finish_time=float(frame_times[-1]),
            fps=fps,
            time=frame_times,
            x=x_values,
            y=y_values,
            speed_metres_per_second=interpolate(gps, "Spd_3D"),
            altitude_metres=interpolate(gps, "Alt"),
            roll_degrees=interpolate(attitude, "Roll"),
            pitch_degrees=interpolate(attitude, "Pitch"),
            heading_radians=heading,
        )

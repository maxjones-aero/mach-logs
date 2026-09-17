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
class FuelModel:
    """Assumptions used to estimate fuel consumption from throttle output."""

    idle_litres_per_minute: float = 0.179
    full_litres_per_minute: float = 0.98
    total_consumed_litres: float = 0.95
    final_remaining_litres: float = 1.2
    prelaunch_seconds: float = 10.0
    launch_speed_metres_per_second: float = 10.0

    def __post_init__(self) -> None:
        if self.idle_litres_per_minute < 0:
            raise ValueError("idle fuel burn cannot be negative")
        if self.full_litres_per_minute <= self.idle_litres_per_minute:
            raise ValueError("full-throttle fuel burn must exceed idle fuel burn")
        if self.total_consumed_litres <= 0 or self.final_remaining_litres < 0:
            raise ValueError("fuel quantities must be positive")
        if self.prelaunch_seconds < 0 or self.launch_speed_metres_per_second <= 0:
            raise ValueError("fuel timing values are invalid")


def _parameter_value(parameters: pd.DataFrame, name: str) -> float:
    matches = parameters.loc[parameters["Name"].eq(name), "Value"]
    if matches.empty:
        raise ValueError(f"flight parameters are missing {name}")
    return float(matches.iloc[-1])


def _throttle_channel(parameters: pd.DataFrame) -> int:
    functions = parameters.loc[
        parameters["Name"].str.match(r"SERVO\d+_FUNCTION", na=False)
        & parameters["Value"].round().eq(70)
    ]
    if functions.empty:
        raise ValueError("flight parameters do not identify a throttle servo (function 70)")
    name = str(functions.iloc[0]["Name"])
    return int(name.removeprefix("SERVO").removesuffix("_FUNCTION"))


def _fuel_use(
    gps: pd.DataFrame,
    servo_outputs: pd.DataFrame,
    parameters: pd.DataFrame,
    frame_times: np.ndarray,
    model: FuelModel,
) -> tuple[np.ndarray, np.ndarray, float, float, int]:
    """Return cumulative fuel use, its model window, and the throttle channel."""
    channel = _throttle_channel(parameters)
    column = f"C{channel}"
    _require_columns(servo_outputs, "RCOU", {"Time", column})
    servo_min = _parameter_value(parameters, f"SERVO{channel}_MIN")
    servo_max = _parameter_value(parameters, f"SERVO{channel}_MAX")
    if servo_min >= servo_max:
        raise ValueError("throttle servo minimum must be lower than its maximum")

    launch_samples = gps.loc[
        gps["Spd_3D"].gt(model.launch_speed_metres_per_second), "Time"
    ]
    if launch_samples.empty:
        raise ValueError("could not detect launch from GPS speed")
    launch_time = float(launch_samples.iloc[0])
    model_start = max(
        float(servo_outputs["Time"].min()), launch_time - model.prelaunch_seconds
    )

    output = servo_outputs.sort_values("Time")
    throttle = np.clip((output[column].to_numpy() - servo_min) / (servo_max - servo_min), 0, 1)
    running = throttle > 0.025
    if not running.any():
        raise ValueError("throttle output never rises above idle")
    model_stop = float(output.loc[running, "Time"].iloc[-1])
    if model_start >= model_stop:
        raise ValueError("fuel-consumption window is empty")

    output_time = output["Time"].to_numpy()
    interior = output_time[(output_time > model_start) & (output_time < model_stop)]
    model_time = np.unique(np.concatenate(([model_start], interior, [model_stop])))
    model_throttle = np.interp(model_time, output_time, throttle)
    burn_rate = model.idle_litres_per_minute + (
        model.full_litres_per_minute - model.idle_litres_per_minute
    ) * model_throttle
    increments = (burn_rate[:-1] + burn_rate[1:]) * 0.5 * np.diff(model_time) / 60.0
    raw_cumulative = np.concatenate(([0.0], np.cumsum(increments)))
    if raw_cumulative[-1] <= 0:
        raise ValueError("fuel-consumption model produced no fuel use")
    cumulative = raw_cumulative * (model.total_consumed_litres / raw_cumulative[-1])
    frame_use = np.interp(
        frame_times,
        model_time,
        cumulative,
        left=0.0,
        right=model.total_consumed_litres,
    )
    frame_throttle = np.interp(frame_times, output_time, throttle) * 100.0
    return frame_use, frame_throttle, model_start, model_stop, channel


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
    battery_percent: np.ndarray
    battery_cell_count: int
    fuel_used_litres: np.ndarray
    fuel_total_litres: float
    fuel_remaining_litres: np.ndarray
    fuel_initial_litres: float
    fuel_final_litres: float
    fuel_model_start_time: float
    fuel_model_stop_time: float
    throttle_channel: int
    throttle_percent: np.ndarray
    lateral_g: np.ndarray
    axial_g: np.ndarray
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
        imu: pd.DataFrame,
        battery: pd.DataFrame,
        servo_outputs: pd.DataFrame,
        parameters: pd.DataFrame,
        *,
        fps: int,
        start_time: float | None = None,
        finish_time: float | None = None,
        fuel_model: FuelModel | None = None,
    ) -> TelemetryTimeline:
        """Build a frame-aligned timeline over the GPS/attitude overlap."""
        _require_columns(gps, "GPS", {"Time", "X", "Y", "Alt", "Spd_3D", "VZ"})
        _require_columns(attitude, "ATT", {"Time", "Roll", "Pitch"})
        _require_columns(imu, "IMU", {"Time", "AccX", "AccY", "AccZ"})
        _require_columns(battery, "BAT", {"Time", "Volt", "RemPct"})
        _require_columns(servo_outputs, "RCOU", {"Time"})
        _require_columns(parameters, "PARM", {"Name", "Value"})
        if fps <= 0:
            raise ValueError("fps must be greater than zero")

        gps = gps.sort_values("Time")
        attitude = attitude.sort_values("Time")
        imu = imu.sort_values("Time")
        battery = battery.sort_values("Time")
        available_start = max(float(gps["Time"].min()), float(attitude["Time"].min()))
        available_start = max(
            available_start,
            float(imu["Time"].min()),
            float(battery["Time"].min()),
            float(servo_outputs["Time"].min()),
        )
        available_finish = min(
            float(gps["Time"].max()),
            float(attitude["Time"].max()),
            float(imu["Time"].max()),
            float(battery["Time"].max()),
            float(servo_outputs["Time"].max()),
        )
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
        fuel_model = fuel_model or FuelModel()

        def interpolate(frame: pd.DataFrame, column: str) -> np.ndarray:
            return np.interp(frame_times, frame["Time"], frame[column])

        x_values = interpolate(gps, "X")
        y_values = interpolate(gps, "Y")
        delta_x = np.gradient(x_values)
        delta_y = np.gradient(y_values)
        lateral_g = (imu["AccY"].pow(2) + imu["AccZ"].pow(2)).pow(0.5) / 9.80665
        axial_g = imu["AccX"] / 9.80665
        roll_values = np.rad2deg(np.unwrap(np.deg2rad(attitude["Roll"].to_numpy())))
        fuel_use, throttle_percent, fuel_start, fuel_stop, throttle_channel = _fuel_use(
            gps, servo_outputs, parameters, frame_times, fuel_model
        )
        peak_voltage = float(battery["Volt"].quantile(0.99))
        battery_cell_count = max(1, round(peak_voltage / 4.2))
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
            battery_percent=np.clip(interpolate(battery, "RemPct"), 0, 100),
            battery_cell_count=battery_cell_count,
            fuel_used_litres=fuel_use,
            fuel_total_litres=fuel_model.total_consumed_litres,
            fuel_remaining_litres=(
                fuel_model.final_remaining_litres
                + fuel_model.total_consumed_litres
                - fuel_use
            ),
            fuel_initial_litres=(
                fuel_model.final_remaining_litres + fuel_model.total_consumed_litres
            ),
            fuel_final_litres=fuel_model.final_remaining_litres,
            fuel_model_start_time=fuel_start,
            fuel_model_stop_time=fuel_stop,
            throttle_channel=throttle_channel,
            throttle_percent=np.clip(throttle_percent, 0, 100),
            lateral_g=np.interp(frame_times, imu["Time"], lateral_g),
            axial_g=np.interp(frame_times, imu["Time"], axial_g),
            roll_degrees=np.interp(frame_times, attitude["Time"], roll_values),
            pitch_degrees=interpolate(attitude, "Pitch"),
            heading_radians=heading,
        )

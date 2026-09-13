"""Flight-path plots and animations."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib as mpl
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.animation import FFMpegWriter, FuncAnimation, writers
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.transforms import Affine2D

LOGGER = logging.getLogger(__name__)
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

ORIGINAL_GREYS = mpl.colormaps["Greys"]
HALF_GREYS = LinearSegmentedColormap.from_list(
    "half_greys",
    ORIGINAL_GREYS(np.linspace(0.5, 0, 512)),
)

mpl.rcParams["font.family"] = "monospace"
mpl.rcParams["font.weight"] = "bold"


def _require_columns(frame: pd.DataFrame, name: str, columns: set[str]) -> None:
    if frame is None or frame.empty:
        raise ValueError(f"the log contains no {name} data")
    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"{name} data is missing required fields: {', '.join(sorted(missing))}")


def _time_slice(frame: pd.DataFrame, start_time: float, finish_time: float) -> pd.DataFrame:
    sliced = frame[(frame["Time"] >= start_time) & (frame["Time"] <= finish_time)].copy()
    return sliced.sort_values("Time")


def _resolve_time_window(
    first: pd.DataFrame,
    second: pd.DataFrame,
    start_time: float | None,
    finish_time: float | None,
) -> tuple[float, float]:
    available_start = max(float(first["Time"].min()), float(second["Time"].min()))
    available_finish = min(float(first["Time"].max()), float(second["Time"].max()))
    start = available_start if start_time is None else start_time
    finish = available_finish if finish_time is None else finish_time
    if not np.isfinite(start) or not np.isfinite(finish) or start >= finish:
        raise ValueError("start time must be a finite value earlier than finish time")
    if start < available_start or finish > available_finish:
        raise ValueError(
            f"requested range {start:g}-{finish:g}s is outside the shared data range "
            f"{available_start:g}-{available_finish:g}s"
        )
    return start, finish


def plot_flight_data(
    gps: pd.DataFrame,
    position: pd.DataFrame,
    *,
    start_time: float | None = None,
    finish_time: float | None = None,
    save_path: str | Path | None = None,
) -> Path | None:
    """Show or save a four-panel summary of position, speed, and altitude."""
    _require_columns(gps, "GPS", {"Time", "X", "Y", "Alt", "Spd", "VZ", "Spd_3D"})
    _require_columns(position, "POS", {"Time", "X", "Y", "Alt"})

    start, finish = _resolve_time_window(gps, position, start_time, finish_time)

    gps_view = _time_slice(gps, start, finish)
    position_view = _time_slice(position, start, finish)
    if gps_view.empty or position_view.empty:
        raise ValueError("the selected time range contains no GPS or POS data")

    figure, axes = plt.subplots(2, 2, sharex=True, figsize=(10, 6))

    axes[0, 0].plot(position_view["Time"], position_view["X"], label="POS X")
    axes[0, 0].plot(gps_view["Time"], gps_view["X"], label="GPS X")
    axes[0, 0].set_ylabel("X (m)")

    axes[1, 0].plot(position_view["Time"], position_view["Y"], label="POS Y")
    axes[1, 0].plot(gps_view["Time"], gps_view["Y"], label="GPS Y")
    axes[1, 0].set_ylabel("Y (m)")

    axes[0, 1].plot(gps_view["Time"], gps_view["Spd_3D"], label="3D speed")
    axes[0, 1].plot(gps_view["Time"], gps_view["Spd"], label="Horizontal speed")
    axes[0, 1].plot(gps_view["Time"], gps_view["VZ"], label="Vertical speed")
    axes[0, 1].set_ylabel("Speed (m/s)")

    axes[1, 1].plot(position_view["Time"], position_view["Alt"], label="POS altitude")
    axes[1, 1].plot(gps_view["Time"], gps_view["Alt"], label="GPS altitude")
    axes[1, 1].set_ylabel("Altitude (m)")

    for axis in axes.flat:
        axis.set_xlabel("Time (s)")
        axis.legend()
        axis.grid(True)
    figure.tight_layout()

    if save_path is None:
        plt.show()
        return None

    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    LOGGER.info("Plot saved to %s", output_path)
    return output_path


def animate_flight_path(
    gps: pd.DataFrame,
    attitude: pd.DataFrame,
    *,
    start_time: float | None = None,
    finish_time: float | None = None,
    fps: int = 30,
    save_path: str | Path | None = None,
    sleek: bool = False,
) -> Path | None:
    """Show or save an animated flight path with attitude instruments."""
    _require_columns(gps, "GPS", {"Time", "X", "Y", "Alt", "Spd_3D"})
    _require_columns(attitude, "ATT", {"Time", "Roll", "Pitch"})
    if fps <= 0:
        raise ValueError("fps must be greater than zero")

    start, finish = _resolve_time_window(gps, attitude, start_time, finish_time)
    gps_view = _time_slice(gps, start, finish)
    if len(gps_view) < 2:
        raise ValueError("the selected time range must contain at least two GPS samples")

    attitude = attitude.sort_values("Time")
    timestep = 1.0 / fps
    timeline = np.arange(start, finish + timestep, timestep)
    x_values = np.interp(timeline, gps_view["Time"], gps_view["X"])
    y_values = np.interp(timeline, gps_view["Time"], gps_view["Y"])
    speed_values = np.interp(timeline, gps_view["Time"], gps_view["Spd_3D"]) * 2.236936
    altitude_values = np.interp(timeline, gps_view["Time"], gps_view["Alt"])
    altitude_values -= altitude_values.min()
    roll_values = np.interp(timeline, attitude["Time"], attitude["Roll"])
    pitch_values = np.interp(timeline, attitude["Time"], attitude["Pitch"])

    figure = plt.figure(figsize=(10, 3))
    grid = figure.add_gridspec(1, 5, width_ratios=[0.3, 0.8, 1, 0.8, 0.3], wspace=0.3)
    speed_axis = figure.add_subplot(grid[0])
    pitch_axis = figure.add_subplot(grid[1])
    path_axis = figure.add_subplot(grid[2])
    roll_axis = figure.add_subplot(grid[3])
    altitude_axis = figure.add_subplot(grid[4])

    def add_instrument(axis: plt.Axes, filename: str):
        instrument_image = mpimg.imread(ASSETS_DIR / filename)
        height, width = instrument_image.shape[:2]
        image_width = 1.0
        image_height = image_width / (width / height)
        artist = axis.imshow(
            instrument_image,
            origin="upper",
            extent=[-image_width / 2, image_width / 2, -image_height / 2, image_height / 2],
            zorder=2,
        )
        padding = 1.2
        axis.set_xlim(-image_width / 2 * padding, image_width / 2 * padding)
        axis.set_ylim(-image_height / 2 * padding, image_height / 2 * padding)
        axis.axis("off")
        return artist

    roll_image = add_instrument(roll_axis, "roll.png")
    pitch_image = add_instrument(pitch_axis, "pitch.png")

    figure.patch.set_facecolor("#2f2f2f")
    path_axis.set_facecolor("#2f2f2f")
    for spine in path_axis.spines.values():
        spine.set_color("white")
    path_axis.tick_params(colors="white")
    if not sleek:
        path_axis.set_xlabel("X (m)", color="white")
        path_axis.set_ylabel("Y (m)", color="white")
        path_axis.set_title("Flight Path Animation", color="white")
        path_axis.grid(linestyle="--", linewidth=0.5, alpha=0.5, color="white")
    path_axis.set_aspect("equal", "box")

    points = np.column_stack((x_values, y_values))
    segments = np.stack((points[:-1], points[1:]), axis=1)
    altitude_max = float(altitude_values.max())
    normalization = mpl.colors.Normalize(vmin=0, vmax=max(altitude_max, 1.0))
    path_collection = LineCollection(segments, cmap=HALF_GREYS, norm=normalization, linewidth=2)
    path_axis.add_collection(path_collection)
    current_point, = path_axis.plot([], [], "o", color="white", markersize=8)

    speed_text = speed_axis.text(
        0.5, 0.5, "", ha="center", va="bottom", fontsize=9, color="white"
    )
    altitude_text = altitude_axis.text(
        0.5, 0.5, "", ha="center", va="bottom", fontsize=9, color="white"
    )
    speed_axis.axis("off")
    altitude_axis.axis("off")
    path_axis.set_xlim(x_values.min() - 10, x_values.max() + 10)
    path_axis.set_ylim(y_values.min() - 10, y_values.max() + 10)
    path_axis.set_xticks([])
    path_axis.set_yticks([])

    def initialize():
        path_collection.set_segments([])
        current_point.set_data([], [])
        return path_collection, current_point, speed_text, altitude_text

    def update(frame: int):
        path_collection.set_segments(segments[:frame])
        path_collection.set_array(altitude_values[:frame])
        current_point.set_data([x_values[frame]], [y_values[frame]])
        speed_text.set_text(f"Velocity: {speed_values[frame]:.1f} mph")
        altitude_text.set_text(f"Altitude: {altitude_values[frame]:.1f} m")
        roll_image.set_transform(
            Affine2D().rotate(-np.deg2rad(roll_values[frame])) + roll_axis.transData
        )
        pitch_image.set_transform(
            Affine2D().rotate(-np.deg2rad(pitch_values[frame])) + pitch_axis.transData
        )
        return path_collection, current_point, speed_text, altitude_text

    animation = FuncAnimation(
        figure,
        update,
        frames=len(timeline),
        init_func=initialize,
        blit=True,
        interval=1000 / fps,
    )

    if save_path is None:
        plt.show()
        return None
    if not writers.is_available("ffmpeg"):
        plt.close(figure)
        raise RuntimeError("FFmpeg is required to save MP4 animations but was not found on PATH")

    output_path = Path(save_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        writer = FFMpegWriter(fps=fps, codec="libx264", bitrate=1800)
        animation.save(str(output_path), writer=writer, dpi=200)
    finally:
        plt.close(figure)
    LOGGER.info("Animation saved to %s", output_path)
    return output_path

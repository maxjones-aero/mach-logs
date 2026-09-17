"""End-to-end generation of standalone editorial overlay assets."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .config import RenderConfig, Theme
from .encoder import FFmpegEncoder
from .renderer import BroadcastRenderer
from .telemetry import FuelModel, TelemetryTimeline

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OverlayOutputs:
    """Paths written by one H.264 overlay package."""

    overlay: Path
    alpha_matte: Path
    blur_matte: Path
    metadata: Path | None = None


def _validate_output_paths(outputs: OverlayOutputs, overwrite: bool) -> None:
    expected_suffixes = {
        "overlay": ".mp4",
        "alpha_matte": ".mp4",
        "blur_matte": ".png",
        "metadata": ".json",
    }
    for name, expected_suffix in expected_suffixes.items():
        path = getattr(outputs, name)
        if path is not None and path.suffix.lower() != expected_suffix:
            raise ValueError(f"{name} output must use the {expected_suffix} extension")

    paths = [path for path in asdict(outputs).values() if path is not None]
    normalized = [Path(path).resolve() for path in paths]
    if len(set(normalized)) != len(normalized):
        raise ValueError("overlay, alpha matte, blur matte and metadata must use different paths")
    if not overwrite:
        existing = [str(path) for path in normalized if path.exists()]
        if existing:
            raise FileExistsError(
                f"output already exists: {', '.join(existing)}; use --overwrite to replace it"
            )


def _write_metadata(
    path: Path,
    *,
    timeline: TelemetryTimeline,
    config: RenderConfig,
    theme: Theme,
    outputs: OverlayOutputs,
    fuel_model: FuelModel,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "format_version": 1,
        "resolution": {"width": config.width, "height": config.height},
        "fps": config.fps,
        "frame_count": timeline.frame_count,
        "duration_seconds": timeline.duration_seconds,
        "log_time": {
            "first_frame_seconds": timeline.start_time,
            "last_frame_seconds": timeline.finish_time,
        },
        "presentation": {
            "title": config.title,
            "theme": theme.name,
            "units": config.units,
            "overlay_format": "H.264 colour plus frame-aligned alpha matte",
            "blur_matte_usage": "static luma mask for editor-applied background blur",
        },
        "telemetry_models": {
            "battery": {
                "chemistry": "LiPo",
                "cell_count": timeline.battery_cell_count,
            },
            "fuel": {
                "idle_litres_per_minute": fuel_model.idle_litres_per_minute,
                "full_litres_per_minute": fuel_model.full_litres_per_minute,
                "total_consumed_litres": timeline.fuel_total_litres,
                "initial_fuel_litres": timeline.fuel_initial_litres,
                "final_fuel_litres": timeline.fuel_final_litres,
                "model_start_seconds": timeline.fuel_model_start_time,
                "model_stop_seconds": timeline.fuel_model_stop_time,
                "throttle_servo_channel": timeline.throttle_channel,
            },
        },
        "files": {
            "overlay": str(outputs.overlay),
            "alpha_matte": str(outputs.alpha_matte),
            "blur_matte": str(outputs.blur_matte),
        },
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def render_overlay_package(
    gps: pd.DataFrame,
    attitude: pd.DataFrame,
    imu: pd.DataFrame,
    battery: pd.DataFrame,
    servo_outputs: pd.DataFrame,
    parameters: pd.DataFrame,
    *,
    config: RenderConfig,
    theme: Theme,
    outputs: OverlayOutputs,
    start_time: float | None = None,
    finish_time: float | None = None,
    fuel_model: FuelModel | None = None,
    overwrite: bool = False,
) -> OverlayOutputs:
    """Render H.264 colour/alpha videos, a static blur matte, and metadata."""
    _validate_output_paths(outputs, overwrite)
    fuel_model = fuel_model or FuelModel()
    timeline = TelemetryTimeline.from_frames(
        gps,
        attitude,
        imu,
        battery,
        servo_outputs,
        parameters,
        fps=config.fps,
        start_time=start_time,
        finish_time=finish_time,
        fuel_model=fuel_model,
    )
    renderer = BroadcastRenderer(timeline, config, theme)
    outputs.blur_matte.parent.mkdir(parents=True, exist_ok=True)
    renderer.render_static_blur_matte().save(outputs.blur_matte)

    with (
        FFmpegEncoder(
            outputs.overlay,
            width=config.width,
            height=config.height,
            fps=config.fps,
            kind="h264_overlay",
            overwrite=overwrite,
        ) as overlay_encoder,
        FFmpegEncoder(
            outputs.alpha_matte,
            width=config.width,
            height=config.height,
            fps=config.fps,
            kind="alpha_matte",
            overwrite=overwrite,
        ) as alpha_encoder,
    ):
        progress_interval = max(1, timeline.frame_count // 20)
        for index in range(timeline.frame_count):
            overlay_frame = renderer.render_overlay(index)
            overlay_encoder.write(overlay_frame.convert("RGB"))
            alpha_encoder.write(renderer.render_alpha_matte(index, overlay_frame))
            if index % progress_interval == 0 or index == timeline.frame_count - 1:
                percent = round((index + 1) / timeline.frame_count * 100)
                LOGGER.info("Rendering overlay: %d%%", percent)

    if outputs.metadata:
        _write_metadata(
            outputs.metadata,
            timeline=timeline,
            config=config,
            theme=theme,
            outputs=outputs,
            fuel_model=fuel_model,
        )
    return outputs

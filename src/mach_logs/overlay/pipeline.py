"""End-to-end generation of standalone editorial overlay assets."""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .config import RenderConfig, Theme
from .encoder import FFmpegEncoder
from .renderer import BroadcastRenderer
from .telemetry import TelemetryTimeline

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OverlayOutputs:
    """Paths written by one overlay render."""

    overlay: Path
    matte: Path | None = None
    preview: Path | None = None
    metadata: Path | None = None


def _validate_output_paths(outputs: OverlayOutputs, overwrite: bool) -> None:
    expected_suffixes = {
        "overlay": ".mov",
        "matte": ".mov",
        "preview": ".mp4",
        "metadata": ".json",
    }
    for name, expected_suffix in expected_suffixes.items():
        path = getattr(outputs, name)
        if path is not None and path.suffix.lower() != expected_suffix:
            raise ValueError(f"{name} output must use the {expected_suffix} extension")

    paths = [path for path in asdict(outputs).values() if path is not None]
    normalized = [Path(path).resolve() for path in paths]
    if len(set(normalized)) != len(normalized):
        raise ValueError("overlay, matte, preview and metadata outputs must use different paths")
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
            "alpha": "straight",
            "overlay_blend_mode": "normal",
            "matte_usage": "luma matte for editor-applied background blur",
        },
        "files": {
            "overlay": str(outputs.overlay),
            "matte": str(outputs.matte) if outputs.matte else None,
            "preview": str(outputs.preview) if outputs.preview else None,
        },
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def render_overlay_package(
    gps: pd.DataFrame,
    attitude: pd.DataFrame,
    *,
    config: RenderConfig,
    theme: Theme,
    outputs: OverlayOutputs,
    start_time: float | None = None,
    finish_time: float | None = None,
    overwrite: bool = False,
) -> OverlayOutputs:
    """Render transparent overlay, blur matte, preview and editorial metadata."""
    _validate_output_paths(outputs, overwrite)
    timeline = TelemetryTimeline.from_frames(
        gps,
        attitude,
        fps=config.fps,
        start_time=start_time,
        finish_time=finish_time,
    )
    renderer = BroadcastRenderer(timeline, config, theme)

    with ExitStack() as stack:
        overlay_encoder = stack.enter_context(
            FFmpegEncoder(
                outputs.overlay,
                width=config.width,
                height=config.height,
                fps=config.fps,
                kind="overlay",
                overwrite=overwrite,
            )
        )
        matte_encoder = (
            stack.enter_context(
                FFmpegEncoder(
                    outputs.matte,
                    width=config.width,
                    height=config.height,
                    fps=config.fps,
                    kind="matte",
                    overwrite=overwrite,
                )
            )
            if outputs.matte
            else None
        )
        preview_encoder = (
            stack.enter_context(
                FFmpegEncoder(
                    outputs.preview,
                    width=config.width,
                    height=config.height,
                    fps=config.fps,
                    kind="preview",
                    overwrite=overwrite,
                )
            )
            if outputs.preview
            else None
        )

        progress_interval = max(1, timeline.frame_count // 20)
        for index in range(timeline.frame_count):
            overlay_frame = renderer.render_overlay(index)
            overlay_encoder.write(overlay_frame)
            if matte_encoder:
                matte_encoder.write(renderer.render_blur_matte(index))
            if preview_encoder:
                preview_encoder.write(renderer.render_preview(index, overlay_frame))
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
        )
    return outputs

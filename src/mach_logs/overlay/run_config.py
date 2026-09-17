"""JSON configuration for a telemetry log and its overlay export."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import RenderConfig, Theme, get_theme
from .pipeline import OverlayOutputs
from .telemetry import FuelModel


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _path(base: Path, value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty path")
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


@dataclass(frozen=True)
class FlightSelection:
    """Rules used to locate the flight and add editorial handles."""

    launch_speed_metres_per_second: float = 10.0
    before_seconds: float = 10.0
    after_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.launch_speed_metres_per_second <= 0:
            raise ValueError("launch speed must be greater than zero")
        if self.before_seconds < 0 or self.after_seconds < 0:
            raise ValueError("flight handles cannot be negative")


@dataclass(frozen=True)
class RunConfig:
    """All reproducible inputs needed to render one flight overlay."""

    source: Path
    log: Path
    reference_latitude: float
    reference_longitude: float
    selection: FlightSelection
    render: RenderConfig
    theme: Theme
    fuel: FuelModel
    outputs: OverlayOutputs


def load_run_config(path: str | Path) -> RunConfig:
    """Load and validate a run JSON file, resolving paths beside that file."""
    source = Path(path).resolve()
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {source}: {error.msg}") from error
    document = _mapping(document, "run configuration")
    base = source.parent

    reference = _mapping(document.get("reference"), "reference")
    selection_data = _mapping(document.get("selection", {}), "selection")
    video = _mapping(document.get("video", {}), "video")
    presentation = _mapping(document.get("presentation", {}), "presentation")
    fuel_data = _mapping(document.get("fuel", {}), "fuel")
    output_data = _mapping(document.get("outputs"), "outputs")

    selection = FlightSelection(**selection_data)
    render = RenderConfig(
        width=video.get("width", 1920),
        height=video.get("height", 1080),
        fps=video.get("fps", 30),
        title=presentation.get("title", "FLIGHT TIME"),
        units=presentation.get("units", "imperial"),
        trail_seconds=presentation.get("trail_seconds", 12.0),
        fade_seconds=presentation.get("fade_seconds", 0.0),
    )
    fuel = FuelModel(
        idle_litres_per_minute=fuel_data.get("idle_litres_per_minute", 0.179),
        full_litres_per_minute=fuel_data.get("full_litres_per_minute", 0.98),
        total_consumed_litres=fuel_data.get("total_consumed_litres", 0.95),
        final_remaining_litres=fuel_data.get("final_remaining_litres", 1.2),
        prelaunch_seconds=selection.before_seconds,
        launch_speed_metres_per_second=selection.launch_speed_metres_per_second,
    )
    metadata_value = output_data.get("metadata")
    outputs = OverlayOutputs(
        overlay=_path(base, output_data.get("overlay"), "outputs.overlay"),
        alpha_matte=_path(
            base, output_data.get("alpha_matte"), "outputs.alpha_matte"
        ),
        blur_matte=_path(base, output_data.get("blur_matte"), "outputs.blur_matte"),
        metadata=(
            _path(base, metadata_value, "outputs.metadata")
            if metadata_value is not None
            else None
        ),
    )
    return RunConfig(
        source=source,
        log=_path(base, document.get("log"), "log"),
        reference_latitude=float(reference["latitude"]),
        reference_longitude=float(reference["longitude"]),
        selection=selection,
        render=render,
        theme=get_theme(
            presentation.get("theme", "orbital"), presentation.get("accent")
        ),
        fuel=fuel,
        outputs=outputs,
    )

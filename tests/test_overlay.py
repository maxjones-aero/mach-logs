from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from mach_logs.overlay.config import RenderConfig, get_theme, parse_hex_colour
from mach_logs.overlay.encoder import FFmpegEncoder
from mach_logs.overlay.pipeline import OverlayOutputs, _validate_output_paths
from mach_logs.overlay.renderer import BroadcastRenderer
from mach_logs.overlay.telemetry import TelemetryTimeline


def telemetry_frames():
    gps = pd.DataFrame(
        {
            "Time": [10.0, 11.0, 12.0],
            "X": [0.0, 8.0, 16.0],
            "Y": [0.0, 4.0, 3.0],
            "Alt": [100.0, 105.0, 110.0],
            "Spd_3D": [10.0, 12.0, 11.0],
        }
    )
    attitude = pd.DataFrame(
        {
            "Time": [10.0, 11.0, 12.0],
            "Roll": [0.0, 5.0, -3.0],
            "Pitch": [1.0, 2.0, 0.0],
        }
    )
    return gps, attitude


def test_timeline_is_aligned_to_output_frames():
    gps, attitude = telemetry_frames()
    timeline = TelemetryTimeline.from_frames(gps, attitude, fps=2)

    assert timeline.frame_count == 5
    assert timeline.duration_seconds == 2.0
    assert list(timeline.time) == [10.0, 10.5, 11.0, 11.5, 12.0]
    assert timeline.x[1] == pytest.approx(4.0)


def test_timeline_rejects_ranges_outside_shared_data():
    gps, attitude = telemetry_frames()

    with pytest.raises(ValueError, match="outside the shared data range"):
        TelemetryTimeline.from_frames(gps, attitude, fps=25, start_time=9.0)


def test_renderer_produces_overlay_matte_and_preview_frames():
    gps, attitude = telemetry_frames()
    config = RenderConfig(width=640, height=360, fps=2, fade_seconds=0)
    timeline = TelemetryTimeline.from_frames(gps, attitude, fps=config.fps)
    renderer = BroadcastRenderer(timeline, config, get_theme("orbital"))

    overlay = renderer.render_overlay(2)
    matte = renderer.render_blur_matte(2)
    preview = renderer.render_preview(2)

    assert overlay.mode == "RGBA"
    assert overlay.size == (640, 360)
    assert overlay.getchannel("A").getextrema() == (0, 255)
    assert matte.mode == "RGB"
    assert matte.getextrema()[0][1] == 255
    assert preview.mode == "RGB"


def test_custom_accent_colour_is_applied():
    theme = get_theme("orbital", "#12AEEF")
    assert theme.accent == (18, 174, 239, 255)
    assert parse_hex_colour("ffffff") == (255, 255, 255, 255)


@pytest.mark.parametrize(
    "config",
    [
        {"width": 639},
        {"width": 641},
        {"fps": 0},
        {"units": "knots"},
        {"trail_seconds": 0},
    ],
)
def test_invalid_render_configuration_is_rejected(config):
    with pytest.raises(ValueError):
        RenderConfig(**config)


def test_overlay_encoder_requests_prores_with_alpha():
    encoder = FFmpegEncoder(
        "out/test-overlay.mov",
        width=1920,
        height=1080,
        fps=30,
        kind="overlay",
    )
    with patch("mach_logs.overlay.encoder.shutil.which", return_value="ffmpeg"):
        command = encoder._command()

    assert "prores_ks" in command
    assert "yuva444p10le" in command
    assert "-alpha_bits" in command


def test_editorial_outputs_require_interchange_extensions():
    outputs = OverlayOutputs(overlay=Path("out/overlay.mp4"))
    with pytest.raises(ValueError, match="overlay output must use the .mov extension"):
        _validate_output_paths(outputs, overwrite=False)

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from mach_logs.overlay.config import RenderConfig, get_theme, parse_hex_colour
from mach_logs.overlay.encoder import FFmpegEncoder
from mach_logs.overlay.pipeline import OverlayOutputs, _validate_output_paths
from mach_logs.overlay.renderer import BroadcastRenderer
from mach_logs.overlay.run_config import load_run_config
from mach_logs.overlay.telemetry import TelemetryTimeline


def telemetry_frames():
    gps = pd.DataFrame(
        {
            "Time": [10.0, 11.0, 12.0],
            "X": [0.0, 8.0, 16.0],
            "Y": [0.0, 4.0, 3.0],
            "Alt": [100.0, 105.0, 110.0],
            "Spd_3D": [10.0, 12.0, 11.0],
            "VZ": [0.0, 0.0, 0.0],
        }
    )
    attitude = pd.DataFrame(
        {
            "Time": [10.0, 11.0, 12.0],
            "Roll": [0.0, 5.0, -3.0],
            "Pitch": [1.0, 2.0, 0.0],
        }
    )
    imu = pd.DataFrame(
        {
            "Time": [10.0, 11.0, 12.0],
            "AccX": [0.0, 0.0, 0.0],
            "AccY": [0.0, 0.0, 0.0],
            "AccZ": [-9.80665, -19.6133, -9.80665],
        }
    )
    battery = pd.DataFrame(
        {
            "Time": [10.0, 11.0, 12.0],
            "Volt": [12.6, 12.3, 12.0],
            "RemPct": [100.0, 95.0, 90.0],
        }
    )
    servo_outputs = pd.DataFrame(
        {
            "Time": [10.0, 11.0, 12.0],
            "C1": [1100.0, 1500.0, 1100.0],
        }
    )
    parameters = pd.DataFrame(
        {
            "Name": ["SERVO1_FUNCTION", "SERVO1_MIN", "SERVO1_MAX"],
            "Value": [70.0, 1100.0, 1900.0],
        }
    )
    return gps, attitude, imu, battery, servo_outputs, parameters


def test_timeline_is_aligned_to_output_frames():
    frames = telemetry_frames()
    timeline = TelemetryTimeline.from_frames(*frames, fps=2)

    assert timeline.frame_count == 5
    assert timeline.duration_seconds == 2.0
    assert list(timeline.time) == [10.0, 10.5, 11.0, 11.5, 12.0]
    assert timeline.x[1] == pytest.approx(4.0)
    assert timeline.lateral_g[2] == pytest.approx(2.0)
    assert timeline.axial_g[2] == pytest.approx(0.0)
    assert timeline.battery_cell_count == 3
    assert timeline.battery_percent[2] == pytest.approx(95.0)
    assert timeline.fuel_used_litres[-1] == pytest.approx(0.95)
    assert timeline.fuel_initial_litres == pytest.approx(2.15)
    assert timeline.fuel_remaining_litres[-1] == pytest.approx(1.2)


def test_timeline_rejects_ranges_outside_shared_data():
    frames = telemetry_frames()

    with pytest.raises(ValueError, match="outside the shared data range"):
        TelemetryTimeline.from_frames(*frames, fps=25, start_time=9.0)


def test_timeline_unwraps_roll_before_interpolating():
    gps, attitude, imu, battery, servo_outputs, parameters = telemetry_frames()
    attitude["Roll"] = [340.0, 20.0, 40.0]

    timeline = TelemetryTimeline.from_frames(
        gps, attitude, imu, battery, servo_outputs, parameters, fps=2
    )

    assert timeline.roll_degrees[1] == pytest.approx(360.0)
    assert timeline.roll_degrees[2] == pytest.approx(380.0)


def test_renderer_produces_overlay_and_matte_frames():
    frames = telemetry_frames()
    config = RenderConfig(width=640, height=360, fps=2, fade_seconds=0)
    timeline = TelemetryTimeline.from_frames(*frames, fps=config.fps)
    renderer = BroadcastRenderer(timeline, config, get_theme("orbital"))

    overlay = renderer.render_overlay(2)
    matte = renderer.render_blur_matte(2)
    alpha_frame = renderer.render_alpha_matte(2, overlay)
    blur_still = renderer.render_static_blur_matte()

    assert overlay.mode == "RGBA"
    assert overlay.size == (640, 360)
    assert overlay.getchannel("A").getextrema() == (0, 255)
    assert matte.mode == "RGB"
    assert matte.getextrema()[0][1] == 255
    assert alpha_frame.mode == "RGB"
    assert alpha_frame.getextrema()[0] == (0, 255)
    assert blur_still.mode == "RGB"


def test_renderer_keeps_the_bottom_centre_clear():
    frames = telemetry_frames()
    config = RenderConfig(width=640, height=360, fps=2, fade_seconds=0)
    timeline = TelemetryTimeline.from_frames(*frames, fps=config.fps)
    renderer = BroadcastRenderer(timeline, config, get_theme("orbital"))

    assert renderer.speed_panel.right <= config.width // 3 + 2
    assert renderer.speed_panel.bottom < renderer.attitude_panel.top
    assert renderer.path_panel.left >= config.width * 2 // 3
    assert renderer.path_panel.bottom < renderer.resource_panel.top
    margin = renderer.px(24)
    assert renderer.speed_panel.left == margin
    assert renderer.attitude_panel.left == margin
    assert renderer.path_panel.right == config.width - margin
    assert renderer.resource_panel.right == config.width - margin
    assert renderer.attitude_panel.bottom == config.height - margin
    assert renderer.resource_panel.bottom == config.height - margin
    assert renderer.timer_panel.top == margin
    assert renderer.timer_panel.right == config.width - margin


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


def test_overlay_encoder_requests_h264():
    encoder = FFmpegEncoder(
        "out/test-overlay.mp4",
        width=1920,
        height=1080,
        fps=30,
        kind="h264_overlay",
    )
    with patch("mach_logs.overlay.encoder.shutil.which", return_value="ffmpeg"):
        command = encoder._command()

    assert "libx264" in command
    assert "yuv420p" in command


def test_editorial_outputs_require_interchange_extensions():
    outputs = OverlayOutputs(
        overlay=Path("out/overlay.mov"),
        alpha_matte=Path("out/alpha.mp4"),
        blur_matte=Path("out/blur.png"),
    )
    with pytest.raises(ValueError, match="overlay output must use the .mp4 extension"):
        _validate_output_paths(outputs, overwrite=False)


def test_run_config_resolves_paths_and_builds_models(tmp_path):
    config_path = tmp_path / "flight.json"
    config_path.write_text(
        """{
          "log": "flight.bin",
          "reference": {"latitude": 51.1, "longitude": -2.1},
          "selection": {"before_seconds": 10, "after_seconds": 10},
          "video": {"width": 1920, "height": 1080, "fps": 30},
          "presentation": {"title": "FLIGHT TIME", "fade_seconds": 0},
          "fuel": {"total_consumed_litres": 0.95, "final_remaining_litres": 1.2},
          "outputs": {
            "overlay": "overlay.mp4",
            "alpha_matte": "alpha.mp4",
            "blur_matte": "blur.png"
          }
        }""",
        encoding="utf-8",
    )

    run = load_run_config(config_path)

    assert run.log == tmp_path / "flight.bin"
    assert run.outputs.alpha_matte == tmp_path / "alpha.mp4"
    assert run.render.title == "FLIGHT TIME"
    assert run.fuel.final_remaining_litres == pytest.approx(1.2)

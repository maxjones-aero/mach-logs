import pandas as pd
import pytest

from mach_logs.plotting import animate_flight_path, plot_flight_data


def animation_frames():
    gps = pd.DataFrame(
        {
            "Time": [1.0, 2.0],
            "X": [0.0, 1.0],
            "Y": [0.0, 1.0],
            "Alt": [10.0, 11.0],
            "Spd_3D": [5.0, 5.0],
        }
    )
    attitude = pd.DataFrame(
        {
            "Time": [1.0, 2.0],
            "Roll": [0.0, 0.0],
            "Pitch": [0.0, 0.0],
        }
    )
    return gps, attitude


def test_plot_rejects_missing_gps_fields():
    gps = pd.DataFrame({"Time": [1.0]})
    position = pd.DataFrame({"Time": [1.0], "X": [0.0], "Y": [0.0], "Alt": [10.0]})

    with pytest.raises(ValueError, match="GPS data is missing required fields"):
        plot_flight_data(gps, position)


def test_plot_rejects_time_window_outside_shared_data():
    gps = pd.DataFrame(
        {
            "Time": [1.0, 2.0],
            "X": [0.0, 1.0],
            "Y": [0.0, 1.0],
            "Alt": [10.0, 11.0],
            "Spd": [5.0, 5.0],
            "VZ": [0.0, 0.0],
            "Spd_3D": [5.0, 5.0],
        }
    )
    position = pd.DataFrame(
        {"Time": [1.0, 2.0], "X": [0.0, 1.0], "Y": [0.0, 1.0], "Alt": [10.0, 11.0]}
    )

    with pytest.raises(ValueError, match="outside the shared data range"):
        plot_flight_data(gps, position, start_time=0.0, finish_time=2.0)


def test_animation_rejects_invalid_time_window():
    gps, attitude = animation_frames()

    with pytest.raises(ValueError, match="earlier than finish"):
        animate_flight_path(gps, attitude, start_time=1.5, finish_time=1.5)


def test_animation_rejects_non_positive_fps():
    gps, attitude = animation_frames()

    with pytest.raises(ValueError, match="fps"):
        animate_flight_path(gps, attitude, fps=0)

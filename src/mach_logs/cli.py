"""Command-line interface for mach-logs."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from .parser import LogFormatError, parse_raw_log


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("log", type=Path, help="path to an ArduPilot DataFlash .bin log")
    parser.add_argument(
        "--reference-lat",
        type=float,
        required=True,
        help="origin latitude in decimal degrees",
    )
    parser.add_argument(
        "--reference-lon",
        type=float,
        required=True,
        help="origin longitude in decimal degrees",
    )
    parser.add_argument(
        "--start",
        type=float,
        help="start time in seconds; defaults to the first shared sample",
    )
    parser.add_argument(
        "--end",
        type=float,
        help="finish time in seconds; defaults to the last shared sample",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mach-logs",
        description="Parse and visualize ArduPilot DataFlash flight logs.",
    )
    parser.add_argument("--verbose", action="store_true", help="show informational progress")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plot_parser = subparsers.add_parser("plot", help="show or save flight telemetry plots")
    _add_common_arguments(plot_parser)
    plot_parser.add_argument(
        "--output",
        type=Path,
        help="save an image instead of opening a window",
    )

    animate_parser = subparsers.add_parser("animate", help="render an animated flight path")
    _add_common_arguments(animate_parser)
    animate_parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="output frames per second (default: 30)",
    )
    animate_parser.add_argument(
        "--output",
        type=Path,
        default=Path("out/flight.mp4"),
        help="MP4 output path",
    )
    animate_parser.add_argument("--sleek", action="store_true", help="hide labels and grid lines")

    overlay_parser = subparsers.add_parser(
        "overlay",
        help="render an H.264 overlay and frame-aligned alpha matte",
    )
    overlay_parser.add_argument("config", type=Path, help="JSON run configuration")
    overlay_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing output files",
    )
    return parser


def _hold_last_sample(frame: pd.DataFrame, finish_time: float) -> pd.DataFrame:
    """Extend a telemetry stream so an editorial tail can hold its final value."""
    if frame.empty or float(frame["Time"].iloc[-1]) >= finish_time:
        return frame
    final = frame.iloc[[-1]].copy()
    final.loc[:, "Time"] = finish_time
    return pd.concat([frame, final], ignore_index=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if arguments.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    try:
        if arguments.command == "plot":
            frames = parse_raw_log(
                arguments.log,
                arguments.reference_lat,
                arguments.reference_lon,
                message_types=("GPS", "POS"),
            )
            from .plotting import plot_flight_data

            plot_flight_data(
                frames["GPS"],
                frames["POS"],
                start_time=arguments.start,
                finish_time=arguments.end,
                save_path=arguments.output,
            )
        elif arguments.command == "animate":
            frames = parse_raw_log(
                arguments.log,
                arguments.reference_lat,
                arguments.reference_lon,
                message_types=("GPS", "ATT"),
            )
            from .plotting import animate_flight_path

            animate_flight_path(
                frames["GPS"],
                frames["ATT"],
                start_time=arguments.start,
                finish_time=arguments.end,
                fps=arguments.fps,
                save_path=arguments.output,
                sleek=arguments.sleek,
            )
        else:
            from .overlay import load_run_config, render_overlay_package

            run = load_run_config(arguments.config)
            frames = parse_raw_log(
                run.log,
                run.reference_latitude,
                run.reference_longitude,
                message_types=("GPS", "ATT", "IMU", "BAT", "RCOU", "PARM"),
            )
            launch_samples = frames["GPS"].loc[
                frames["GPS"]["Spd_3D"].gt(
                    run.selection.launch_speed_metres_per_second
                ),
                "Time",
            ]
            if launch_samples.empty:
                raise ValueError("could not detect launch from GPS speed")
            launch_time = float(launch_samples.iloc[0])
            landing_time = float(frames["GPS"]["Time"].max())
            start_time = launch_time - run.selection.before_seconds
            finish_time = landing_time + run.selection.after_seconds
            for message_type in ("GPS", "ATT", "IMU", "BAT", "RCOU"):
                frames[message_type] = _hold_last_sample(
                    frames[message_type], finish_time
                )

            render_overlay_package(
                frames["GPS"],
                frames["ATT"],
                frames["IMU"],
                frames["BAT"],
                frames["RCOU"],
                frames["PARM"],
                config=run.render,
                theme=run.theme,
                outputs=run.outputs,
                start_time=start_time,
                finish_time=finish_time,
                fuel_model=run.fuel,
                overwrite=arguments.overwrite,
            )
    except (FileExistsError, FileNotFoundError, LogFormatError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    return 0

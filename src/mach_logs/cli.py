"""Command-line interface for mach-logs."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if arguments.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    try:
        from .plotting import animate_flight_path, plot_flight_data

        frames = parse_raw_log(
            arguments.log,
            arguments.reference_lat,
            arguments.reference_lon,
        )
        if arguments.command == "plot":
            plot_flight_data(
                frames["GPS"],
                frames["POS"],
                start_time=arguments.start,
                finish_time=arguments.end,
                save_path=arguments.output,
            )
        else:
            animate_flight_path(
                frames["GPS"],
                frames["ATT"],
                start_time=arguments.start,
                finish_time=arguments.end,
                fps=arguments.fps,
                save_path=arguments.output,
                sleek=arguments.sleek,
            )
    except (FileNotFoundError, LogFormatError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    return 0

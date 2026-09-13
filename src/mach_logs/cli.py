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

    overlay_parser = subparsers.add_parser(
        "overlay",
        help="render standalone broadcast graphics with transparency",
    )
    _add_common_arguments(overlay_parser)
    overlay_parser.add_argument(
        "--output",
        type=Path,
        default=Path("out/flight-overlay.mov"),
        help="transparent ProRes 4444 output",
    )
    overlay_parser.add_argument(
        "--matte-output",
        type=Path,
        default=Path("out/flight-blur-matte.mov"),
        help="ProRes luma matte for editor-applied panel blur",
    )
    overlay_parser.add_argument(
        "--preview-output",
        type=Path,
        default=Path("out/flight-overlay-preview.mp4"),
        help="H.264 review preview",
    )
    overlay_parser.add_argument(
        "--metadata-output",
        type=Path,
        default=Path("out/flight-overlay.json"),
        help="editorial timing and format metadata",
    )
    overlay_parser.add_argument(
        "--no-matte",
        action="store_true",
        help="do not render a blur matte",
    )
    overlay_parser.add_argument(
        "--no-preview",
        action="store_true",
        help="do not render a review preview",
    )
    overlay_parser.add_argument(
        "--width",
        type=int,
        default=1920,
        help="frame width (default: 1920)",
    )
    overlay_parser.add_argument(
        "--height",
        type=int,
        default=1080,
        help="frame height (default: 1080)",
    )
    overlay_parser.add_argument("--fps", type=int, default=30, help="frame rate (default: 30)")
    overlay_parser.add_argument(
        "--title",
        default="FLIGHT TELEMETRY",
        help="short label shown beside the mission timer",
    )
    overlay_parser.add_argument(
        "--units",
        choices=("imperial", "metric"),
        default="imperial",
        help="display units (default: imperial)",
    )
    overlay_parser.add_argument(
        "--theme",
        choices=("orbital", "minimal"),
        default="orbital",
        help="visual theme (default: orbital)",
    )
    overlay_parser.add_argument(
        "--accent",
        help="custom accent colour in #RRGGBB format",
    )
    overlay_parser.add_argument(
        "--trail-seconds",
        type=float,
        default=12.0,
        help="length of the bright flight-path trail",
    )
    overlay_parser.add_argument(
        "--fade-seconds",
        type=float,
        default=0.6,
        help="panel fade-in and fade-out duration",
    )
    overlay_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing output files",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if arguments.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    try:
        message_types = ("GPS", "POS") if arguments.command == "plot" else ("GPS", "ATT")
        frames = parse_raw_log(
            arguments.log,
            arguments.reference_lat,
            arguments.reference_lon,
            message_types=message_types,
        )
        if arguments.command == "plot":
            from .plotting import plot_flight_data

            plot_flight_data(
                frames["GPS"],
                frames["POS"],
                start_time=arguments.start,
                finish_time=arguments.end,
                save_path=arguments.output,
            )
        elif arguments.command == "animate":
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
            from .overlay import OverlayOutputs, RenderConfig, get_theme, render_overlay_package

            render_overlay_package(
                frames["GPS"],
                frames["ATT"],
                config=RenderConfig(
                    width=arguments.width,
                    height=arguments.height,
                    fps=arguments.fps,
                    title=arguments.title,
                    units=arguments.units,
                    trail_seconds=arguments.trail_seconds,
                    fade_seconds=arguments.fade_seconds,
                ),
                theme=get_theme(arguments.theme, arguments.accent),
                outputs=OverlayOutputs(
                    overlay=arguments.output,
                    matte=None if arguments.no_matte else arguments.matte_output,
                    preview=None if arguments.no_preview else arguments.preview_output,
                    metadata=arguments.metadata_output,
                ),
                start_time=arguments.start,
                finish_time=arguments.end,
                overwrite=arguments.overwrite,
            )
    except (FileExistsError, FileNotFoundError, LogFormatError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    return 0

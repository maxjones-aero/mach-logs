"""Pillow-based broadcast telemetry renderer."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import RGBA, RenderConfig, Theme
from .telemetry import TelemetryTimeline


@dataclass(frozen=True)
class Rectangle:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def inset(self, amount: int) -> Rectangle:
        return Rectangle(
            self.left + amount,
            self.top + amount,
            self.right - amount,
            self.bottom - amount,
        )

    def as_box(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom


@lru_cache(maxsize=32)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        windows_fonts / ("seguisb.ttf" if bold else "segoeui.ttf"),
        Path(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size=size)
    except OSError:
        return ImageFont.load_default(size=size)


def _with_alpha(colour: RGBA, alpha: int) -> RGBA:
    return colour[0], colour[1], colour[2], max(0, min(255, alpha))


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


class BroadcastRenderer:
    """Render standalone RGBA overlays, blur mattes and review previews."""

    def __init__(
        self,
        timeline: TelemetryTimeline,
        config: RenderConfig,
        theme: Theme,
    ) -> None:
        self.timeline = timeline
        self.config = config
        self.theme = theme
        self.scale = min(config.width / 1920, config.height / 1080)
        self.speed_panel, self.path_panel, self.attitude_panel, self.timer_panel = self._layout()
        self.path_points = self._map_path_points()
        self.static_overlay = self._render_static_overlay()
        self.static_matte = self._render_static_matte()
        self.preview_background = self._render_preview_background()
        self.relative_altitude = timeline.altitude_metres - float(
            np.nanmin(timeline.altitude_metres)
        )
        self.speed_max = max(float(np.nanpercentile(timeline.speed_metres_per_second, 98)), 1.0)

    def px(self, value: float) -> int:
        return max(1, round(value * self.scale))

    def _layout(self) -> tuple[Rectangle, Rectangle, Rectangle, Rectangle]:
        margin = self.px(54)
        gap = self.px(18)
        speed_width = self.px(272)
        path_width = self.px(590)
        attitude_width = self.px(370)
        side_height = self.px(230)
        path_height = self.px(300)
        total_width = speed_width + path_width + attitude_width + gap * 2
        left = (self.config.width - total_width) // 2
        bottom = self.config.height - margin

        speed = Rectangle(left, bottom - side_height, left + speed_width, bottom)
        path_left = speed.right + gap
        path = Rectangle(path_left, bottom - path_height, path_left + path_width, bottom)
        attitude_left = path.right + gap
        attitude = Rectangle(
            attitude_left,
            bottom - side_height,
            attitude_left + attitude_width,
            bottom,
        )
        timer_width = self.px(310)
        timer_height = self.px(66)
        timer = Rectangle(
            self.config.width - margin - timer_width,
            margin,
            self.config.width - margin,
            margin + timer_height,
        )
        return speed, path, attitude, timer

    def _glass_panel(self, image: Image.Image, rectangle: Rectangle, radius: int) -> None:
        shadow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        offset = self.px(8)
        shadow_box = (
            rectangle.left + offset,
            rectangle.top + offset,
            rectangle.right + offset,
            rectangle.bottom + offset,
        )
        shadow_draw.rounded_rectangle(shadow_box, radius=radius, fill=self.theme.shadow)
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(self.px(18)))
        image.alpha_composite(shadow_layer)

        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            rectangle.as_box(),
            radius=radius,
            fill=self.theme.panel_fill,
            outline=self.theme.panel_border,
            width=self.px(1.5),
        )
        highlight_y = rectangle.top + self.px(2)
        draw.line(
            (rectangle.left + radius, highlight_y, rectangle.right - radius, highlight_y),
            fill=_with_alpha(self.theme.primary, 38),
            width=self.px(1),
        )

    def _label(
        self,
        draw: ImageDraw.ImageDraw,
        position: tuple[int, int],
        text: str,
        *,
        anchor: str = "la",
    ) -> None:
        draw.text(
            position,
            text,
            font=_font(self.px(13), bold=True),
            fill=self.theme.secondary,
            anchor=anchor,
        )

    def _render_static_overlay(self) -> Image.Image:
        image = Image.new("RGBA", (self.config.width, self.config.height), (0, 0, 0, 0))
        radius = self.px(20)
        for panel in (self.speed_panel, self.path_panel, self.attitude_panel, self.timer_panel):
            self._glass_panel(image, panel, radius)

        draw = ImageDraw.Draw(image)
        inset = self.px(24)
        self._label(
            draw,
            (self.speed_panel.left + inset, self.speed_panel.top + inset),
            "GROUND SPEED",
        )
        self._label(
            draw,
            (self.path_panel.left + inset, self.path_panel.top + inset),
            "FLIGHT PATH",
        )
        self._label(
            draw,
            (self.attitude_panel.left + inset, self.attitude_panel.top + inset),
            "ATTITUDE / ALTITUDE",
        )
        self._label(
            draw,
            (self.timer_panel.left + self.px(18), self.timer_panel.top + self.px(17)),
            self.config.title.upper(),
        )

        accent_width = self.px(34)
        for panel in (self.speed_panel, self.path_panel, self.attitude_panel):
            y = panel.top + self.px(49)
            draw.line(
                (panel.left + inset, y, panel.left + inset + accent_width, y),
                fill=self.theme.accent,
                width=self.px(2),
            )
        if len(self.path_points) > 1:
            draw.line(
                self.path_points,
                fill=_with_alpha(self.theme.secondary, 28),
                width=self.px(1.5),
            )
        return image

    def _render_static_matte(self) -> Image.Image:
        image = Image.new("L", (self.config.width, self.config.height), 0)
        draw = ImageDraw.Draw(image)
        radius = self.px(20)
        for panel in (self.speed_panel, self.path_panel, self.attitude_panel, self.timer_panel):
            draw.rounded_rectangle(panel.as_box(), radius=radius, fill=255)
        return image.filter(ImageFilter.GaussianBlur(self.px(7)))

    def _render_preview_background(self) -> Image.Image:
        width, height = self.config.width, self.config.height
        mix = np.linspace(0, 1, height, dtype=np.float32)[:, np.newaxis]
        colours = np.concatenate(
            (
                15 + 3 * mix,
                28 + 14 * mix,
                39 + 18 * mix,
                np.full_like(mix, 255),
            ),
            axis=1,
        ).astype(np.uint8)
        pixels = np.repeat(colours[:, np.newaxis, :], width, axis=1)
        image = Image.fromarray(pixels)

        draw = ImageDraw.Draw(image)
        grid = self.px(96)
        grid_colour = (118, 160, 183, 17)
        for x in range(0, width, grid):
            draw.line((x, 0, x, height), fill=grid_colour, width=1)
        for y in range(0, height, grid):
            draw.line((0, y, width, y), fill=grid_colour, width=1)
        return image

    def _map_path_points(self) -> list[tuple[int, int]]:
        area = self.path_panel.inset(self.px(34))
        area = Rectangle(area.left, area.top + self.px(32), area.right, area.bottom)
        x_min, x_max = float(np.nanmin(self.timeline.x)), float(np.nanmax(self.timeline.x))
        y_min, y_max = float(np.nanmin(self.timeline.y)), float(np.nanmax(self.timeline.y))
        x_span = max(x_max - x_min, 1.0)
        y_span = max(y_max - y_min, 1.0)
        scale = min(area.width / x_span, area.height / y_span) * 0.88
        centre_x = (x_min + x_max) / 2
        centre_y = (y_min + y_max) / 2
        pixel_centre_x = (area.left + area.right) / 2
        pixel_centre_y = (area.top + area.bottom) / 2
        return [
            (
                round(pixel_centre_x + (x_value - centre_x) * scale),
                round(pixel_centre_y - (y_value - centre_y) * scale),
            )
            for x_value, y_value in zip(self.timeline.x, self.timeline.y, strict=True)
        ]

    def _presentation_opacity(self, index: int) -> float:
        if self.config.fade_seconds == 0:
            return 1.0
        elapsed = index / self.config.fps
        remaining = self.timeline.duration_seconds - elapsed
        fade_in = _smoothstep(elapsed / self.config.fade_seconds)
        fade_out = _smoothstep(remaining / self.config.fade_seconds)
        return min(fade_in, fade_out)

    def _draw_speed(self, draw: ImageDraw.ImageDraw, index: int) -> None:
        speed_ms = float(self.timeline.speed_metres_per_second[index])
        if self.config.units == "imperial":
            speed = speed_ms * 2.236936
            unit = "MPH"
            maximum = self.speed_max * 2.236936
        else:
            speed = speed_ms * 3.6
            unit = "KM/H"
            maximum = self.speed_max * 3.6

        x = self.speed_panel.left + self.px(24)
        y = self.speed_panel.top + self.px(73)
        draw.text(
            (x, y),
            f"{speed:03.0f}",
            font=_font(self.px(64), bold=True),
            fill=self.theme.primary,
            anchor="la",
        )
        draw.text(
            (self.speed_panel.right - self.px(25), y + self.px(46)),
            unit,
            font=_font(self.px(14), bold=True),
            fill=self.theme.secondary,
            anchor="ra",
        )

        bar = Rectangle(
            x,
            self.speed_panel.bottom - self.px(38),
            self.speed_panel.right - self.px(24),
            self.speed_panel.bottom - self.px(32),
        )
        draw.rounded_rectangle(bar.as_box(), radius=self.px(3), fill=(255, 255, 255, 28))
        proportion = max(0.0, min(1.0, speed / max(maximum, 1.0)))
        fill_right = round(bar.left + bar.width * proportion)
        if fill_right > bar.left:
            draw.rounded_rectangle(
                (bar.left, bar.top, fill_right, bar.bottom),
                radius=self.px(3),
                fill=self.theme.accent,
            )

    def _draw_path(self, draw: ImageDraw.ImageDraw, index: int) -> None:
        trail_frames = max(2, round(self.config.trail_seconds * self.config.fps))
        start = max(1, index - trail_frames)
        for point_index in range(start, index + 1):
            age = (point_index - start) / max(index - start, 1)
            alpha = round(35 + age * 220)
            draw.line(
                (self.path_points[point_index - 1], self.path_points[point_index]),
                fill=_with_alpha(self.theme.accent, alpha),
                width=self.px(2.5),
            )

        current_x, current_y = self.path_points[index]
        angle = -float(self.timeline.heading_radians[index])
        length = self.px(14)
        wing = self.px(7)
        direction = (math.cos(angle), math.sin(angle))
        perpendicular = (-direction[1], direction[0])
        marker = [
            (current_x + direction[0] * length, current_y + direction[1] * length),
            (
                current_x - direction[0] * length * 0.65 + perpendicular[0] * wing,
                current_y - direction[1] * length * 0.65 + perpendicular[1] * wing,
            ),
            (
                current_x - direction[0] * length * 0.35,
                current_y - direction[1] * length * 0.35,
            ),
            (
                current_x - direction[0] * length * 0.65 - perpendicular[0] * wing,
                current_y - direction[1] * length * 0.65 - perpendicular[1] * wing,
            ),
        ]
        draw.polygon(marker, fill=self.theme.primary)
        draw.ellipse(
            (
                current_x - self.px(2),
                current_y - self.px(2),
                current_x + self.px(2),
                current_y + self.px(2),
            ),
            fill=self.theme.accent,
        )

    def _draw_attitude(self, image: Image.Image, draw: ImageDraw.ImageDraw, index: int) -> None:
        centre_x = self.attitude_panel.left + self.px(91)
        centre_y = self.attitude_panel.top + self.px(137)
        radius = self.px(54)
        size = radius * 2
        pitch = float(self.timeline.pitch_degrees[index])
        roll = float(self.timeline.roll_degrees[index])

        horizon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        horizon_draw = ImageDraw.Draw(horizon)
        pitch_offset = round(max(-30.0, min(30.0, pitch)) / 30 * radius * 0.45)
        split = radius + pitch_offset
        horizon_draw.rectangle((0, 0, size, split), fill=(33, 66, 82, 205))
        horizon_draw.rectangle((0, split, size, size), fill=(45, 34, 29, 210))
        horizon_draw.line((0, split, size, split), fill=self.theme.primary, width=self.px(2))
        horizon = horizon.rotate(roll, resample=Image.Resampling.BICUBIC)
        circle_mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(circle_mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        image.paste(horizon, (centre_x - radius, centre_y - radius), circle_mask)

        draw.ellipse(
            (centre_x - radius, centre_y - radius, centre_x + radius, centre_y + radius),
            outline=self.theme.panel_border,
            width=self.px(2),
        )
        wing = self.px(22)
        draw.line(
            (centre_x - wing, centre_y, centre_x - self.px(6), centre_y),
            fill=self.theme.accent,
            width=self.px(3),
        )
        draw.line(
            (centre_x + self.px(6), centre_y, centre_x + wing, centre_y),
            fill=self.theme.accent,
            width=self.px(3),
        )
        draw.ellipse(
            (
                centre_x - self.px(3),
                centre_y - self.px(3),
                centre_x + self.px(3),
                centre_y + self.px(3),
            ),
            fill=self.theme.accent,
        )

        altitude = float(self.relative_altitude[index])
        if self.config.units == "imperial":
            altitude *= 3.28084
            unit = "FT"
        else:
            unit = "M"
        value_x = self.attitude_panel.left + self.px(175)
        draw.text(
            (value_x, self.attitude_panel.top + self.px(78)),
            f"{altitude:04.0f}",
            font=_font(self.px(48), bold=True),
            fill=self.theme.primary,
            anchor="la",
        )
        draw.text(
            (self.attitude_panel.right - self.px(22), self.attitude_panel.top + self.px(116)),
            f"REL ALT / {unit}",
            font=_font(self.px(12), bold=True),
            fill=self.theme.secondary,
            anchor="ra",
        )
        draw.text(
            (value_x, self.attitude_panel.bottom - self.px(46)),
            f"ROLL  {roll:+05.1f}°",
            font=_font(self.px(12), bold=True),
            fill=self.theme.secondary,
            anchor="la",
        )
        draw.text(
            (value_x, self.attitude_panel.bottom - self.px(25)),
            f"PITCH {pitch:+05.1f}°",
            font=_font(self.px(12), bold=True),
            fill=self.theme.secondary,
            anchor="la",
        )

    def _draw_timer(self, draw: ImageDraw.ImageDraw, index: int) -> None:
        elapsed = index / self.config.fps
        total_seconds = round(elapsed)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        draw.text(
            (self.timer_panel.right - self.px(18), self.timer_panel.top + self.px(15)),
            f"T+ {hours:02d}:{minutes:02d}:{seconds:02d}",
            font=_font(self.px(22), bold=True),
            fill=self.theme.primary,
            anchor="ra",
        )

    def render_overlay(self, index: int) -> Image.Image:
        """Render one straight-alpha RGBA overlay frame."""
        if not 0 <= index < self.timeline.frame_count:
            raise IndexError(f"frame index {index} is outside the telemetry timeline")
        image = self.static_overlay.copy()
        draw = ImageDraw.Draw(image)
        self._draw_speed(draw, index)
        self._draw_path(draw, index)
        self._draw_attitude(image, draw, index)
        self._draw_timer(draw, index)

        opacity = self._presentation_opacity(index)
        if opacity < 1:
            alpha = image.getchannel("A").point(lambda value: round(value * opacity))
            image.putalpha(alpha)
        return image

    def render_blur_matte(self, index: int) -> Image.Image:
        """Render a feathered RGB luma matte for editor-controlled background blur."""
        if not 0 <= index < self.timeline.frame_count:
            raise IndexError(f"frame index {index} is outside the telemetry timeline")
        opacity = self._presentation_opacity(index)
        matte = self.static_matte
        if opacity < 1:
            matte = matte.point(lambda value: round(value * opacity))
        return Image.merge("RGB", (matte, matte, matte))

    def render_preview(self, index: int, overlay: Image.Image | None = None) -> Image.Image:
        """Composite the overlay over a neutral grid for fast editorial review."""
        preview = self.preview_background.copy()
        preview.alpha_composite(overlay if overlay is not None else self.render_overlay(index))
        return preview.convert("RGB")

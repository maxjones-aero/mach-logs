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


@lru_cache(maxsize=3)
def _aircraft_asset(name: str) -> Image.Image:
    """Load one of the packaged transparent aircraft silhouettes."""
    path = Path(__file__).resolve().parents[1] / "assets" / f"aircraft-{name}.png"
    with Image.open(path) as source:
        return source.convert("RGBA")


def _with_alpha(colour: RGBA, alpha: int) -> RGBA:
    return colour[0], colour[1], colour[2], max(0, min(255, alpha))


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def _wrap_degrees(value: float) -> float:
    """Return an angle in the conventional [-180, 180) display range."""
    return (value + 180.0) % 360.0 - 180.0


class BroadcastRenderer:
    """Render standalone RGBA overlays and their editorial mattes."""

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
        (
            self.speed_panel,
            self.path_panel,
            self.attitude_panel,
            self.resource_panel,
            self.timer_panel,
        ) = self._layout()
        self.path_points = self._map_path_points()
        self.static_overlay = self._render_static_overlay()
        self.static_matte = self._render_static_matte()

    def px(self, value: float) -> int:
        return max(1, round(value * self.scale))

    def _layout(self) -> tuple[Rectangle, Rectangle, Rectangle, Rectangle, Rectangle]:
        # Use one optical safe-area inset for every widget on every outer edge.
        margin = self.px(24)
        gap = self.px(18)
        speed_width = self.px(300)
        # Keep every bottom widget out of the centre third, where the aircraft is framed.
        path_width = self.px(300)
        attitude_width = self.px(370)
        resource_width = self.px(250)
        speed_height = self.px(135)
        attitude_height = self.px(230)
        path_height = self.px(300)
        resource_height = self.px(190)
        bottom = self.config.height - margin

        attitude_left = margin
        attitude = Rectangle(
            attitude_left,
            bottom - attitude_height,
            attitude_left + attitude_width,
            bottom,
        )
        speed_bottom = attitude.top - gap
        speed = Rectangle(margin, speed_bottom - speed_height, margin + speed_width, speed_bottom)
        resource = Rectangle(
            self.config.width - margin - resource_width,
            bottom - resource_height,
            self.config.width - margin,
            bottom,
        )
        path_bottom = resource.top - gap
        path = Rectangle(
            self.config.width - margin - path_width,
            path_bottom - path_height,
            self.config.width - margin,
            path_bottom,
        )
        timer_width = self.px(330)
        timer_height = self.px(72)
        timer = Rectangle(
            self.config.width - margin - timer_width,
            margin,
            self.config.width - margin,
            margin + timer_height,
        )
        return speed, path, attitude, resource, timer

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
            font=_font(self.px(18), bold=True),
            fill=self.theme.secondary,
            anchor=anchor,
        )

    def _render_static_overlay(self) -> Image.Image:
        image = Image.new("RGBA", (self.config.width, self.config.height), (0, 0, 0, 0))
        radius = self.px(20)
        for panel in (
            self.speed_panel,
            self.path_panel,
            self.attitude_panel,
            self.resource_panel,
            self.timer_panel,
        ):
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
            "THROTTLE / G LOADING",
        )
        self._label(
            draw,
            (self.resource_panel.left + inset, self.resource_panel.top + inset),
            "BATTERY / FUEL",
        )
        self._label(
            draw,
            (self.timer_panel.left + self.px(18), self.timer_panel.top + self.px(17)),
            self.config.title.upper(),
        )

        accent_width = self.px(34)
        for panel in (
            self.speed_panel,
            self.path_panel,
            self.attitude_panel,
            self.resource_panel,
        ):
            y = panel.top + self.px(49)
            draw.line(
                (panel.left + inset, y, panel.left + inset + accent_width, y),
                fill=self.theme.accent,
                width=self.px(2),
            )
        return image

    def _render_static_matte(self) -> Image.Image:
        image = Image.new("L", (self.config.width, self.config.height), 0)
        draw = ImageDraw.Draw(image)
        radius = self.px(20)
        for panel in (
            self.speed_panel,
            self.path_panel,
            self.attitude_panel,
            self.resource_panel,
            self.timer_panel,
        ):
            draw.rounded_rectangle(panel.as_box(), radius=radius, fill=255)
        return image.filter(ImageFilter.GaussianBlur(self.px(7)))

    def _aircraft_icon(self, name: str, size: int) -> Image.Image:
        """Return a centred, theme-coloured square aircraft icon for the current layout."""
        source = _aircraft_asset(name)
        icon = source.copy()
        icon.thumbnail((size, size), Image.Resampling.LANCZOS)
        tinted = Image.new("RGBA", icon.size, self.theme.primary)
        tinted.putalpha(icon.getchannel("A"))
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.alpha_composite(
            tinted,
            ((size - tinted.width) // 2, (size - tinted.height) // 2),
        )
        return canvas

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
        ground_ms = float(self.timeline.speed_metres_per_second[index])
        if self.config.units == "imperial":
            primary_factor, secondary_factor = 2.236936, 3.6
            primary_unit, secondary_unit = "MPH", "KM/H"
        else:
            primary_factor, secondary_factor = 3.6, 2.236936
            primary_unit, secondary_unit = "KM/H", "MPH"

        value_x = self.speed_panel.left + self.px(24)
        y = self.speed_panel.top + self.px(67)
        draw.text(
            (value_x, y),
            f"{ground_ms * primary_factor:03.0f}",
            font=_font(self.px(48), bold=True),
            fill=self.theme.primary,
            anchor="la",
        )
        detail_x = self.speed_panel.left + self.px(172)
        draw.text(
            (detail_x, y + self.px(4)),
            primary_unit,
            font=_font(self.px(16), bold=True),
            fill=self.theme.secondary,
            anchor="la",
        )
        draw.text(
            (detail_x, y + self.px(27)),
            f"{ground_ms * secondary_factor:.0f} {secondary_unit}",
            font=_font(self.px(18), bold=True),
            fill=self.theme.secondary,
            anchor="la",
        )

    def _draw_path(self, image: Image.Image, index: int) -> None:
        draw = ImageDraw.Draw(image)
        if index > 0:
            draw.line(
                self.path_points[: index + 1],
                fill=_with_alpha(self.theme.secondary, 70),
                width=self.px(1.5),
            )
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
        heading_degrees = math.degrees(float(self.timeline.heading_radians[index]))
        aircraft = self._aircraft_icon("top", self.px(32)).rotate(
            180 + heading_degrees,
            resample=Image.Resampling.BICUBIC,
            expand=True,
        )
        image.alpha_composite(
            aircraft,
            (round(current_x - aircraft.width / 2), round(current_y - aircraft.height / 2)),
        )
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
        centre_x = self.attitude_panel.left + self.px(120)
        centre_y = self.attitude_panel.top + self.px(145)
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

        aircraft = self._aircraft_icon("front", size)
        image.alpha_composite(
            aircraft,
            (centre_x - radius, centre_y - radius - self.px(11)),
        )

        draw.ellipse(
            (centre_x - radius, centre_y - radius, centre_x + radius, centre_y + radius),
            outline=self.theme.panel_border,
            width=self.px(2),
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

        throttle = float(self.timeline.throttle_percent[index])
        lateral_g = float(self.timeline.lateral_g[index])
        axial_g = float(self.timeline.axial_g[index])
        throttle_bar = Rectangle(
            self.attitude_panel.left + self.px(25),
            self.attitude_panel.top + self.px(75),
            self.attitude_panel.left + self.px(39),
            self.attitude_panel.bottom - self.px(28),
        )
        draw.rounded_rectangle(
            throttle_bar.as_box(),
            radius=self.px(5),
            outline=self.theme.primary,
            width=self.px(2),
        )
        throttle_inner = throttle_bar.inset(self.px(4))
        throttle_top = round(throttle_inner.bottom - throttle_inner.height * throttle / 100.0)
        if throttle_top < throttle_inner.bottom:
            draw.rounded_rectangle(
                (throttle_inner.left, throttle_top, throttle_inner.right, throttle_inner.bottom),
                radius=self.px(2),
                fill=self.theme.accent,
            )

        value_x = self.attitude_panel.left + self.px(207)
        draw.text(
            (value_x, self.attitude_panel.top + self.px(75)),
            f"{throttle:.0f}%",
            font=_font(self.px(28), bold=True),
            fill=self.theme.primary,
            anchor="la",
        )
        draw.text(
            (self.attitude_panel.right - self.px(20), self.attitude_panel.top + self.px(88)),
            "THROTTLE",
            font=_font(self.px(14), bold=True),
            fill=self.theme.secondary,
            anchor="ra",
        )
        draw.text(
            (value_x, self.attitude_panel.top + self.px(125)),
            f"{lateral_g:+.1f}G",
            font=_font(self.px(26), bold=True),
            fill=self.theme.primary,
            anchor="la",
        )
        draw.text(
            (self.attitude_panel.right - self.px(20), self.attitude_panel.top + self.px(138)),
            "LATERAL",
            font=_font(self.px(14), bold=True),
            fill=self.theme.secondary,
            anchor="ra",
        )
        draw.text(
            (value_x, self.attitude_panel.top + self.px(175)),
            f"{axial_g:+.1f}G",
            font=_font(self.px(26), bold=True),
            fill=self.theme.primary,
            anchor="la",
        )
        draw.text(
            (self.attitude_panel.right - self.px(20), self.attitude_panel.top + self.px(188)),
            "AXIAL",
            font=_font(self.px(14), bold=True),
            fill=self.theme.secondary,
            anchor="ra",
        )

    def _draw_battery_fuel(self, draw: ImageDraw.ImageDraw, index: int) -> None:
        battery_percent = float(self.timeline.battery_percent[index])
        fuel_remaining = float(self.timeline.fuel_remaining_litres[index])
        fuel_fraction = max(
            0.0,
            min(1.0, fuel_remaining / max(self.timeline.fuel_initial_litres, 1e-9)),
        )
        panel = self.resource_panel
        battery_centre = panel.left + self.px(65)
        fuel_centre = panel.right - self.px(65)
        icon_top = panel.top + self.px(65)
        icon_bottom = panel.top + self.px(137)
        outline_width = self.px(3)

        battery_box = Rectangle(
            battery_centre - self.px(24),
            icon_top,
            battery_centre + self.px(24),
            icon_bottom,
        )
        draw.rounded_rectangle(
            battery_box.as_box(),
            radius=self.px(7),
            outline=self.theme.primary,
            width=outline_width,
        )
        draw.rounded_rectangle(
            (
                battery_centre - self.px(10),
                icon_top - self.px(8),
                battery_centre + self.px(10),
                icon_top + self.px(1),
            ),
            radius=self.px(2),
            fill=self.theme.primary,
        )
        inner = battery_box.inset(self.px(7))
        fill_top = round(inner.bottom - inner.height * battery_percent / 100.0)
        if fill_top < inner.bottom:
            draw.rounded_rectangle(
                (inner.left, fill_top, inner.right, inner.bottom),
                radius=self.px(3),
                fill=self.theme.accent,
            )
        for segment in range(1, self.timeline.battery_cell_count):
            y = round(inner.top + inner.height * segment / self.timeline.battery_cell_count)
            draw.line(
                (inner.left, y, inner.right, y),
                fill=self.theme.panel_fill,
                width=self.px(3),
            )

        fuel_box = Rectangle(
            fuel_centre - self.px(25),
            icon_top,
            fuel_centre + self.px(25),
            icon_bottom,
        )
        draw.rounded_rectangle(
            fuel_box.as_box(),
            radius=self.px(8),
            outline=self.theme.primary,
            width=outline_width,
        )
        fuel_inner = fuel_box.inset(self.px(7))
        fuel_fill_top = round(fuel_inner.bottom - fuel_inner.height * fuel_fraction)
        if fuel_fill_top < fuel_inner.bottom:
            draw.rounded_rectangle(
                (fuel_inner.left, fuel_fill_top, fuel_inner.right, fuel_inner.bottom),
                radius=self.px(3),
                fill=self.theme.accent,
            )

        value_y = panel.bottom - self.px(25)
        draw.text(
            (battery_centre, value_y),
            f"{battery_percent:.0f}%",
            font=_font(self.px(22), bold=True),
            fill=self.theme.primary,
            anchor="mm",
        )
        draw.text(
            (fuel_centre, value_y),
            f"{fuel_remaining:.2f} L",
            font=_font(self.px(22), bold=True),
            fill=self.theme.primary,
            anchor="mm",
        )

    def _draw_timer(self, draw: ImageDraw.ImageDraw, index: int) -> None:
        elapsed = index / self.config.fps
        total_seconds = round(elapsed)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        draw.text(
            (self.timer_panel.right - self.px(18), self.timer_panel.top + self.px(15)),
            f"T+ {hours:02d}:{minutes:02d}:{seconds:02d}",
            font=_font(self.px(26), bold=True),
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
        self._draw_path(image, index)
        self._draw_attitude(image, draw, index)
        self._draw_battery_fuel(draw, index)
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

    def render_alpha_matte(
        self,
        index: int,
        overlay: Image.Image | None = None,
    ) -> Image.Image:
        """Render the exact per-frame alpha channel as an RGB luma matte."""
        if not 0 <= index < self.timeline.frame_count:
            raise IndexError(f"frame index {index} is outside the telemetry timeline")
        source = overlay if overlay is not None else self.render_overlay(index)
        alpha = source.getchannel("A")
        return Image.merge("RGB", (alpha, alpha, alpha))

    def render_static_blur_matte(self) -> Image.Image:
        """Render the full-strength feathered panel mask as a still image."""
        return Image.merge("RGB", (self.static_matte,) * 3)

"""Overlay render configuration and visual themes."""

from __future__ import annotations

from dataclasses import dataclass, replace

RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class Theme:
    """Colours used by the broadcast renderer."""

    name: str
    panel_fill: RGBA
    panel_border: RGBA
    primary: RGBA
    secondary: RGBA
    accent: RGBA
    shadow: RGBA


THEMES = {
    "orbital": Theme(
        name="orbital",
        panel_fill=(7, 14, 22, 166),
        panel_border=(210, 232, 245, 58),
        primary=(244, 249, 252, 255),
        secondary=(157, 177, 190, 235),
        accent=(91, 214, 255, 255),
        shadow=(0, 0, 0, 115),
    ),
    "minimal": Theme(
        name="minimal",
        panel_fill=(15, 17, 20, 148),
        panel_border=(255, 255, 255, 48),
        primary=(255, 255, 255, 255),
        secondary=(185, 188, 192, 235),
        accent=(255, 255, 255, 255),
        shadow=(0, 0, 0, 100),
    ),
}


def parse_hex_colour(value: str) -> RGBA:
    """Parse a CSS-style RGB hex colour and make it fully opaque."""
    cleaned = value.removeprefix("#")
    if len(cleaned) != 6:
        raise ValueError("accent colour must use the format #RRGGBB")
    try:
        red, green, blue = (int(cleaned[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError as error:
        raise ValueError("accent colour must use the format #RRGGBB") from error
    return red, green, blue, 255


def get_theme(name: str, accent: str | None = None) -> Theme:
    """Return a named theme, optionally with a custom accent colour."""
    try:
        theme = THEMES[name]
    except KeyError as error:
        choices = ", ".join(sorted(THEMES))
        raise ValueError(f"unknown theme {name!r}; choose from {choices}") from error
    return replace(theme, accent=parse_hex_colour(accent)) if accent else theme


@dataclass(frozen=True)
class RenderConfig:
    """Resolution, timing, units and presentation settings."""

    width: int = 1920
    height: int = 1080
    fps: int = 30
    title: str = "FLIGHT TELEMETRY"
    units: str = "imperial"
    trail_seconds: float = 12.0
    fade_seconds: float = 0.6

    def __post_init__(self) -> None:
        if self.width < 640 or self.height < 360:
            raise ValueError("overlay resolution must be at least 640x360")
        if self.width % 2 or self.height % 2:
            raise ValueError("overlay width and height must be even numbers")
        if self.fps <= 0:
            raise ValueError("fps must be greater than zero")
        if self.units not in {"imperial", "metric"}:
            raise ValueError("units must be either 'imperial' or 'metric'")
        if self.trail_seconds <= 0:
            raise ValueError("trail duration must be greater than zero")
        if self.fade_seconds < 0:
            raise ValueError("fade duration cannot be negative")
        if not self.title.strip():
            raise ValueError("overlay title cannot be empty")

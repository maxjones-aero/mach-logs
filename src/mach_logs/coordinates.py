"""Geographic coordinate helpers."""

from __future__ import annotations

import math

EARTH_RADIUS_METRES = 6_378_137.0


def _validate_coordinate(value: float, *, name: str, lower: float, upper: float) -> None:
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{name} must be a finite value between {lower} and {upper} degrees")


def latlon_to_xy(
    lat: float,
    lon: float,
    ref_lat: float,
    ref_lon: float,
) -> tuple[float, float]:
    """Convert decimal-degree coordinates to local X/Y offsets in metres.

    The equirectangular approximation is appropriate for the short distances
    normally covered by a single flight log. All inputs are decimal degrees,
    not MAVLink's occasionally used degrees-times-1e7 integer representation.
    """
    _validate_coordinate(lat, name="latitude", lower=-90.0, upper=90.0)
    _validate_coordinate(lon, name="longitude", lower=-180.0, upper=180.0)
    _validate_coordinate(ref_lat, name="reference latitude", lower=-90.0, upper=90.0)
    _validate_coordinate(ref_lon, name="reference longitude", lower=-180.0, upper=180.0)

    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    ref_lat_rad = math.radians(ref_lat)
    ref_lon_rad = math.radians(ref_lon)

    delta_lat = lat_rad - ref_lat_rad
    delta_lon = lon_rad - ref_lon_rad
    x = EARTH_RADIUS_METRES * delta_lon * math.cos((lat_rad + ref_lat_rad) / 2)
    y = EARTH_RADIUS_METRES * delta_lat
    return x, y


def dms_to_decimal(degrees: float, minutes: float, seconds: float) -> float:
    """Convert conventional DMS coordinates to decimal degrees.

    Put the sign on ``degrees`` only; minutes and seconds must be positive.
    For example, 3° 12' 30" west is ``dms_to_decimal(-3, 12, 30)``.
    """
    if not 0 <= minutes < 60:
        raise ValueError("minutes must be between 0 (inclusive) and 60 (exclusive)")
    if not 0 <= seconds < 60:
        raise ValueError("seconds must be between 0 (inclusive) and 60 (exclusive)")

    sign = -1 if degrees < 0 else 1
    return sign * (abs(degrees) + minutes / 60 + seconds / 3600)

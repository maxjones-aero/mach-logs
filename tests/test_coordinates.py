import math

import pytest

from mach_logs.coordinates import dms_to_decimal, latlon_to_xy


def test_dms_to_decimal_applies_degree_sign_to_whole_coordinate():
    assert dms_to_decimal(-3, 12, 30) == pytest.approx(-3.2083333)
    assert dms_to_decimal(48, 30, 0) == pytest.approx(48.5)


@pytest.mark.parametrize(("minutes", "seconds"), [(60, 0), (-1, 0), (0, 60), (0, -1)])
def test_dms_to_decimal_rejects_invalid_subdivisions(minutes, seconds):
    with pytest.raises(ValueError):
        dms_to_decimal(1, minutes, seconds)


def test_reference_coordinate_maps_to_origin():
    assert latlon_to_xy(48.0, -3.0, 48.0, -3.0) == pytest.approx((0.0, 0.0))


def test_latitude_offset_is_measured_in_metres():
    _, northing = latlon_to_xy(48.001, -3.0, 48.0, -3.0)
    assert math.isclose(northing, 111.319, rel_tol=0.001)


def test_coordinate_range_is_validated():
    with pytest.raises(ValueError, match="latitude"):
        latlon_to_xy(480000000, -3.0, 48.0, -3.0)

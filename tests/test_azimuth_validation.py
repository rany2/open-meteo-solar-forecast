"""Tests for azimuth range validation."""

# ruff: noqa: S101

import unittest

import pytest

from open_meteo_solar_forecast import OpenMeteoSolarForecast
from open_meteo_solar_forecast.exceptions import OpenMeteoSolarForecastConfigError


def _forecast(azimuth: float | list[float]) -> OpenMeteoSolarForecast:
    return OpenMeteoSolarForecast(
        azimuth=azimuth,
        declination=20,
        dc_kwp=2.0,
        latitude=52.16,
        longitude=4.47,
    )


class AzimuthValidationTests(unittest.TestCase):
    """Reject azimuth values outside the Open-Meteo [-180, 180] convention."""

    def test_compass_bearing_is_rejected_with_conversion_hint(self) -> None:
        """A compass west bearing (270) fails at construction, not request time."""
        with pytest.raises(OpenMeteoSolarForecastConfigError) as exc_info:
            _forecast(270)

        message = str(exc_info.value)
        assert "270" in message
        assert "subtract 180" in message

    def test_out_of_range_list_value_is_rejected(self) -> None:
        """Per-array azimuth values are validated too."""
        with pytest.raises(OpenMeteoSolarForecastConfigError):
            _forecast([-90, 270])

    def test_open_meteo_range_is_accepted(self) -> None:
        """Boundary and in-range values construct without error."""
        for azimuth in (-180, -90, 0, 90, 180):
            _forecast(azimuth)

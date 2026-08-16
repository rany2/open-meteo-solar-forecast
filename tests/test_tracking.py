"""Tests for solar tracker configuration."""

# ruff: noqa: S101

import unittest

from open_meteo_solar_forecast import OpenMeteoSolarForecast
from open_meteo_solar_forecast.exceptions import OpenMeteoSolarForecastConfigError


class TrackingConfigTests(unittest.TestCase):
    """Verify tracking parameter validation and normalization."""

    def test_default_and_per_array_tracking(self) -> None:
        """Normalize tracking like other per-array parameters."""
        forecast = OpenMeteoSolarForecast(
            latitude=[48.0, 48.0],
            longitude=[11.0, 11.0],
            declination=[20, 30],
            azimuth=[0, 0],
            dc_kwp=[1.0, 2.0],
        )
        assert forecast.tracking == ["none", "none"]

        forecast = OpenMeteoSolarForecast(
            latitude=[48.0, 48.0],
            longitude=[11.0, 11.0],
            declination=[20, 30],
            azimuth=[0, 0],
            dc_kwp=[1.0, 2.0],
            tracking=["none", "dual"],
        )
        assert forecast.tracking == ["none", "dual"]

    def test_invalid_tracking_rejected(self) -> None:
        """Reject tracking values the API does not support."""
        with self.assertRaises(OpenMeteoSolarForecastConfigError):
            OpenMeteoSolarForecast(
                latitude=48.0,
                longitude=11.0,
                declination=20,
                azimuth=0,
                dc_kwp=1.0,
                tracking="bogus",
            )


if __name__ == "__main__":
    unittest.main()

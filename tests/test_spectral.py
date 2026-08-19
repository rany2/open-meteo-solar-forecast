"""Tests for spectral mismatch correction and snow-aware ground albedo."""

# ruff: noqa: S101

import unittest

import numpy as np
import pandas as pd

from open_meteo_solar_forecast import OpenMeteoSolarForecast
from open_meteo_solar_forecast.constants import (
    SNOW_ALBEDO_DEPTH_M,
    SNOW_GROUND_ALBEDO,
)
from open_meteo_solar_forecast.spectral import spectral_factor


def _airmass(values) -> pd.Series:
    return pd.Series(values, dtype=float)


class SpectralFactorTests(unittest.TestCase):
    """Verify the spectral mismatch factor."""

    def test_typical_conditions_are_near_unity(self) -> None:
        """Stay close to no correction under ordinary conditions."""
        factor = spectral_factor([20.0], [50.0], [1013.25], _airmass([1.5]))
        assert 0.95 < factor[0] < 1.05

    def test_factor_rises_with_water_vapour(self) -> None:
        """Increase with humidity, as the Lee and Panchula fit does for silicon.

        Verified against pvlib: monosi runs 0.985 at 0.37 cm of precipitable
        water up to 1.003 at 3.55 cm. Note this is the opposite of the naive
        expectation that near-infrared absorption should penalise silicon.
        """
        dry = spectral_factor([20.0], [10.0], [1013.25], _airmass([1.5]))[0]
        humid = spectral_factor([20.0], [95.0], [1013.25], _airmass([1.5]))[0]
        assert humid > dry

    def test_factor_rises_with_airmass(self) -> None:
        """Increase as the light path lengthens."""
        low = spectral_factor([20.0], [50.0], [1013.25], _airmass([1.0]))[0]
        high = spectral_factor([20.0], [50.0], [1013.25], _airmass([4.0]))[0]
        assert high > low

    def test_correction_stays_small_for_silicon(self) -> None:
        """Keep the correction modest across realistic conditions.

        A large spectral swing would indicate the inputs or units are wrong.
        """
        factors = spectral_factor(
            [-5.0, 5.0, 20.0, 35.0] * 3,
            [20.0, 50.0, 80.0, 95.0] * 3,
            [1013.25] * 12,
            _airmass([1.0] * 4 + [2.0] * 4 + [4.0] * 4),
        )
        assert np.all(np.abs(factors - 1.0) < 0.06)

    def test_altitude_is_accounted_for(self) -> None:
        """Use pressure so airmass is absolute rather than relative.

        At 1600 m the air is thinner, so the same relative airmass is less
        absolute airmass.
        """
        sea = spectral_factor([15.0], [50.0], [1013.25], _airmass([2.0]))[0]
        alt = spectral_factor([15.0], [50.0], [835.0], _airmass([2.0]))[0]
        assert sea != alt

    def test_output_is_bounded(self) -> None:
        """Clamp implausible corrections from extreme inputs."""
        factor = spectral_factor(
            [-40.0, 50.0, 15.0, 15.0],
            [0.0, 100.0, 50.0, 50.0],
            [500.0, 1100.0, 1013.25, 1013.25],
            _airmass([0.1, 40.0, 1.0, 1.0]),
        )
        assert np.all(factor >= 0.8)
        assert np.all(factor <= 1.2)

    def test_no_nan_leaks_through(self) -> None:
        """Fall back to no correction outside the model's fitted range."""
        factor = spectral_factor(
            [15.0] * 3, [50.0] * 3, [1013.25] * 3, _airmass([0.0, 1e6, np.nan])
        )
        assert np.isfinite(factor).all()

    def test_length_is_preserved(self) -> None:
        """Return one factor per timestep."""
        n = 25
        factor = spectral_factor(
            [15.0] * n, [60.0] * n, [1000.0] * n, _airmass(np.linspace(1, 6, n))
        )
        assert len(factor) == n


class SnowAlbedoTests(unittest.TestCase):
    """Verify ground albedo responds to lying snow."""

    @staticmethod
    def _weather(snow_depth):
        n = len(snow_depth)
        forecast = OpenMeteoSolarForecast(
            latitude=60.0, longitude=10.0, declination=45, azimuth=0, dc_kwp=5.0
        )
        minutely = {"time": [i * 900 for i in range(n)]}
        for var in forecast.MINUTELY_15_VARS:
            minutely[var] = [0.0] * n
        minutely["snow_depth"] = list(snow_depth)
        minutely["temperature_2m"] = [-2.0] * n
        minutely["relative_humidity_2m"] = [80.0] * n
        minutely["surface_pressure"] = [1013.25] * n
        return forecast, minutely

    def test_bare_ground_is_not_flagged(self) -> None:
        """Leave albedo alone when there is no snow."""
        forecast, minutely = self._weather([0.0, 0.0, 0.0, 0.0])
        data = {"utc_offset_seconds": 0, "minutely_15": minutely}
        import datetime as dt

        weather = forecast._prepare_weather(data, dt.timezone.utc)  # noqa: SLF001
        assert not weather["ground_is_snowy"].any()

    def test_deep_snow_is_flagged(self) -> None:
        """Flag snow-covered ground so albedo can be raised."""
        forecast, minutely = self._weather([0.30] * 4)
        data = {"utc_offset_seconds": 0, "minutely_15": minutely}
        import datetime as dt

        weather = forecast._prepare_weather(data, dt.timezone.utc)  # noqa: SLF001
        assert weather["ground_is_snowy"].all()

    def test_threshold_is_respected(self) -> None:
        """Ignore a dusting too thin to change the ground's reflectance."""
        below = SNOW_ALBEDO_DEPTH_M / 2
        above = SNOW_ALBEDO_DEPTH_M * 2
        forecast, minutely = self._weather([below, above, below, above])
        data = {"utc_offset_seconds": 0, "minutely_15": minutely}
        import datetime as dt

        weather = forecast._prepare_weather(data, dt.timezone.utc)  # noqa: SLF001
        assert list(weather["ground_is_snowy"]) == [False, True, False, True]

    def test_snow_albedo_exceeds_default_ground(self) -> None:
        """Keep snow more reflective than the default ground assumption."""
        default_albedo = 0.25
        assert SNOW_GROUND_ALBEDO > default_albedo
        assert SNOW_GROUND_ALBEDO <= 1.0


if __name__ == "__main__":
    unittest.main()

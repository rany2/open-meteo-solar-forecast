"""Tests for per-array inverter (AC) capacity support."""

# ruff: noqa: S101

import unittest
from datetime import datetime, timezone

from open_meteo_solar_forecast import OpenMeteoSolarForecast
from open_meteo_solar_forecast.exceptions import OpenMeteoSolarForecastConfigError


def _make_forecast(**kwargs) -> OpenMeteoSolarForecast:
    """Create a two-array forecast object with sensible defaults."""
    defaults = {
        "latitude": 48.0,
        "longitude": 11.0,
        "declination": [0, 0],
        "azimuth": [0, 0],
        "dc_kwp": [2.0, 2.0],
    }
    defaults.update(kwargs)
    return OpenMeteoSolarForecast(**defaults)


class AcKwpConfigTests(unittest.TestCase):
    """Verify ac_kwp validation and normalization."""

    def test_default_is_shared_and_unlimited(self) -> None:
        """Default to a shared inverter with unlimited capacity."""
        forecast = _make_forecast()
        assert forecast.shared_inverter is True
        assert forecast.ac_kwp == [float("inf"), float("inf")]

    def test_scalar_is_shared_inverter(self) -> None:
        """Interpret a scalar as one inverter shared by all arrays."""
        forecast = _make_forecast(ac_kwp=3.0)
        assert forecast.shared_inverter is True
        assert forecast.ac_kwp == [3.0, 3.0]

    def test_list_is_per_array_inverters(self) -> None:
        """Interpret a list as one inverter per array."""
        forecast = _make_forecast(ac_kwp=[1.5, 2.5])
        assert forecast.shared_inverter is False
        assert forecast.ac_kwp == [1.5, 2.5]

    def test_none_entry_means_unlimited(self) -> None:
        """Allow None entries for arrays without an inverter limit."""
        forecast = _make_forecast(ac_kwp=[1.5, None])
        assert forecast.shared_inverter is False
        assert forecast.ac_kwp == [1.5, float("inf")]

    def test_length_mismatch_rejected(self) -> None:
        """Reject ac_kwp lists that do not match the number of arrays."""
        with self.assertRaises(OpenMeteoSolarForecastConfigError):
            _make_forecast(ac_kwp=[1.0, 2.0, 3.0])

    def test_non_positive_rejected(self) -> None:
        """Reject zero or negative inverter capacities."""
        with self.assertRaises(OpenMeteoSolarForecastConfigError):
            _make_forecast(ac_kwp=0.0)
        with self.assertRaises(OpenMeteoSolarForecastConfigError):
            _make_forecast(ac_kwp=[1.0, -2.0])


def _fake_api_data() -> dict:
    """Build a minimal API response producing high output per 2 kWp array."""
    tz = timezone.utc
    t0 = int(datetime(2026, 8, 14, 12, 0, tzinfo=tz).timestamp())
    t1 = t0 + 900
    # Pure diffuse irradiance on a horizontal plane (tilt 0) gives a GTI
    # close to 1000 W/m² (G_STC) reduced only by diffuse IAM reflection
    # losses, so each 2 kWp array produces roughly (but not exactly) 2 kW.
    # A cool ambient temperature keeps the Faiman cell temperature near STC.
    t_amb = -9.2
    return {
        "utc_offset_seconds": 0,
        "minutely_15": {
            "time": [t0, t1],
            "shortwave_radiation": [1000.0, 1000.0],
            "shortwave_radiation_instant": [1000.0, 1000.0],
            "diffuse_radiation": [1000.0, 1000.0],
            "diffuse_radiation_instant": [1000.0, 1000.0],
            "direct_normal_irradiance": [0.0, 0.0],
            "direct_normal_irradiance_instant": [0.0, 0.0],
            "snow_depth": [0.0, 0.0],
            "temperature_2m": [t_amb, t_amb],
            "wind_speed_10m": [1.0, 1.0],
        },
    }


class AcKwpClampTests(unittest.IsolatedAsyncioTestCase):
    """Verify inverter clamping behaviour in estimate()."""

    @staticmethod
    async def _estimate_total(forecast: OpenMeteoSolarForecast) -> float:
        async def fake_request(uri, *, params=None):  # noqa: ARG001
            return _fake_api_data()

        forecast._request = fake_request  # noqa: SLF001
        estimate = await forecast.estimate()
        assert len(estimate.watts) == 1
        return next(iter(estimate.watts.values()))

    async def _per_array_baseline(self) -> float:
        """Return the unclamped output of a single array."""
        total = await self._estimate_total(_make_forecast())
        return total / 2

    async def test_no_inverter_limit(self) -> None:
        """Sum both arrays without clamping when no capacity is set."""
        total = await self._estimate_total(_make_forecast())
        # Each 2 kWp array produces near-STC output, reduced by diffuse IAM
        # reflection losses and the Faiman cell temperature model.
        assert 3000 < total < 4000

    async def test_shared_inverter_clamps_combined_output(self) -> None:
        """Clamp the combined output to a shared inverter's capacity."""
        total = await self._estimate_total(_make_forecast(ac_kwp=1.0))
        assert total == 1000

    async def test_per_array_inverters_clamp_individually(self) -> None:
        """Clamp each array to its own inverter capacity before summing."""
        # Array 1 clamped to 1000 W, array 2 (~1900 W) unclamped.
        baseline = await self._per_array_baseline()
        total = await self._estimate_total(_make_forecast(ac_kwp=[1.0, 3.0]))
        assert total == 1000 + baseline

    async def test_per_array_none_entry_is_unlimited(self) -> None:
        """Leave arrays with a None capacity unclamped."""
        baseline = await self._per_array_baseline()
        total = await self._estimate_total(_make_forecast(ac_kwp=[1.0, None]))
        assert total == 1000 + baseline


if __name__ == "__main__":
    unittest.main()

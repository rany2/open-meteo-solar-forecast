"""Tests for missing (None) values in the API response (issue #55)."""

# ruff: noqa: S101

import unittest

from open_meteo_solar_forecast import OpenMeteoSolarForecast

from .test_ac_kwp import _fake_api_data


def _make_forecast(**kwargs) -> OpenMeteoSolarForecast:
    """Create a single-array forecast object with sensible defaults."""
    defaults = {
        "latitude": 48.0,
        "longitude": 11.0,
        "declination": 20,
        "azimuth": 0,
        "dc_kwp": 2.0,
    }
    defaults.update(kwargs)
    return OpenMeteoSolarForecast(**defaults)


class MissingValueTests(unittest.IsolatedAsyncioTestCase):
    """Verify that missing optional values do not break estimate()."""

    @staticmethod
    async def _estimate_total(forecast: OpenMeteoSolarForecast, data: dict) -> float:
        async def fake_request(uri, *, params=None):  # noqa: ARG001
            return data

        forecast._request = fake_request  # noqa: SLF001
        estimate = await forecast.estimate()
        assert len(estimate.watts) == 1
        return next(iter(estimate.watts.values()))

    async def test_missing_snow_depth_is_treated_as_no_snow(self) -> None:
        """Treat a None snow depth as 0 cm when snow correction is enabled."""
        data = _fake_api_data()
        data["minutely_15"]["snow_depth"] = [None, None]
        total = await self._estimate_total(
            _make_forecast(max_snowcover_depth_cm=5.0), data
        )
        assert total == 2000

    async def test_snow_depth_still_reduces_output(self) -> None:
        """Keep the snow correction working for real snow depth values."""
        data = _fake_api_data()
        data["minutely_15"]["snow_depth"] = [0.025, 0.025]  # 2.5 cm
        total = await self._estimate_total(
            _make_forecast(max_snowcover_depth_cm=5.0), data
        )
        # Half the irradiance; slightly more than half the power because the
        # cell runs cooler at lower irradiance.
        assert 1000 <= total < 1100

    async def test_missing_diffuse_and_direct_values(self) -> None:
        """Do not fail when diffuse/direct components are None."""
        data = _fake_api_data()
        for key in (
            "diffuse_radiation",
            "diffuse_radiation_instant",
            "direct_radiation",
            "direct_radiation_instant",
        ):
            data["minutely_15"][key] = [None, None]
        total = await self._estimate_total(
            _make_forecast(), data
        )
        assert total == 2000


if __name__ == "__main__":
    unittest.main()

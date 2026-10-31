"""Missing optional weather values must not abort an entire forecast."""

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from open_meteo_solar_forecast import OpenMeteoSolarForecast


def weather_data() -> dict:
    """Return three intervals with consistent daylight weather."""
    start = int(datetime(2026, 6, 1, 12, tzinfo=UTC).timestamp())
    return {
        "utc_offset_seconds": 0,
        "minutely_15": {
            "time": [start + 900 * i for i in range(4)],
            "temperature_2m": [20.0] * 4,
            "global_tilted_irradiance": [500.0] * 4,
            "global_tilted_irradiance_instant": [500.0] * 4,
            "diffuse_radiation": [100.0] * 4,
            "diffuse_radiation_instant": [100.0] * 4,
            "direct_radiation": [400.0] * 4,
            "direct_radiation_instant": [400.0] * 4,
            "snow_depth": [0.0] * 4,
        },
        "daily": {
            "time": [start - 12 * 3600],
            "sunrise": [start - 6 * 3600],
            "sunset": [start + 6 * 3600],
        },
    }


class MissingWeatherTests(unittest.IsolatedAsyncioTestCase):
    """Exercise missing data through the full estimate calculation."""

    async def estimate(self, data: dict, **options):
        """Calculate a forecast without making network requests."""
        forecast = OpenMeteoSolarForecast(
            latitude=50,
            longitude=10,
            azimuth=0,
            declination=25,
            dc_kwp=1,
            **options,
        )
        with patch.object(forecast, "_request", AsyncMock(return_value=data)):
            return await forecast.estimate()

    async def test_missing_snow_preserves_other_intervals(self):
        data = weather_data()
        baseline = await self.estimate(data, max_snowcover_depth_cm=5)
        data["minutely_15"]["snow_depth"] = [0.0, None, 0.025, 0.05]
        result = await self.estimate(data, max_snowcover_depth_cm=5)
        periods = list(result.wh_period_15m.values())
        self.assertEqual(periods[0], next(iter(baseline.wh_period_15m.values())))
        self.assertGreater(periods[1], 0)
        self.assertLess(periods[1], periods[0])
        self.assertEqual(periods[2], 0)

    async def test_missing_shading_input_skips_only_affected_interval(self):
        for partial, fields in (
            (False, ("diffuse_radiation", "diffuse_radiation_instant")),
            (
                True,
                (
                    "diffuse_radiation",
                    "diffuse_radiation_instant",
                    "direct_radiation",
                    "direct_radiation_instant",
                ),
            ),
        ):
            for field in fields:
                with self.subTest(partial=partial, field=field):
                    data = weather_data()
                    options = dict(
                        use_horizon=True,
                        partial_shading=partial,
                        horizon_map=((0.0, 90.0), (360.0, 90.0)),
                    )
                    baseline = await self.estimate(data, **options)
                    data["minutely_15"][field][2] = None
                    result = await self.estimate(data, **options)
                    expected = dict(baseline.wh_period_15m)
                    expected.pop(list(expected)[1])
                    self.assertEqual(result.wh_period_15m, expected)

    async def test_unused_radiation_fields_can_be_missing(self):
        for options in (
            {},
            dict(
                use_horizon=True,
                partial_shading=True,
                horizon_map=((0.0, -90.0), (360.0, -90.0)),
            ),
        ):
            with self.subTest(options=options):
                data = weather_data()
                baseline = await self.estimate(data, **options)
                for field in (
                    "diffuse_radiation",
                    "diffuse_radiation_instant",
                    "direct_radiation",
                    "direct_radiation_instant",
                ):
                    data["minutely_15"][field] = [None] * 4
                result = await self.estimate(data, **options)
                self.assertEqual(result.wh_period_15m, baseline.wh_period_15m)

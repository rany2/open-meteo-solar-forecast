"""Hourly and daily totals conserve the available quarter-hour energy."""

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from open_meteo_solar_forecast import OpenMeteoSolarForecast


def weather_data(start: datetime, quarters: int) -> dict:
    """Build constant 1000 W weather, including the initial boundary sample."""
    timestamp = int(start.timestamp())
    count = quarters + 1
    midnight = int(start.replace(hour=0, minute=0).timestamp())
    return {
        "utc_offset_seconds": 0,
        "minutely_15": {
            "time": [timestamp + 900 * i for i in range(count)],
            "temperature_2m": [25 - 1000 * 0.0342] * count,
            "global_tilted_irradiance": [1000.0] * count,
            "global_tilted_irradiance_instant": [1000.0] * count,
            "diffuse_radiation": [0.0] * count,
            "diffuse_radiation_instant": [0.0] * count,
            "direct_radiation": [1000.0] * count,
            "direct_radiation_instant": [1000.0] * count,
            "snow_depth": [0.0] * count,
        },
        "daily": {
            "time": [midnight, midnight + 86400],
            "sunrise": [midnight + 21600, midnight + 108000],
            "sunset": [midnight + 64800, midnight + 151200],
        },
    }


class HourlyEnergyTests(unittest.IsolatedAsyncioTestCase):
    """Check actual estimate output for short hours, gaps and midnight."""

    async def estimate(self, data: dict, **options):
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

    async def test_partial_and_complete_hours(self):
        start = datetime(2026, 6, 1, 12, tzinfo=UTC)
        for count in range(1, 5):
            with self.subTest(count=count):
                result = await self.estimate(weather_data(start, count))
                self.assertEqual(result.wh_period[start], 250 * count)
                self.assertEqual(sum(result.wh_days.values()), 250 * count)
                self.assertEqual(sum(result.wh_period_15m.values()), 250 * count)

    async def test_missing_quarter_is_not_scaled_to_full_hour(self):
        start = datetime(2026, 6, 1, 12, tzinfo=UTC)
        data = weather_data(start, 4)
        data["minutely_15"]["global_tilted_irradiance"][2] = None
        result = await self.estimate(data)
        self.assertEqual(result.wh_period[start], 750)
        self.assertEqual(sum(result.wh_days.values()), 750)
        self.assertEqual(len(result.wh_period_15m), 3)

    async def test_clipped_energy_is_split_at_midnight(self):
        start = datetime(2026, 6, 1, 23, 45, tzinfo=UTC)
        result = await self.estimate(weather_data(start, 2), ac_kwp=0.8)
        self.assertEqual(list(result.wh_period.values()), [200, 200])
        self.assertEqual(list(result.wh_days.values()), [200, 200])
        self.assertEqual(sum(result.wh_period_15m.values()), 400)

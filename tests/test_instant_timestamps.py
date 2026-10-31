"""Instantaneous power uses the API timestamp and temperature."""

import unittest
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from open_meteo_solar_forecast import OpenMeteoSolarForecast
from tests.test_ac_kwp import _fake_api_data


class InstantTimestampTests(unittest.IsolatedAsyncioTestCase):
    """Keep instantaneous samples separate from preceding interval energy."""

    async def estimate(self, data):
        forecast = OpenMeteoSolarForecast(
            latitude=50, longitude=10, azimuth=0, declination=25, dc_kwp=1
        )
        with patch.object(forecast, "_request", AsyncMock(return_value=data)):
            return await forecast.estimate()

    async def test_power_uses_api_time_while_energy_uses_interval_start(self):
        for offset in (0, 7200, -19800):
            with self.subTest(offset=offset):
                data = _fake_api_data()
                data["utc_offset_seconds"] = offset
                for field, values in data["daily"].items():
                    data["daily"][field] = [ts - offset for ts in values]
                samples = data["minutely_15"]
                start = samples["time"][0] - offset
                for field, values in samples.items():
                    samples[field] = [values[0]] * 4
                samples["time"] = [start + 900 * i for i in range(4)]
                samples["global_tilted_irradiance_instant"] = [0, 1000, 0, 0]

                result = await self.estimate(data)
                tz = timezone(timedelta(seconds=offset))
                times = [datetime.fromtimestamp(ts, tz) for ts in samples["time"]]
                self.assertEqual(result.watts, dict(zip(times[1:], (1000, 0, 0))))
                self.assertEqual(result.peak_production_time(times[1].date()), times[1])
                self.assertEqual(result.wh_period_15m, dict.fromkeys(times[:-1], 250))

    async def test_instant_temperature_matches_instant_irradiance(self):
        data = _fake_api_data()
        data["minutely_15"]["temperature_2m"][0] += 20
        result = await self.estimate(data)
        self.assertEqual(list(result.watts.values()), [1000])
        self.assertLess(sum(result.wh_period_15m.values()), 250)

    async def test_midnight_power_belongs_to_new_day(self):
        data = _fake_api_data()
        midnight = datetime(2026, 8, 15, tzinfo=UTC)
        samples = data["minutely_15"]
        samples["time"] = [
            int((midnight - timedelta(minutes=15)).timestamp()),
            int(midnight.timestamp()),
        ]
        for values in data["daily"].values():
            values.append(values[0] + 86400)
        result = await self.estimate(data)
        self.assertEqual(result.watts, {midnight: 1000})
        self.assertEqual(result.peak_production_time(midnight.date()), midnight)
        self.assertEqual(
            result.wh_period_15m, {midnight - timedelta(minutes=15): 250}
        )

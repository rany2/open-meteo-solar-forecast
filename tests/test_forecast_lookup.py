"""Forecast lookups work with array gaps and endpoint samples."""

import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from open_meteo_solar_forecast import OpenMeteoSolarForecast
from open_meteo_solar_forecast.models import Estimate
from tests.test_ac_kwp import _fake_api_data


class ForecastLookupTests(unittest.TestCase):
    """Check chronological lookup and the bounds of instantaneous samples."""

    def test_last_sample_is_available_without_extrapolating(self):
        start = datetime(2026, 6, 1, 12, tzinfo=UTC)
        end = start + timedelta(minutes=15)
        estimate = Estimate({start: 500, end: 1000}, {}, {}, UTC)
        for time, expected in (
            (start - timedelta(seconds=1), 0),
            (start, 500),
            (end - timedelta(seconds=1), 500),
            (end, 1000),
            (end + timedelta(seconds=1), 0),
        ):
            with self.subTest(time=time):
                self.assertEqual(estimate.power_production_at_time(time), expected)

    def test_single_sample_and_empty_forecasts(self):
        start = datetime(2026, 6, 1, 12, tzinfo=UTC)
        self.assertEqual(
            Estimate({start: 1000}, {}, {}, UTC).power_production_at_time(start), 1000
        )
        self.assertEqual(Estimate({}, {}, {}, UTC).power_production_at_time(start), 0)

    def test_unordered_input_preserves_power_and_hourly_energy(self):
        start = datetime(2026, 6, 1, 12, tzinfo=UTC)
        end = start + timedelta(hours=1)
        estimate = Estimate(
            {end: 1000, start: 500},
            {end: 250, start: 125},
            {end.date() + timedelta(days=1): 250, start.date(): 125},
            UTC,
            {end: 250, start: 125},
        )
        self.assertEqual(estimate.power_production_at_time(start), 500)
        with patch.object(Estimate, "now", return_value=start):
            self.assertEqual(estimate.energy_current_hour, 125)
        for series in (
            estimate.watts, estimate.wh_period, estimate.wh_days, estimate.wh_period_15m
        ):
            self.assertEqual(list(series), sorted(series))


class MultipleArrayLookupTests(unittest.IsolatedAsyncioTestCase):
    """Exercise sparse array merging through the real forecast calculation."""

    async def test_later_array_fills_earlier_gap_without_losing_power(self):
        data = _fake_api_data()
        samples = data["minutely_15"]
        start = samples["time"][0]
        for field, values in samples.items():
            samples[field] = [values[0]] * 4
        samples["time"] = [start + 900 * i for i in range(4)]
        sparse = deepcopy(data)
        sparse["minutely_15"]["global_tilted_irradiance"][1] = None
        forecast = OpenMeteoSolarForecast(
            latitude=50, longitude=10, azimuth=0, declination=25, dc_kwp=[1, 1]
        )
        for responses in ([sparse, data], [data, sparse]):
            with self.subTest(sparse_first=responses[0] is sparse):
                with patch.object(forecast, "_request", AsyncMock(side_effect=responses)):
                    result = await forecast.estimate()
                first = min(result.watts)
                self.assertEqual(result.watts[first], 1000)
                self.assertEqual(result.power_production_at_time(first), 1000)
                self.assertEqual(list(result.watts.values()), [1000, 2000, 2000])
                self.assertEqual(list(result.wh_period_15m.values()), [250, 500, 500])
                self.assertEqual(list(result.watts), sorted(result.watts))
                self.assertEqual(list(result.wh_period_15m), sorted(result.wh_period_15m))

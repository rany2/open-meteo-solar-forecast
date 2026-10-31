"""Remaining energy includes the unfinished part of the current interval."""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from open_meteo_solar_forecast import OpenMeteoSolarForecast
from open_meteo_solar_forecast.models import Estimate, _interval_value_sum_w_to_wh
from tests.test_ac_kwp import _fake_api_data


class RemainingEnergyTests(unittest.TestCase):
    """Check interval overlap, boundaries and gaps."""

    def setUp(self):
        self.start = datetime(2026, 6, 1, 12, tzinfo=UTC)
        self.data = {
            self.start: 1000,
            self.start + timedelta(minutes=15): 1000,
            self.start + timedelta(minutes=30): 0,
        }

    def test_today_remaining_includes_current_quarter(self):
        estimate = Estimate(self.data, {}, {}, UTC)
        with patch.object(
            Estimate, "now", return_value=self.start + timedelta(minutes=1)
        ):
            self.assertAlmostEqual(
                estimate.energy_production_today_remaining, 1000 * 29 / 60
            )

    def test_boundaries_and_partial_end(self):
        for begin, end, expected in (
            (0, 30, 500),
            (15, 30, 250),
            (1, 14, 1000 * 13 / 60),
            (-15, 15, 250),
            (30, 60, 0),
            (15, 15, 0),
        ):
            with self.subTest(begin=begin, end=end):
                self.assertAlmostEqual(
                    _interval_value_sum_w_to_wh(
                        self.start + timedelta(minutes=begin),
                        self.start + timedelta(minutes=end),
                        self.data,
                    ),
                    expected,
                )

    def test_gap_and_last_sample_are_not_extrapolated(self):
        data = {self.start + timedelta(hours=1): 1000, self.start: 1000}
        self.assertEqual(
            _interval_value_sum_w_to_wh(
                self.start, self.start + timedelta(hours=2), data
            ),
            500,
        )

    def test_midnight_limits_remaining_energy(self):
        start = self.start.replace(hour=23, minute=45)
        estimate = Estimate({start: 1200}, {}, {}, UTC)
        with patch.object(Estimate, "now", return_value=start + timedelta(minutes=5)):
            self.assertEqual(estimate.energy_production_today_remaining, 200)

    def test_empty_series(self):
        self.assertEqual(
            _interval_value_sum_w_to_wh(
                self.start, self.start + timedelta(hours=1), {}
            ),
            0,
        )

    def test_interval_energy_takes_precedence_over_instantaneous_power(self):
        estimate = Estimate(
            {self.start: 0},
            {},
            {},
            UTC,
            {
                self.start: 250,
                self.start + timedelta(minutes=15): 125,
                self.start + timedelta(minutes=30): 0,
            },
        )
        with patch.object(
            Estimate, "now", return_value=self.start + timedelta(minutes=5)
        ):
            self.assertAlmostEqual(
                estimate.energy_production_today_remaining, 250 * 2 / 3 + 125
            )

    def test_zero_interval_energy_does_not_fall_back_to_instantaneous_power(self):
        estimate = Estimate({self.start: 1000}, {}, {}, UTC, {self.start: 0})
        with patch.object(Estimate, "now", return_value=self.start):
            self.assertEqual(estimate.energy_production_today_remaining, 0)

    def test_interval_energy_gaps_boundaries_and_midnight(self):
        start = self.start.replace(hour=23)
        midnight = start + timedelta(hours=1)
        periods = {
            midnight: 1000,
            start + timedelta(minutes=45): 300,
            start: 150,
        }
        estimate = Estimate({start: 0}, {}, {}, UTC, periods)
        for time, expected in (
            (start, 450),
            (start + timedelta(minutes=5), 400),
            (start + timedelta(minutes=15), 300),
            (start + timedelta(minutes=30), 300),
            (start + timedelta(minutes=50), 200),
            (midnight + timedelta(minutes=15), 0),
        ):
            with self.subTest(time=time):
                with patch.object(Estimate, "now", return_value=time):
                    self.assertAlmostEqual(
                        estimate.energy_production_today_remaining, expected
                    )


class RemainingForecastEnergyTests(unittest.IsolatedAsyncioTestCase):
    """Use the real calculation to distinguish average and instant radiation."""

    async def test_remaining_matches_interval_energy_when_instant_radiation_is_zero(
        self,
    ):
        data = _fake_api_data()
        data["minutely_15"]["global_tilted_irradiance_instant"] = [0, 0]
        forecast = OpenMeteoSolarForecast(
            latitude=50, longitude=10, azimuth=0, declination=25, dc_kwp=1
        )
        with patch.object(forecast, "_request", AsyncMock(return_value=data)):
            estimate = await forecast.estimate()
        start = min(estimate.wh_period_15m)
        with patch.object(Estimate, "now", return_value=start):
            self.assertEqual(sum(estimate.wh_period_15m.values()), 250)
            self.assertEqual(estimate.energy_production_today_remaining, 250)

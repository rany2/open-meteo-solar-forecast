"""Remaining energy includes the unfinished part of the current interval."""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from open_meteo_solar_forecast.models import Estimate, _interval_value_sum_w_to_wh


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

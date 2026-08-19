"""Tests for exact quarter-hour forecast energy."""

# ruff: noqa: S101

import datetime as dt
import math
import unittest
from pathlib import Path

from open_meteo_solar_forecast.models import Estimate
from open_meteo_solar_forecast.open_meteo_solar_forecast import _quarter_hour_energy


class QuarterHourEnergyTests(unittest.TestCase):
    """Verify the exact PT15M energy contract."""

    def test_estimate_addition_is_backward_compatible(self) -> None:
        """Keep existing positional Estimate construction valid."""
        estimate = Estimate({}, {}, {}, dt.UTC)

        assert estimate.wh_period_15m == {}
        assert estimate.watts == {}
        assert estimate.wh_period == {}
        assert estimate.wh_days == {}

    def test_interval_energy_keys_values_and_hourly_conservation(self) -> None:
        """Preserve aware keys and conserve complete-hour energy."""
        timezone = dt.timezone(dt.timedelta(hours=2))
        hour = dt.datetime(2026, 8, 14, 12, tzinfo=timezone)
        average_power = {
            hour + dt.timedelta(minutes=offset): value
            for offset, value in zip(
                (0, 15, 30, 45), (100, 200, 300, 400), strict=True
            )
        }

        periods = _quarter_hour_energy(average_power)
        existing_hourly_energy = sum(average_power.values()) / len(average_power)

        assert list(periods) == list(average_power)
        assert all(
            timestamp.utcoffset() == dt.timedelta(hours=2) for timestamp in periods
        )
        assert periods[hour] == 25.0
        assert math.isclose(
            sum(periods.values()), existing_hourly_energy, rel_tol=1e-12
        )

    def test_combined_clipped_power_is_passed_through_once(self) -> None:
        """Convert an already combined and clipped value exactly once."""
        start = dt.datetime(2026, 8, 14, 12, tzinfo=dt.UTC)
        # The estimate path combines arrays and clips w_avg before conversion.
        periods = _quarter_hour_energy({start: 10_000})

        assert periods == {start: 2_500.0}

    def test_conversion_follows_array_combination_and_inverter_stage(self) -> None:
        """Keep conversion downstream of array combination and the inverter."""
        source = (
            Path(__file__).resolve().parents[1]
            / "src/open_meteo_solar_forecast/open_meteo_solar_forecast.py"
        ).read_text(encoding="utf-8")

        combined = source.index("w_avg[time_start] +=")
        inverted = source.index("w_avg[time] = round(inverter_ac_power")
        converted = source.index("wh_period_15m = _quarter_hour_energy(w_avg)")
        returned = source.index("wh_period_15m=wh_period_15m")

        assert combined < inverted < converted < returned
        assert "watts=w_inst" in source
        assert "wh_period=wh_period" in source
        assert "wh_days=wh_days" in source

    def test_missing_source_periods_do_not_create_zero_intervals(self) -> None:
        """Keep legitimate zeroes without filling absent intervals."""
        start = dt.datetime(2026, 8, 14, 12, tzinfo=dt.UTC)

        periods = _quarter_hour_energy({start: 0})

        assert periods == {start: 0.0}
        assert start + dt.timedelta(minutes=15) not in periods

    def test_timezone_offsets_remain_part_of_timestamp_identity(self) -> None:
        """Keep repeated civil times distinct across a DST offset change."""
        summer = dt.datetime(
            2026, 10, 25, 2, tzinfo=dt.timezone(dt.timedelta(hours=2))
        )
        winter = dt.datetime(
            2026, 10, 25, 2, tzinfo=dt.timezone(dt.timedelta(hours=1))
        )

        periods = _quarter_hour_energy({summer: 100, winter: 200})

        assert periods[summer] == 25.0
        assert periods[winter] == 50.0
        assert summer.isoformat() != winter.isoformat()


if __name__ == "__main__":
    unittest.main()

"""Data models for the Forecast.Solar API."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


def _timed_value(at: dt.datetime, data: dict[dt.datetime, int]) -> int | None:
    """Return the value for a specific time."""
    value = None
    for timestamp, cur_value in data.items():
        if timestamp > at:
            return value
        value = cur_value

    return None


def _interval_value_sum(
    interval_begin: dt.datetime, interval_end: dt.datetime, data: dict[dt.datetime, int]
) -> int:
    """Return the sum of values in interval."""
    total = 0

    for timestamp, wh in data.items():
        # Skip all until this hour
        if timestamp < interval_begin:
            continue

        if timestamp >= interval_end:
            break

        total += wh

    return total


def _interval_value_sum_w_to_wh(
    interval_begin: dt.datetime, interval_end: dt.datetime, data: dict[dt.datetime, int]
) -> float:
    """Convert W to Wh and return the sum of values in interval."""
    total = 0.0
    sorted_timestamps = sorted(data.keys())

    for i, timestamp in enumerate(sorted_timestamps):
        if timestamp >= interval_end:
            break

        # Intersect each forecast interval with the requested time range.
        # Do not extend a quarter-hour sample across missing forecast data.
        start = max(timestamp, interval_begin)
        end = min(timestamp + dt.timedelta(minutes=15), interval_end)
        if i + 1 < len(sorted_timestamps):
            end = min(end, sorted_timestamps[i + 1])
        if end <= start:
            continue

        duration_hours = (end - start).total_seconds() / 3600

        # Add the energy in watt-hours
        total += data[timestamp] * duration_hours

    return total


@dataclass
class Estimate:
    """Object holding estimate forecast results from Forecast.Solar.

    Attributes
    ----------
        watts: Estimated solar power output per time period.
        wh_period: Estimated solar energy production differences per hour.
        wh_days: Estimated solar energy production per day.
        wh_period_15m: Estimated solar energy production per 15-minute interval.

    """

    watts: dict[dt.datetime, int]
    wh_period: dict[dt.datetime, int]
    wh_days: dict[dt.datetime, int]
    api_timezone: dt.timezone
    wh_period_15m: dict[dt.datetime, float] = field(default_factory=dict)

    @property
    def timezone(self) -> timezone:
        """Return API timezone information."""
        return self.api_timezone

    @property
    def energy_production_today(self) -> int:
        """Return estimated energy produced today."""
        return self.day_production(self.now().date())

    @property
    def energy_production_tomorrow(self) -> int:
        """Return estimated energy produced today."""
        return self.day_production(self.now().date() + dt.timedelta(days=1))

    @property
    def energy_production_today_remaining(self) -> float:
        """Return estimated energy produced in rest of today."""
        now = self.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(
            days=1
        )
        if self.wh_period_15m:
            total = 0.0
            interval = dt.timedelta(minutes=15)
            for timestamp, energy in self.wh_period_15m.items():
                start = max(timestamp, now)
                end = min(timestamp + interval, midnight)
                if end > start:
                    total += energy * ((end - start) / interval)
            return total

        # Older callers and stored forecasts may only contain power samples.
        return _interval_value_sum_w_to_wh(
            now,
            midnight,
            self.watts,
        )

    @property
    def power_production_now(self) -> int:
        """Return estimated power production right now."""
        return self.power_production_at_time(self.now())

    @property
    def power_highest_peak_time_today(self) -> dt.datetime:
        """Return datetime with highest power production moment today."""
        return self.peak_production_time(self.now().date())

    @property
    def power_highest_peak_time_tomorrow(self) -> dt.datetime:
        """Return datetime with highest power production moment tomorrow."""
        return self.peak_production_time(self.now().date() + dt.timedelta(days=1))

    @property
    def energy_current_hour(self) -> int:
        """Return the estimated energy production for the current hour."""
        return _interval_value_sum(
            self.now().replace(minute=0, second=0, microsecond=0),
            self.now().replace(minute=0, second=0, microsecond=0)
            + dt.timedelta(hours=1),
            self.wh_period,
        )

    def day_production(self, specific_date: dt.date) -> int:
        """Return the day production."""
        for date, production in self.wh_days.items():
            if date == specific_date:
                return production

        return 0

    def now(self) -> dt.datetime:
        """Return the current timestamp in the API timezone."""
        return dt.datetime.now(tz=self.api_timezone)

    def peak_production_time(self, specific_date: dt.date) -> dt.datetime:
        """Return the peak time on a specific date."""
        value = max(
            (watt for date, watt in self.watts.items() if date.date() == specific_date),
            default=None,
        )
        for timestamp, watt in self.watts.items():
            if watt == value and timestamp.date() == specific_date:
                return timestamp
        raise RuntimeError("No peak production time found")

    def power_production_at_time(self, time: dt.datetime) -> int:
        """Return estimated power production at a specific time."""
        return _timed_value(time, self.watts) or 0

    def sum_energy_production(self, period_hours: int) -> int:
        """Return the sum of the energy production."""
        now = self.now().replace(minute=59, second=59, microsecond=999)
        until = now + dt.timedelta(hours=period_hours)

        return _interval_value_sum(now, until, self.wh_period)

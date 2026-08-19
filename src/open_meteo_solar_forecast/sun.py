"""Sun position and horizon shading helpers."""

from __future__ import annotations

from datetime import UTC, date, tzinfo
from datetime import datetime as dt

import numpy
import suncalc


def check_horizon_shading(
    time: dt,
    lon: float,
    lat: float,
    hmap: numpy.ndarray,
) -> bool:
    """Check if the horizon blocks out direct sunlight."""
    position_rad = suncalc.get_position(time, lon, lat)
    azimuth_deg = (180 + numpy.rad2deg(position_rad["azimuth"])) % 360
    altitude_deg = numpy.rad2deg(position_rad["altitude"])
    horizon_deg = numpy.interp(azimuth_deg, hmap[0], hmap[1])
    return altitude_deg < horizon_deg


def anchor_to_day(ts: int, day: date, tz: tzinfo) -> dt:
    """Convert a timestamp to tz and re-anchor it onto the given day."""
    time = dt.fromtimestamp(ts, UTC).astimezone(tz)
    if time.date() != day:
        time = dt.combine(day, time.timetz())
    return time


def build_sun_times(
    daily_dates: list[date],
    timestamps: list[int],
    tz: tzinfo,
) -> dict[date, dt]:
    """Build a mapping of local dates to re-anchored sun event times.

    Key sunrise/sunset by the date of the daily "time" entry rather
    than the date of the sunrise/sunset timestamp itself. For large
    UTC offsets (e.g. UTC+13) the API can return sunrise/sunset
    timestamps that fall on an adjacent local day, which previously
    caused a KeyError for dates missing from the dicts (issue #45).
    """
    return {
        day: anchor_to_day(ts, day, tz)
        for day, ts in zip(daily_dates, timestamps, strict=True)
    }

"""Substitute satellite-observed irradiance for the recent past.

Everything else in this library is a *forecast*. For time that has already
elapsed, a geostationary satellite has actually watched the sky, and an
observation beats a prediction: against satellite-derived irradiance the model
ensemble carries 11-29% relative error with a consistent negative bias.

That matters because several headline figures are partly or wholly historical
-- energy produced so far today, and power right now. Replacing the forecast
with the observation over the elapsed window removes that error outright.

This is observed irradiance, not measured PV output. Nothing here learns from
the user's system or needs a calibration period.

Coverage is the catch, and the reason this is opt-in rather than automatic:

============================  ==========================  ========
source                        region                      delay
============================  ==========================  ========
EUMETSAT MTG                  Europe, Africa              20 min
EUMETSAT MSG / IODC           Europe, Africa, S. America  2 h
                              India
JMA Himawari                  Asia, Australia, NZ         30 min
NASA GOES                     Americas                    unavailable
============================  ==========================  ========

North America has no coverage at all, so for those users the extra request
would cost latency and return nothing.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy
import pandas as pd

_LOGGER = logging.getLogger(__name__)

SATELLITE_BASE_URL = "https://satellite-api.open-meteo.com"

# Seamless blends the available sources and had the lowest latency measured:
# roughly 15 minutes behind real time, at a 10-minute native step.
SATELLITE_MODEL = "satellite_radiation_seamless"

# Only irradiance is observed. Temperature, wind and snow stay with the
# forecast models.
SATELLITE_VARS: tuple[str, ...] = (
    "shortwave_radiation",
    "shortwave_radiation_instant",
    "diffuse_radiation",
    "diffuse_radiation_instant",
    "direct_normal_irradiance",
    "direct_normal_irradiance_instant",
)

# Averaged variables describe the interval ending at their timestamp, so they
# are re-averaged over each target interval. Instantaneous ones are sampled.
_AVERAGED = tuple(v for v in SATELLITE_VARS if not v.endswith("_instant"))

INTERVAL = pd.Timedelta(minutes=15)


def satellite_params(
    latitude: float, longitude: float, past_days: int
) -> dict[str, str]:
    """Query parameters for the satellite archive request."""
    return {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "hourly": ",".join(SATELLITE_VARS),
        "models": SATELLITE_MODEL,
        # Native resolution keeps the 10-minute cadence instead of collapsing
        # to hourly, which would blur the shape of the day.
        "temporal_resolution": "native",
        "past_days": str(past_days),
        "forecast_days": "1",
        "timeformat": "unixtime",
        "timezone": "UTC",
    }


def _observed_frame(data: Any) -> pd.DataFrame | None:
    """Turn a satellite response into a frame, or None if it carries nothing."""
    hourly = (data or {}).get("hourly")
    if not isinstance(hourly, dict) or not hourly.get("time"):
        return None

    # Convert to plain arrays before building the frame. Handing pandas a
    # Series carrying its own RangeIndex alongside an explicit DatetimeIndex
    # makes it align the two, which silently yields all-NaN.
    frame = pd.DataFrame(
        {
            var: pd.to_numeric(
                pd.Series(hourly.get(var)), errors="coerce"
            ).to_numpy(dtype=float)
            for var in SATELLITE_VARS
            if var in hourly
        },
        index=pd.to_datetime(hourly["time"], unit="s", utc=True),
    )
    frame = frame.dropna(how="all")
    return frame if not frame.empty else None


def _align(observed: pd.DataFrame, targets: pd.DatetimeIndex) -> pd.DataFrame:
    """Resample observations onto the library's 15-minute grid.

    The satellite cadence (10, 15 or 30 minutes depending on source) rarely
    matches, so averaged variables are re-averaged over each target interval
    and instantaneous ones are interpolated to the timestamp itself.
    """
    aligned = pd.DataFrame(index=targets, columns=list(observed.columns), dtype=float)

    for column in observed.columns:
        series = observed[column].dropna()
        if series.empty:
            continue
        if column in _AVERAGED:
            # Bucket each observation into the target interval that contains
            # it. Labels mark interval ends, matching the forecast convention.
            buckets = series.index.ceil(INTERVAL)
            grouped = series.groupby(buckets).mean()
            aligned[column] = grouped.reindex(targets)
        else:
            combined = series.reindex(
                series.index.union(targets)
            ).interpolate(method="time", limit_area="inside")
            aligned[column] = combined.reindex(targets)

    return aligned


def blend_observations(
    minutely: dict[str, list[Any]],
    data: Any,
) -> tuple[dict[str, list[Any]], int]:
    """Overwrite forecast irradiance with observation where one exists.

    Returns the (possibly unchanged) series and how many timesteps were
    replaced. Any timestep the satellite does not cover keeps its forecast
    value, so a partial or entirely empty response degrades quietly.
    """
    observed = _observed_frame(data)
    if observed is None:
        _LOGGER.debug("Satellite response carried no usable irradiance")
        return minutely, 0

    targets = pd.to_datetime(minutely["time"], unit="s", utc=True)
    aligned = _align(observed, targets)

    blended = dict(minutely)
    replaced = numpy.zeros(len(targets), dtype=bool)

    for var in SATELLITE_VARS:
        if var not in aligned or var not in blended:
            continue
        values = aligned[var].to_numpy(dtype=float)
        usable = numpy.isfinite(values)
        if not usable.any():
            continue
        current = numpy.array(
            [numpy.nan if v is None else v for v in blended[var]], dtype=float
        )
        current[usable] = values[usable]
        blended[var] = [None if numpy.isnan(v) else float(v) for v in current]
        replaced |= usable

    count = int(replaced.sum())
    _LOGGER.debug(
        "Replaced forecast irradiance with satellite observation at %d of %d "
        "timesteps",
        count,
        len(targets),
    )
    return blended, count

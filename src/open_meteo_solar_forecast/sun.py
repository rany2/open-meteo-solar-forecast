"""Sun position, irradiance transposition and horizon shading helpers."""

from __future__ import annotations

from datetime import date, tzinfo
from datetime import datetime as dt
from typing import Any


import numpy
import pandas as pd
from pvlib import atmosphere, iam, irradiance, solarposition


def solar_position(
    times: pd.DatetimeIndex, latitude: float, longitude: float
) -> pd.DataFrame:
    """Calculate the solar position for the given times and location."""
    return solarposition.get_solarposition(times, latitude, longitude)


def compute_gti(
    solpos: pd.DataFrame,
    ghi: list[float | None],
    dhi: list[float | None],
    dni: list[float | None],
    array: dict[str, Any],
) -> pd.Series:
    """Transpose horizontal irradiance onto the array plane, after IAM losses.

    Azimuth uses the Open-Meteo convention (0 = South, -90 = East, 90 = West)
    and is converted to the pvlib convention (0 = North, 90 = East).
    """
    times = solpos.index
    tracking = array["tracking"]
    surface_tilt: Any = array["declination"]
    surface_azimuth: Any = (array["azimuth"] + 180.0) % 360.0
    if tracking in ("tilt", "dual"):
        surface_tilt = solpos["apparent_zenith"].clip(0.0, 90.0)
    if tracking in ("azimuth", "dual"):
        surface_azimuth = solpos["azimuth"]

    ghi_series = pd.Series(ghi, index=times, dtype=float)
    dhi_series = pd.Series(dhi, index=times, dtype=float)
    dni_series = pd.Series(dni, index=times, dtype=float)

    total = irradiance.get_total_irradiance(
        surface_tilt,
        surface_azimuth,
        solpos["apparent_zenith"],
        solpos["azimuth"],
        dni_series,
        ghi_series,
        dhi_series,
        dni_extra=irradiance.get_extra_radiation(times),
        airmass=atmosphere.get_relative_airmass(solpos["apparent_zenith"]),
        albedo=array["albedo"],
        model="perez-driesse",
    )

    aoi = irradiance.aoi(
        surface_tilt, surface_azimuth, solpos["apparent_zenith"], solpos["azimuth"]
    )
    iam_beam = iam.physical(aoi)
    iam_diffuse = iam.marion_diffuse("physical", surface_tilt)

    poa = (
        total["poa_direct"] * iam_beam
        + total["poa_sky_diffuse"] * iam_diffuse["sky"]
        + total["poa_ground_diffuse"] * iam_diffuse["ground"]
    )

    # Perez yields NaN below the horizon, where there is no irradiance anyway.
    return poa.fillna(0.0).clip(lower=0.0)


def check_horizon_shading(
    solpos: pd.DataFrame,
    hmap: numpy.ndarray,
) -> numpy.ndarray:
    """Check if the horizon blocks out direct sunlight."""
    azimuth_deg = solpos["azimuth"].to_numpy() % 360
    altitude_deg = solpos["apparent_elevation"].to_numpy()
    horizon_deg = numpy.interp(azimuth_deg, hmap[0], hmap[1])
    return altitude_deg < horizon_deg


def build_sun_times(
    daily_dates: list[date],
    latitude: float,
    longitude: float,
    tz: tzinfo,
) -> tuple[dict[date, dt], dict[date, dt]]:
    """Build mappings of local dates to sunrise and sunset times."""
    days = pd.DatetimeIndex(
        [dt.combine(day, dt.min.time(), tzinfo=tz) for day in daily_dates]
    )
    events = solarposition.sun_rise_set_transit_spa(days, latitude, longitude)
    sunrise: dict[date, dt] = {}
    sunset: dict[date, dt] = {}
    for day, rise, set_ in zip(
        daily_dates, events["sunrise"], events["sunset"], strict=True
    ):
        midnight = dt.combine(day, dt.min.time(), tzinfo=tz)
        sunrise[day] = (
            midnight
            if pd.isna(rise)
            else rise.round("s").astimezone(tz).to_pydatetime()
        )
        sunset[day] = (
            midnight
            if pd.isna(set_)
            else set_.round("s").astimezone(tz).to_pydatetime()
        )
    return sunrise, sunset

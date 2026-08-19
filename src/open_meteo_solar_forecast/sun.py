"""Sun position, irradiance transposition and horizon shading helpers."""

from __future__ import annotations

from datetime import date, tzinfo
from datetime import datetime as dt
from typing import Any, NamedTuple

import numpy
import pandas as pd
from pvlib import atmosphere, iam, irradiance, solarposition


class PlaneIrradiance(NamedTuple):
    """Plane-of-array irradiance, with and without the direct beam.

    Attributes
    ----------
        total: Everything the array collects: beam, sky diffuse and
            ground-reflected, each after incidence-angle losses.
        beam_blocked: What remains when something opaque stands between the
            array and the sun. Always less than or equal to ``total``.

    """

    total: pd.Series
    beam_blocked: pd.Series


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
) -> PlaneIrradiance:
    """Transpose horizontal irradiance onto the array plane, after IAM losses.

    Azimuth uses the Open-Meteo convention (0 = South, -90 = East, 90 = West)
    and is converted to the pvlib convention (0 = North, 90 = East).

    Returns both the unobstructed total and the value that survives when the
    direct beam is blocked. The second is assembled explicitly rather than
    falling back to horizontal diffuse irradiance, because two things must be
    removed together:

    * the beam itself, and
    * the **circumsolar** part of sky diffuse, which is forward-scattered light
      arriving from within a few degrees of the sun's disc. Whatever hides the
      sun hides that halo too. It is not a rounding error: it averages about a
      third of sky diffuse and can exceed three quarters in clear conditions.

    Isotropic sky, horizon brightening and ground reflection all survive, since
    they arrive from directions the obstruction does not cover.
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

    sky = irradiance.perez_driesse(
        surface_tilt,
        surface_azimuth,
        dhi_series,
        dni_series,
        irradiance.get_extra_radiation(times),
        solpos["apparent_zenith"],
        solpos["azimuth"],
        airmass=atmosphere.get_relative_airmass(solpos["apparent_zenith"]),
        return_components=True,
    )
    beam = irradiance.beam_component(
        surface_tilt, surface_azimuth, solpos["apparent_zenith"], solpos["azimuth"],
        dni_series,
    )
    ground = irradiance.get_ground_diffuse(
        surface_tilt, ghi_series, albedo=array["albedo"]
    )

    aoi = irradiance.aoi(
        surface_tilt, surface_azimuth, solpos["apparent_zenith"], solpos["azimuth"]
    )
    iam_beam = iam.physical(aoi)
    iam_diffuse = iam.marion_diffuse("physical", surface_tilt)

    ground_term = ground * iam_diffuse["ground"]
    poa = (
        beam * iam_beam
        + sky["poa_sky_diffuse"] * iam_diffuse["sky"]
        + ground_term
    )
    poa_beam_blocked = (
        (sky["poa_isotropic"] + sky["poa_horizon"]) * iam_diffuse["sky"]
        + ground_term
    )

    # Perez yields NaN below the horizon, where there is no irradiance anyway.
    return PlaneIrradiance(
        total=poa.fillna(0.0).clip(lower=0.0),
        beam_blocked=poa_beam_blocked.fillna(0.0).clip(lower=0.0),
    )


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

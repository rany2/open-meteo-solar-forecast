"""Sun position, irradiance transposition and horizon shading helpers."""

from __future__ import annotations

from datetime import date, tzinfo
from datetime import datetime as dt
from functools import lru_cache
from typing import Any, NamedTuple

import numpy
import pandas as pd
from pvlib import atmosphere, iam, irradiance, solarposition

# Resolution of the sky-dome integration below. 0.5 deg in azimuth and
# elevation converges to well under 0.1% of the analytic result while staying
# a few milliseconds of work, and the result is cached anyway.
_SVF_AZIMUTH_STEPS = 720
_SVF_ELEVATION_STEPS = 180


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

    When a horizon profile is supplied, those surviving sky components are also
    scaled by :func:`sky_view_factor`, because a skyline hides part of the sky
    dome permanently rather than only while the sun is behind it. That scaling
    applies to the unobstructed total as well, since the sky is missing at all
    times of day.
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

    # A skyline hides part of the sky dome at all times, not only when the sun
    # is behind it. Circumsolar is excluded from the scaling: it tracks the
    # sun, so it is either fully visible or fully blocked, which the caller
    # decides by choosing between the two values returned here.
    view_factor = 1.0
    if array.get("use_horizon"):
        view_factor = sky_view_factor(
            tuple(tuple(float(v) for v in point) for point in array["horizon_map"]),
            round(float(numpy.mean(numpy.asarray(surface_tilt, dtype=float))), 2),
            round(float(numpy.mean(numpy.asarray(surface_azimuth, dtype=float))), 2),
        )

    ground_term = ground * iam_diffuse["ground"]
    diffuse_visible = (
        (sky["poa_isotropic"] + sky["poa_horizon"]) * view_factor
    )
    poa = (
        beam * iam_beam
        + (diffuse_visible + sky["poa_circumsolar"]) * iam_diffuse["sky"]
        + ground_term
    )
    poa_beam_blocked = diffuse_visible * iam_diffuse["sky"] + ground_term

    # Perez yields NaN below the horizon, where there is no irradiance anyway.
    return PlaneIrradiance(
        total=poa.fillna(0.0).clip(lower=0.0),
        beam_blocked=poa_beam_blocked.fillna(0.0).clip(lower=0.0),
    )


@lru_cache(maxsize=64)
def sky_view_factor(
    horizon_map: tuple[tuple[float, float], ...],
    surface_tilt: float,
    surface_azimuth: float,
) -> float:
    """Fraction of a tilted plane's sky diffuse that survives the skyline.

    Blocking the sun is only half of what a hill does. It also permanently
    hides part of the sky dome, so diffuse light is reduced *at every moment*,
    including when the sun is nowhere near the obstruction.

    Computed by integrating the visible sky over the hemisphere, weighting each
    direction by its incidence angle on the plane, and dividing by the same
    integral with a flat horizon. For an unobstructed flat plane this reduces
    to the familiar ``(1 + cos(tilt)) / 2`` and the ratio is 1.0.

    The weighting is what makes the result directional: a hill behind a
    south-facing array barely matters, while the same hill in front of it is
    significant, because the plane hardly faces the sky behind it.

    Args:
    ----
        horizon_map: ``(azimuth, elevation)`` pairs in degrees, azimuth
            measured clockwise from north.
        surface_tilt: Module tilt from horizontal, degrees.
        surface_azimuth: Direction the modules face, degrees clockwise from
            north (pvlib convention).

    Returns:
    -------
        Multiplier in [0, 1] to apply to sky diffuse irradiance.

    """
    hmap = numpy.asarray(horizon_map, dtype=float)

    # Cell centres, so no sample sits exactly on a boundary.
    azimuth = (
        numpy.linspace(0.0, 360.0, _SVF_AZIMUTH_STEPS, endpoint=False)
        + 180.0 / _SVF_AZIMUTH_STEPS
    )
    elevation = (
        numpy.linspace(0.0, 90.0, _SVF_ELEVATION_STEPS, endpoint=False)
        + 45.0 / _SVF_ELEVATION_STEPS
    )
    grid_az, grid_el = numpy.meshgrid(azimuth, elevation, indexing="ij")

    az_rad = numpy.radians(grid_az)
    el_rad = numpy.radians(grid_el)
    tilt_rad = numpy.radians(surface_tilt)
    saz_rad = numpy.radians(surface_azimuth)

    # Cosine of the angle between the sky direction and the surface normal.
    cos_incidence = numpy.sin(el_rad) * numpy.cos(tilt_rad) + numpy.cos(
        el_rad
    ) * numpy.sin(tilt_rad) * numpy.cos(az_rad - saz_rad)

    # Sky behind the plane contributes nothing; cos(el) is the solid-angle
    # element for a hemisphere parameterised by elevation.
    weight = numpy.clip(cos_incidence, 0.0, None) * numpy.cos(el_rad)
    unobstructed = weight.sum()
    if unobstructed <= 0:
        return 1.0

    horizon = numpy.interp(azimuth, hmap[:, 0], hmap[:, 1])
    visible = grid_el >= horizon[:, None]
    return float(numpy.clip(weight[visible].sum() / unobstructed, 0.0, 1.0))


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

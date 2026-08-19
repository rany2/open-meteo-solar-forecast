"""Tests for horizon shading.

The property that matters is monotonicity: raising the skyline can never raise
production. That failed before, because the shaded branch substituted raw
*horizontal* diffuse irradiance for the plane-of-array value. For a tilted
array the horizontal figure is often the larger of the two, so a modest hill
appeared to *increase* output.
"""

# ruff: noqa: S101

import unittest

import numpy as np
import pandas as pd
from pvlib import atmosphere, iam, irradiance, solarposition

from open_meteo_solar_forecast.sun import (
    check_horizon_shading,
    compute_gti,
    sky_view_factor,
)

LAT, LON = 52.0, 4.0


def _uniform(elevation: float) -> tuple[tuple[float, float], ...]:
    return ((0.0, elevation), (360.0, elevation))


def _scene(n: int = 48, tilt: float = 40.0, albedo: float = 0.25):
    """Build a day of plausible irradiance and the matching solar position."""
    times = pd.date_range("2026-06-21 03:00", periods=n, freq="20min", tz="UTC")
    solpos = solarposition.get_solarposition(times, LAT, LON)
    cosz = np.cos(np.radians(solpos["apparent_zenith"])).clip(lower=0)
    dni = pd.Series(np.where(cosz > 0, 780.0, 0.0), index=times)
    dhi = pd.Series(np.where(cosz > 0, 130.0, 0.0), index=times)
    ghi = dhi + dni * cosz
    array = {
        "tracking": "none",
        "declination": tilt,
        "azimuth": 0.0,
        "albedo": albedo,
    }
    return solpos, ghi.tolist(), dhi.tolist(), dni.tolist(), array


class PlaneIrradianceTests(unittest.TestCase):
    """Verify the two plane-of-array components."""

    def test_blocked_never_exceeds_total(self) -> None:
        """Guarantee shading can only ever remove irradiance."""
        plane = compute_gti(*_scene())
        assert (plane.beam_blocked <= plane.total + 1e-9).all()

    def test_blocked_is_strictly_less_whenever_a_beam_exists(self) -> None:
        """Remove light wherever there is a beam striking the front of the array.

        Around sunrise and sunset the sun swings behind the array plane. There
        is no beam to block then, so shading correctly changes nothing, and
        those timestamps are excluded here.
        """
        solpos, ghi, dhi, dni, array = _scene()
        plane = compute_gti(solpos, ghi, dhi, dni, array)
        beam = irradiance.beam_component(
            array["declination"],
            (array["azimuth"] + 180.0) % 360.0,
            solpos["apparent_zenith"],
            solpos["azimuth"],
            pd.Series(dni, index=solpos.index),
        )
        lit = beam > 1.0
        assert lit.any()
        assert (plane.beam_blocked[lit] < plane.total[lit]).all()

    def test_blocked_equals_total_when_the_sun_is_behind_the_array(self) -> None:
        """Change nothing where no beam reaches the front of the modules."""
        solpos, ghi, dhi, dni, array = _scene()
        plane = compute_gti(solpos, ghi, dhi, dni, array)
        beam = irradiance.beam_component(
            array["declination"],
            (array["azimuth"] + 180.0) % 360.0,
            solpos["apparent_zenith"],
            solpos["azimuth"],
            pd.Series(dni, index=solpos.index),
        )
        behind = beam <= 0.0
        assert behind.any()
        assert np.allclose(plane.beam_blocked[behind], plane.total[behind])

    def test_total_matches_the_pvlib_reference_assembly(self) -> None:
        """Leave unshaded output identical to the previous implementation.

        The components are assembled by hand now, so this pins them against
        pvlib's own combined helper.
        """
        solpos, ghi, dhi, dni, array = _scene()
        times = solpos.index
        tilt = array["declination"]
        saz = (array["azimuth"] + 180.0) % 360.0

        reference = irradiance.get_total_irradiance(
            tilt, saz, solpos["apparent_zenith"], solpos["azimuth"],
            pd.Series(dni, index=times), pd.Series(ghi, index=times),
            pd.Series(dhi, index=times),
            dni_extra=irradiance.get_extra_radiation(times),
            airmass=atmosphere.get_relative_airmass(solpos["apparent_zenith"]),
            albedo=array["albedo"], model="perez-driesse",
        )
        aoi = irradiance.aoi(
            tilt, saz, solpos["apparent_zenith"], solpos["azimuth"]
        )
        iam_d = iam.marion_diffuse("physical", tilt)
        expected = (
            reference["poa_direct"] * iam.physical(aoi)
            + reference["poa_sky_diffuse"] * iam_d["sky"]
            + reference["poa_ground_diffuse"] * iam_d["ground"]
        ).fillna(0.0).clip(lower=0.0)

        assert np.allclose(compute_gti(*_scene()).total, expected)

    def test_blocked_excludes_circumsolar(self) -> None:
        """Drop the circumsolar halo along with the beam.

        Whatever hides the sun's disc also hides the forward-scattered light
        immediately around it, which is a large share of sky diffuse.
        """
        solpos, ghi, dhi, dni, array = _scene()
        plane = compute_gti(solpos, ghi, dhi, dni, array)
        times = solpos.index
        tilt = array["declination"]
        saz = (array["azimuth"] + 180.0) % 360.0

        sky = irradiance.perez_driesse(
            tilt, saz, pd.Series(dhi, index=times), pd.Series(dni, index=times),
            irradiance.get_extra_radiation(times),
            solpos["apparent_zenith"], solpos["azimuth"],
            airmass=atmosphere.get_relative_airmass(solpos["apparent_zenith"]),
            return_components=True,
        )
        ground = irradiance.get_ground_diffuse(
            tilt, pd.Series(ghi, index=times), albedo=array["albedo"]
        )
        iam_d = iam.marion_diffuse("physical", tilt)
        expected = (
            (sky["poa_isotropic"] + sky["poa_horizon"]) * iam_d["sky"]
            + ground * iam_d["ground"]
        ).fillna(0.0).clip(lower=0.0)

        assert np.allclose(plane.beam_blocked, expected)

        daylight = plane.total > 50
        circumsolar_share = (
            sky["poa_circumsolar"][daylight] / sky["poa_sky_diffuse"][daylight]
        )
        assert circumsolar_share.mean() > 0.1, "circumsolar should be material"

    def test_never_negative(self) -> None:
        """Keep both components physically valid."""
        plane = compute_gti(*_scene())
        assert (plane.total >= 0).all()
        assert (plane.beam_blocked >= 0).all()

    def test_snowy_albedo_raises_both_components(self) -> None:
        """Reflect more from snowy ground onto the tilted plane."""
        bare = compute_gti(*_scene(albedo=0.25))
        snowy = compute_gti(*_scene(albedo=0.65))
        assert snowy.total.sum() > bare.total.sum()
        assert snowy.beam_blocked.sum() > bare.beam_blocked.sum()


class SkyViewFactorTests(unittest.TestCase):
    """Verify the fraction of sky diffuse surviving a skyline."""

    def test_matches_the_analytic_solution_for_a_flat_plane(self) -> None:
        """Reproduce cos^2(h) exactly for a horizontal plane.

        For tilt 0 and a uniform skyline at elevation h, integrating the
        visible sky weighted by incidence angle has the closed form cos^2(h).
        This pins the geometry.
        """
        for h in (0, 10, 20, 30, 45, 60, 80):
            got = sky_view_factor(_uniform(h), 0.0, 180.0)
            assert abs(got - np.cos(np.radians(h)) ** 2) < 1e-6

    def test_flat_horizon_is_a_no_op(self) -> None:
        """Hide no sky when the skyline is flat."""
        for tilt in (0.0, 20.0, 40.0, 90.0):
            assert abs(sky_view_factor(_uniform(0.0), tilt, 180.0) - 1.0) < 1e-9

    def test_a_full_wall_hides_everything(self) -> None:
        """Leave no visible sky behind a 90 degree skyline."""
        assert sky_view_factor(_uniform(90.0), 35.0, 180.0) < 1e-6

    def test_decreases_monotonically_with_skyline_height(self) -> None:
        """Hide more sky as the skyline rises."""
        values = [
            sky_view_factor(_uniform(h), 35.0, 180.0)
            for h in (0, 5, 10, 20, 30, 45, 60, 80)
        ]
        assert values == sorted(values, reverse=True)

    def test_is_directional(self) -> None:
        """Weight obstructions by whether the array actually faces them.

        A tilted array barely sees the sky behind it, so a hill there should
        cost far less than the same hill in front.
        """
        in_front = ((0.0, 0.0), (90.0, 0.0), (180.0, 40.0), (270.0, 0.0),
                    (360.0, 0.0))
        behind = ((0.0, 40.0), (90.0, 0.0), (180.0, 0.0), (270.0, 0.0),
                  (360.0, 40.0))
        south_facing = 180.0
        assert (
            sky_view_factor(in_front, 35.0, south_facing)
            < sky_view_factor(behind, 35.0, south_facing)
        )

    def test_bounded(self) -> None:
        """Stay within [0, 1] across a range of shapes."""
        for h in (0, 15, 45, 75, 90):
            for tilt in (0.0, 15.0, 45.0, 90.0):
                value = sky_view_factor(_uniform(h), tilt, 180.0)
                assert 0.0 <= value <= 1.0


class SkyViewIntegrationTests(unittest.TestCase):
    """Verify the factor reaches the irradiance actually used."""

    @staticmethod
    def _plane(use_horizon: bool, elevation: float = 25.0):
        solpos, ghi, dhi, dni, array = _scene()
        array = {
            **array,
            "use_horizon": use_horizon,
            "horizon_map": _uniform(elevation),
        }
        return compute_gti(solpos, ghi, dhi, dni, array)

    def test_diffuse_is_reduced_even_when_the_sun_is_clear(self) -> None:
        """Reduce diffuse at all times, not only while the sun is behind.

        This is the whole point: a hill hides sky permanently. Compare only
        timestamps where the sun is well above the skyline, so no beam
        blocking is involved.
        """
        solpos, *_ = _scene()
        high_sun = solpos["apparent_elevation"].to_numpy() > 40.0
        assert high_sun.any()

        plain = self._plane(use_horizon=False)
        walled = self._plane(use_horizon=True)

        assert (
            walled.total.to_numpy()[high_sun] < plain.total.to_numpy()[high_sun]
        ).all()

    def test_no_effect_without_a_horizon(self) -> None:
        """Leave arrays that did not opt in completely untouched."""
        plain = self._plane(use_horizon=False)
        solpos, ghi, dhi, dni, array = _scene()
        assert np.allclose(plain.total, compute_gti(solpos, ghi, dhi, dni, array).total)

    def test_blocked_still_never_exceeds_total(self) -> None:
        """Preserve the ordering once the view factor is applied."""
        walled = self._plane(use_horizon=True)
        assert (walled.beam_blocked <= walled.total + 1e-9).all()


class HorizonMonotonicityTests(unittest.TestCase):
    """Verify a taller skyline never increases collected irradiance."""

    @staticmethod
    def _collected(elevation: float) -> float:
        """Total collected irradiance, via the same path the library uses.

        Includes the sky-view factor, so this exercises beam blocking and
        permanent sky obstruction together rather than only the former.
        """
        solpos, ghi, dhi, dni, array = _scene()
        array = {
            **array,
            "use_horizon": True,
            "horizon_map": _uniform(elevation),
        }
        plane = compute_gti(solpos, ghi, dhi, dni, array)
        hmap = np.array(_uniform(elevation)).T
        shaded = check_horizon_shading(solpos, hmap)
        return float(np.where(shaded, plane.beam_blocked, plane.total).sum())

    def test_raising_the_horizon_never_increases_output(self) -> None:
        """Decrease monotonically as the skyline rises."""
        previous = None
        for elevation in (0, 5, 10, 15, 25, 40, 60, 80):
            value = self._collected(elevation)
            if previous is not None:
                assert value <= previous + 1e-6, (
                    f"horizon {elevation} deg collected more than the step below"
                )
            previous = value

    def test_flat_horizon_is_a_no_op(self) -> None:
        """Change nothing when the horizon is flat.

        A 0 degree skyline only 'shades' the array when the sun is already
        below the horizon and there is no direct beam to lose.
        """
        solpos, ghi, dhi, dni, array = _scene()
        plane = compute_gti(solpos, ghi, dhi, dni, array)
        assert abs(self._collected(0.0) - float(plane.total.sum())) < 1e-6

    def test_a_wall_removes_most_of_the_output(self) -> None:
        """Leave only sky and ground diffuse behind a very high skyline."""
        solpos, ghi, dhi, dni, array = _scene()
        plane = compute_gti(solpos, ghi, dhi, dni, array)
        assert self._collected(89.0) < 0.5 * float(plane.total.sum())


if __name__ == "__main__":
    unittest.main()

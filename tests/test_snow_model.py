"""Tests for the NREL snow coverage model.

The behaviour these lock in is the distinction between snow on the *ground* and
snow on the *modules*. Driving panel losses from ground depth predicted a 59%
winter energy loss in Oslo where the physical model predicts almost none.
"""

# ruff: noqa: S101

import unittest

import pandas as pd

from open_meteo_solar_forecast.snow import snow_dc_loss


def _times(n: int, freq_min: int = 15) -> pd.DatetimeIndex:
    return pd.date_range("2026-01-15 08:00", periods=n, freq=f"{freq_min}min", tz="UTC")


class SnowCoverageTests(unittest.TestCase):
    """Verify snow coverage is modelled on the modules, not on the ground."""

    def test_no_snow_means_no_loss(self) -> None:
        """Produce zero loss when there is no snow at all."""
        n = 24
        loss = snow_dc_loss(
            _times(n), [0.0] * n, [0.0] * n, [500.0] * n, [5.0] * n, surface_tilt=35.0
        )
        assert loss.tolist() == [0.0] * n

    def test_deep_ground_snow_alone_does_not_zero_output(self) -> None:
        """Do not derate purely because snow lies on the ground.

        This is the regression guard for the original bug: 30 cm of old ground
        snow, no fresh snowfall, sun on the panel. A tilted module sheds within
        hours, so late in the window it must be producing.
        """
        n = 48  # 12 hours of daylight at 15-minute resolution
        loss = snow_dc_loss(
            _times(n),
            [0.0] * n,  # no fresh snowfall
            [0.30] * n,  # 30 cm on the ground, persisting
            [600.0] * n,  # sunny
            [2.0] * n,  # above freezing
            surface_tilt=35.0,
        )
        assert loss[-1] == 0.0, "panel should have shed old ground snow"

    def test_fresh_snowfall_covers_the_module(self) -> None:
        """Derate fully while snow is actively falling."""
        n = 12
        loss = snow_dc_loss(
            _times(n),
            [1.0] * n,  # 1 cm per 15 min = 4 cm/hr, well over threshold
            [0.10] * n,
            [50.0] * n,  # dim, so it cannot slide off
            [-5.0] * n,  # freezing
            surface_tilt=35.0,
        )
        assert loss[-1] == 1.0

    def test_snow_slides_off_once_the_sun_returns(self) -> None:
        """Recover after a snowfall event ends and irradiance rises."""
        snowfall = [2.0] * 4 + [0.0] * 44
        poa = [20.0] * 4 + [700.0] * 44
        temp = [-3.0] * 4 + [4.0] * 44
        n = len(snowfall)

        loss = snow_dc_loss(
            _times(n), snowfall, [0.15] * n, poa, temp, surface_tilt=40.0
        )

        assert loss[3] == 1.0, "covered during the snowfall event"
        assert loss[-1] < loss[3], "should shed once the sun is out"

    def test_steeper_tilt_sheds_at_least_as_fast(self) -> None:
        """Shed snow no more slowly on a steep roof than on a shallow one."""
        snowfall = [2.0] * 4 + [0.0] * 44
        poa = [20.0] * 4 + [500.0] * 44
        temp = [-3.0] * 4 + [3.0] * 44
        n = len(snowfall)

        steep = snow_dc_loss(
            _times(n), snowfall, [0.15] * n, poa, temp, surface_tilt=60.0
        )
        shallow = snow_dc_loss(
            _times(n), snowfall, [0.15] * n, poa, temp, surface_tilt=10.0
        )
        assert steep.sum() <= shallow.sum()

    def test_loss_is_always_a_valid_fraction(self) -> None:
        """Keep the loss within [0, 1] for noisy input."""
        n = 40
        loss = snow_dc_loss(
            _times(n),
            [0.0, 5.0] * (n // 2),
            [0.0, 0.4] * (n // 2),
            [0.0, 900.0] * (n // 2),
            [-20.0, 15.0] * (n // 2),
            surface_tilt=30.0,
        )
        assert len(loss) == n
        assert loss.min() >= 0.0
        assert loss.max() <= 1.0

    def test_short_series_is_handled_gracefully(self) -> None:
        """Return zeros instead of raising when there is no usable history.

        pvlib needs at least three timestamps to infer the sampling frequency.
        Real responses carry hundreds, but the library must not crash on a
        degenerate series.
        """
        for n in (0, 1, 2):
            loss = snow_dc_loss(
                _times(n), [1.0] * n, [0.2] * n, [10.0] * n, [-5.0] * n,
                surface_tilt=35.0,
            )
            assert len(loss) == n
            assert loss.tolist() == [0.0] * n

    def test_tracker_tilt_series_is_accepted(self) -> None:
        """Collapse a time-varying tracker tilt to a representative angle."""
        n = 20
        tilts = pd.Series(range(n), dtype=float).to_numpy()
        loss = snow_dc_loss(
            _times(n), [0.0] * n, [0.0] * n, [400.0] * n, [3.0] * n,
            surface_tilt=tilts,
        )
        assert len(loss) == n


if __name__ == "__main__":
    unittest.main()

"""Tests for wind-height correction and cell temperature, including inertia."""

# ruff: noqa: S101

import unittest

import numpy as np
import pandas as pd

from open_meteo_solar_forecast.constants import WIND_SPEED_10M_TO_MODULE
from open_meteo_solar_forecast.power import (
    _uniform_runs,
    cell_temperature,
    cell_temperature_series,
    module_wind_speed,
)


def _times(n: int, freq: str = "15min") -> pd.DatetimeIndex:
    return pd.date_range("2026-06-01 06:00", periods=n, freq=freq, tz="UTC")


class WindHeightTests(unittest.TestCase):
    """Verify the 10 m to module-height wind conversion."""

    def test_ratio_is_within_the_published_range(self) -> None:
        """Stay inside the 10 m -> 2 m ratios reported in the literature.

        Driesse (2022) surveys values of 0.51, 0.56, 0.67 and 0.725.
        """
        assert 0.51 <= WIND_SPEED_10M_TO_MODULE <= 0.725

    def test_module_wind_is_slower_than_10m_wind(self) -> None:
        """Reduce wind speed, since wind slows closer to the ground."""
        for w in (0.5, 2.0, 8.0):
            assert 0 < module_wind_speed(w) < w

    def test_calm_stays_calm(self) -> None:
        """Map zero wind to zero wind."""
        assert module_wind_speed(0.0) == 0.0

    def test_slower_wind_gives_a_hotter_cell(self) -> None:
        """Confirm the correction raises cell temperature, lowering output.

        This is the whole point: feeding 10 m wind to Faiman overstates
        convective cooling.
        """
        hot = cell_temperature(900, 25, module_wind_speed(4.0))
        cool = cell_temperature(900, 25, 4.0)
        assert hot > cool


class UniformRunTests(unittest.TestCase):
    """Verify how gapped time series are split for pvlib routines."""

    def test_regular_index_is_one_run(self) -> None:
        """Return a single run covering a regularly sampled index."""
        assert _uniform_runs(_times(20)) == [(0, 20)]

    def test_gap_splits_into_two_runs(self) -> None:
        """Split either side of a hole in the series."""
        idx = _times(30)
        gapped = idx[list(range(12)) + list(range(20, 30))]
        runs = _uniform_runs(gapped)
        assert len(runs) == 2
        # every run must be internally uniform
        for start, stop in runs:
            deltas = gapped[start:stop].to_series().diff().dropna().unique()
            assert len(deltas) == 1

    def test_short_series_yields_no_runs(self) -> None:
        """Skip series too short for smoothing to mean anything."""
        assert _uniform_runs(_times(2)) == []

    def test_runs_stay_within_bounds(self) -> None:
        """Never index past the end of the series."""
        idx = _times(40)
        gapped = idx[list(range(5)) + list(range(9, 20)) + list(range(30, 40))]
        for start, stop in _uniform_runs(gapped):
            assert 0 <= start < stop <= len(gapped)


class CellTemperatureSeriesTests(unittest.TestCase):
    """Verify the vectorised cell temperature path."""

    @staticmethod
    def _inputs(n: int):
        poa = np.linspace(0, 900, n)
        air = np.full(n, 20.0)
        wind = np.full(n, 2.0)
        return poa, air, wind

    def test_matches_the_scalar_model_without_inertia(self) -> None:
        """Agree with the scalar Faiman helper when smoothing is off."""
        n = 12
        poa, air, wind = self._inputs(n)
        series = cell_temperature_series(_times(n), poa, air, wind)
        for i in range(n):
            assert abs(series[i] - cell_temperature(poa[i], air[i], wind[i])) < 1e-9

    def test_inertia_changes_the_result_on_15_minute_data(self) -> None:
        """Apply smoothing when the sampling interval is short enough."""
        n = 40
        poa, air, wind = self._inputs(n)
        steady = cell_temperature_series(_times(n), poa, air, wind)
        smoothed = cell_temperature_series(
            _times(n), poa, air, wind, thermal_inertia=True
        )
        assert not np.allclose(steady, smoothed)

    def test_inertia_lags_a_rising_temperature(self) -> None:
        """Trail the steady-state value while conditions are warming.

        Thermal mass means the module has not caught up yet.
        """
        n = 40
        poa, air, wind = self._inputs(n)
        steady = cell_temperature_series(_times(n), poa, air, wind)
        smoothed = cell_temperature_series(
            _times(n), poa, air, wind, thermal_inertia=True
        )
        assert smoothed[-1] < steady[-1]

    def test_gapped_series_does_not_raise(self) -> None:
        """Survive an index with holes.

        pvlib's smoothing rejects unequal intervals outright, and rows with
        incomplete weather data are dropped upstream, so gaps are routine.
        """
        idx = _times(40)
        keep = list(range(15)) + list(range(27, 40))
        gapped = idx[keep]
        poa, air, wind = self._inputs(len(keep))

        result = cell_temperature_series(
            gapped, poa, air, wind, thermal_inertia=True
        )

        assert len(result) == len(keep)
        assert np.isfinite(result).all()

    def test_hourly_series_falls_back_to_steady_state(self) -> None:
        """Leave hourly data alone, which pvlib declines to smooth."""
        n = 12
        poa, air, wind = self._inputs(n)
        idx = _times(n, freq="1h")
        steady = cell_temperature_series(idx, poa, air, wind)
        smoothed = cell_temperature_series(
            idx, poa, air, wind, thermal_inertia=True
        )
        assert np.allclose(steady, smoothed)

    def test_short_series_is_handled(self) -> None:
        """Return steady-state values when there is no history to smooth."""
        for n in (0, 1, 2, 3):
            poa, air, wind = self._inputs(n)
            out = cell_temperature_series(
                _times(n), poa, air, wind, thermal_inertia=True
            )
            assert len(out) == n

    def test_darkness_sits_at_ambient(self) -> None:
        """Report ambient temperature when there is no irradiance."""
        n = 10
        out = cell_temperature_series(
            _times(n), np.zeros(n), np.full(n, 7.5), np.full(n, 1.0)
        )
        assert np.allclose(out, 7.5)


if __name__ == "__main__":
    unittest.main()

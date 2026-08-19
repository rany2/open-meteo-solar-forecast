"""Tests for DC system losses.

Before this was added the model described a perfect array: no soiling, no
mismatch, no wiring loss. That over-predicted production by roughly 9% at every
single timestep.
"""

# ruff: noqa: S101

import unittest

from open_meteo_solar_forecast.constants import (
    ALPHA_TEMP,
    DC_LOSS_FACTOR,
    G_STC,
    PVWATTS_DC_LOSS_PERCENT,
    TEMP_STC_CELL,
)
from open_meteo_solar_forecast.power import cell_temperature, gen_power


class DcLossConstantTests(unittest.TestCase):
    """Verify the loss constant is plausible and internally consistent."""

    def test_loss_is_in_a_physically_sensible_range(self) -> None:
        """Keep the derate between 5% and 15%."""
        assert 5.0 < PVWATTS_DC_LOSS_PERCENT < 15.0

    def test_factor_matches_percentage(self) -> None:
        """Keep the multiplicative and percentage forms in agreement."""
        assert abs(DC_LOSS_FACTOR - (1 - PVWATTS_DC_LOSS_PERCENT / 100)) < 1e-12

    def test_excludes_shading_and_availability(self) -> None:
        """Stay below PVWatts' stock 14.076% default.

        Shading is modelled explicitly through ``horizon_map``, and
        availability is a fleet-average outage allowance that does not belong
        in a per-interval forecast. Including either would bias every forecast
        low, so the derate must remain meaningfully below the stock figure.
        """
        assert PVWATTS_DC_LOSS_PERCENT < 14.076
        assert 8.0 < PVWATTS_DC_LOSS_PERCENT < 9.5


class GenPowerLossTests(unittest.TestCase):
    """Verify gen_power applies the derate."""

    def test_output_is_derated_against_the_lossless_formula(self) -> None:
        """Match the textbook formula scaled by the loss factor."""
        gti, t_amb, wind, dc_wp = 800.0, 15.0, 2.0, 5000.0

        temp_cell = cell_temperature(gti, t_amb, wind)
        lossless = (
            dc_wp
            * (gti / G_STC)
            * (1 + ALPHA_TEMP * (temp_cell - TEMP_STC_CELL))
        )
        expected = round(lossless * DC_LOSS_FACTOR)

        assert gen_power(gti, t_amb, wind, 1.0, dc_wp) == expected

    def test_derate_is_roughly_nine_percent(self) -> None:
        """Sanity-check the magnitude of the correction."""
        gti, t_amb, wind, dc_wp = 1000.0, 25.0, 1.0, 4000.0

        temp_cell = cell_temperature(gti, t_amb, wind)
        lossless = (
            dc_wp * (gti / G_STC) * (1 + ALPHA_TEMP * (temp_cell - TEMP_STC_CELL))
        )
        actual = gen_power(gti, t_amb, wind, 1.0, dc_wp)

        shortfall = 1 - actual / lossless
        assert 0.08 < shortfall < 0.10

    def test_efficiency_factor_still_composes(self) -> None:
        """Apply the user's efficiency factor on top of the system losses."""
        args = (700.0, 10.0, 3.0)
        full = gen_power(*args, 1.0, 3000.0)
        half = gen_power(*args, 0.5, 3000.0)
        assert abs(half - full / 2) <= 1

    def test_zero_irradiance_yields_zero(self) -> None:
        """Produce nothing in the dark regardless of losses."""
        assert gen_power(0.0, 10.0, 1.0, 1.0, 5000.0) == 0

    def test_output_scales_with_array_size(self) -> None:
        """Keep output proportional to nameplate capacity."""
        args = (600.0, 12.0, 2.0, 1.0)
        assert abs(gen_power(*args, 8000.0) - 2 * gen_power(*args, 4000.0)) <= 1


if __name__ == "__main__":
    unittest.main()

"""Tests for irradiance-dependent module efficiency.

The plain ``P = Pmax * (G / Gstc) * ...`` formula treats a module as equally
efficient in twilight as at noon, which over-predicts in dim conditions by up
to 14%.
"""

# ruff: noqa: S101

import unittest

import numpy as np

from open_meteo_solar_forecast.constants import (
    ALPHA_TEMP,
    G_STC,
    TEMP_STC_CELL,
)
from open_meteo_solar_forecast.power import gen_power_at_temp, irradiance_efficiency


class IrradianceEfficiencyTests(unittest.TestCase):
    """Verify the shape of the efficiency curve."""

    def test_exactly_unity_at_stc(self) -> None:
        """Return precisely 1.0 at 1000 W/m^2.

        Anything else would move nameplate output away from its rating. The
        raw ADR curve gives 0.99924 here, so it must be normalised.
        """
        assert abs(float(irradiance_efficiency([G_STC])[0]) - 1.0) < 1e-9

    def test_dim_light_is_penalised(self) -> None:
        """Reproduce the measured low-light shortfall."""
        expected = {50: 0.860, 100: 0.907, 200: 0.949, 400: 0.982, 600: 0.995}
        actual = irradiance_efficiency(list(expected))
        for got, want in zip(actual, expected.values(), strict=True):
            assert abs(got - want) < 0.002

    def test_monotonic_rise_through_the_working_range(self) -> None:
        """Improve steadily with light up to STC."""
        values = irradiance_efficiency([10, 50, 100, 200, 400, 600, 800, 1000])
        assert list(values) == sorted(values)

    def test_slight_sag_above_stc(self) -> None:
        """Fall back slightly beyond 1000 W/m^2, as series resistance bites."""
        assert irradiance_efficiency([1400])[0] < irradiance_efficiency([1000])[0]

    def test_never_exceeds_unity(self) -> None:
        """Never invent efficiency above the STC rating."""
        values = irradiance_efficiency(np.linspace(0, 1500, 400))
        assert values.max() <= 1.0

    def test_bounded_and_finite_for_hostile_input(self) -> None:
        """Stay finite for zero, negative and missing irradiance.

        The underlying model returns NaN for negative input.
        """
        values = irradiance_efficiency([0.0, -1.0, -500.0, np.nan, np.inf])
        assert np.isfinite(values).all()
        assert (values >= 0.0).all()
        assert (values <= 1.0).all()

    def test_length_is_preserved(self) -> None:
        """Return one factor per input."""
        assert len(irradiance_efficiency(np.linspace(0, 1200, 37))) == 37


class PowerIntegrationTests(unittest.TestCase):
    """Verify the effect on generated power."""

    def test_nameplate_is_unchanged_at_stc(self) -> None:
        """Keep STC output equal to the nameplate rating.

        This is the guard against the new factor quietly rescaling everything.
        """
        dc_wp = 5000.0
        power = gen_power_at_temp(
            G_STC, TEMP_STC_CELL, 1.0 * irradiance_efficiency([G_STC])[0], dc_wp
        )
        from open_meteo_solar_forecast.constants import DC_LOSS_FACTOR

        assert abs(power - round(dc_wp * DC_LOSS_FACTOR)) <= 1

    def test_dim_conditions_produce_less_than_the_linear_model(self) -> None:
        """Predict less than a pure irradiance ratio would, in dim light."""
        dc_wp = 5000.0
        gti = 100.0
        linear = gen_power_at_temp(gti, TEMP_STC_CELL, 1.0, dc_wp)
        corrected = gen_power_at_temp(
            gti, TEMP_STC_CELL, irradiance_efficiency([gti])[0], dc_wp
        )
        assert corrected < linear
        assert 0.88 < corrected / linear < 0.93

    def test_temperature_model_is_untouched(self) -> None:
        """Leave the documented temperature coefficient in charge.

        The ADR model carries its own, milder temperature term. Only the
        irradiance dependence is borrowed, so the ratio between a hot and a
        cold cell must still follow ALPHA_TEMP exactly.
        """
        dc_wp, gti = 5000.0, 800.0
        eta = irradiance_efficiency([gti])[0]
        cold = gen_power_at_temp(gti, TEMP_STC_CELL, eta, dc_wp)
        hot = gen_power_at_temp(gti, TEMP_STC_CELL + 30.0, eta, dc_wp)
        assert abs(hot / cold - (1 + ALPHA_TEMP * 30.0)) < 1e-3

    def test_darkness_still_produces_nothing(self) -> None:
        """Produce zero power with zero irradiance."""
        assert gen_power_at_temp(0.0, 15.0, irradiance_efficiency([0.0])[0], 5000.0) == 0


if __name__ == "__main__":
    unittest.main()

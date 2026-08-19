"""Tests for the PVWatts inverter model.

The previous implementation was a hard ``min(P, capacity)`` clip, which treats
the inverter as lossless below its rating. That over-predicts by ~4% at typical
operating points and by ~17% at low load.
"""

# ruff: noqa: S101

import unittest

from open_meteo_solar_forecast.constants import ETA_INV_NOM
from open_meteo_solar_forecast.power import inverter_ac_power, inverter_dc_input_limit


class DcInputLimitTests(unittest.TestCase):
    """Verify translation from AC nameplate to DC input limit."""

    def test_ac_rating_is_scaled_by_nominal_efficiency(self) -> None:
        """Place the AC cap exactly on the advertised rating."""
        pdc0 = inverter_dc_input_limit(5000.0, 8000.0)
        assert abs(pdc0 - 5000.0 / ETA_INV_NOM) < 1e-9
        # driving it well past the limit must saturate at the AC nameplate
        assert abs(inverter_ac_power(pdc0 * 5, pdc0) - 5000.0) < 1e-6

    def test_unlimited_capacity_falls_back_to_array_nameplate(self) -> None:
        """Size the inverter to the array when no capacity is configured."""
        assert inverter_dc_input_limit(float("inf"), 6000.0) == 6000.0

    def test_fallback_does_not_invent_aggressive_clipping(self) -> None:
        """Avoid clipping an unconfigured system at realistic irradiance.

        An array only reaches nameplate DC at 1000 W/m^2 and 25C cell
        temperature. At a realistic 85% of nameplate the model must still be on
        the efficiency curve rather than saturated.
        """
        dc_wp = 5000.0
        pdc0 = inverter_dc_input_limit(float("inf"), dc_wp)
        ac = inverter_ac_power(0.85 * dc_wp, pdc0)
        assert ac < 0.85 * dc_wp, "efficiency curve should still apply"
        assert ac > 0.80 * dc_wp, "should not be clipping this hard"


class InverterEfficiencyTests(unittest.TestCase):
    """Verify the shape of the efficiency curve."""

    def test_output_never_exceeds_input(self) -> None:
        """Respect conservation of energy across the operating range."""
        pdc0 = 5000.0
        for pdc in (1.0, 10.0, 100.0, 1000.0, 2500.0, 5000.0, 9000.0):
            assert inverter_ac_power(pdc, pdc0) < pdc

    def test_part_load_is_less_efficient_than_near_nominal(self) -> None:
        """Reproduce the characteristic part-load efficiency droop."""
        pdc0 = 5000.0
        low = inverter_ac_power(250.0, pdc0) / 250.0
        high = inverter_ac_power(4000.0, pdc0) / 4000.0
        assert low < high

    def test_beats_the_old_hard_clip_at_typical_load(self) -> None:
        """Predict measurably less than a lossless clip at a normal load."""
        pdc0, pdc = 5000.0, 2500.0
        hard_clip = min(pdc, ETA_INV_NOM * pdc0)
        modelled = inverter_ac_power(pdc, pdc0)
        shortfall = 1 - modelled / hard_clip
        assert 0.02 < shortfall < 0.08

    def test_monotonic_in_dc_input(self) -> None:
        """Never produce less AC from more DC."""
        pdc0 = 4000.0
        outputs = [inverter_ac_power(p, pdc0) for p in range(0, 8000, 100)]
        assert outputs == sorted(outputs)

    def test_saturates_at_the_ac_nameplate(self) -> None:
        """Cap the output no matter how much DC is supplied."""
        pdc0 = 3000.0
        cap = ETA_INV_NOM * pdc0
        assert abs(inverter_ac_power(1e9, pdc0) - cap) < 1e-6

    def test_over_panelled_array_clips_instead_of_collapsing(self) -> None:
        """Clip a heavily over-panelled array rather than reporting nothing.

        The PVWatts efficiency polynomial is only valid up to pdc/pdc0 ~ 1;
        far beyond it the modelled efficiency goes negative and pvlib's floor
        at zero would report a large array as producing no power at all.
        """
        pdc0 = 3000.0
        cap = ETA_INV_NOM * pdc0
        for ratio in (1.5, 5.0, 100.0, 1e6):
            assert abs(inverter_ac_power(ratio * pdc0, pdc0) - cap) < 1e-6

    def test_zero_and_negative_input_yield_zero(self) -> None:
        """Return zero rather than a negative or NaN at the origin."""
        assert inverter_ac_power(0.0, 5000.0) == 0.0
        assert inverter_ac_power(-100.0, 5000.0) == 0.0

    def test_degenerate_capacity_yields_zero(self) -> None:
        """Avoid dividing by zero when the capacity is nonsensical."""
        assert inverter_ac_power(1000.0, 0.0) == 0.0


if __name__ == "__main__":
    unittest.main()

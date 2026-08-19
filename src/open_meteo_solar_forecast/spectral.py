"""Spectral mismatch correction.

Module ratings are defined against the AM1.5 reference spectrum (1.42 cm of
precipitable water), but the real spectrum shifts with atmospheric water vapour
and with how much atmosphere the light traverses.

For crystalline silicon the correction is small and stays within roughly ±2 %.
It sits slightly below unity in very dry air and at low airmass, and slightly
above it in humid air and at high airmass:

===========  ==============
conditions   monosi factor
===========  ==============
pw 0.37 cm   0.985
pw 1.42 cm   0.997
pw 3.55 cm   1.003
AM 1.0       0.981
AM 5.0       1.040
===========  ==============

Over a year that nets out to roughly +0.3 % in a dry climate and +0.9 % in a
damp northern one. It needs no measured data: precipitable water is estimated
from temperature and relative humidity, both of which the API already returns.

References
----------
    - Gueymard, C. (1994). "Analysis of monthly average atmospheric
      precipitable water and turbidity in Canada and Northern United States".
      Solar Energy 53(1), 57-71.
    - Lee, M. and Panchula, A. (2016). "Spectral Correction for Photovoltaic
      Module Performance Based on Air Mass and Precipitable Water".
      IEEE PVSC.

"""

from __future__ import annotations

import warnings

import numpy
import pandas as pd  # noqa: TCH002 - runtime use in type conversion
from pvlib import atmosphere, spectrum

from .constants import SPECTRAL_MODULE_TYPE

# Beyond the range the model was fitted over, pvlib returns NaN. Falling back
# to 1.0 there means "no correction", which is the right neutral behaviour.
_NEUTRAL = 1.0

# Guard against implausible corrections leaking through from extreme inputs.
_MIN_FACTOR = 0.8
_MAX_FACTOR = 1.2


def spectral_factor(
    temp_air: list[float],
    relative_humidity: list[float],
    surface_pressure_hpa: list[float],
    relative_airmass: pd.Series,
    module_type: str = SPECTRAL_MODULE_TYPE,
) -> numpy.ndarray:
    """Return the spectral mismatch factor for each timestep.

    Args:
    ----
        temp_air: Ambient air temperature, °C.
        relative_humidity: Relative humidity, %.
        surface_pressure_hpa: Surface pressure in hPa, as the API reports it.
            Used to convert relative airmass to absolute, which is what the
            spectral model expects; at altitude the difference is significant.
        relative_airmass: Relative airmass, already computed for transposition.
        module_type: PV technology, as named by pvlib.

    Returns:
    -------
        Array of multiplicative factors, 1.0 meaning no correction.

    """
    pressure_pa = numpy.asarray(surface_pressure_hpa, dtype=float) * 100.0
    airmass_absolute = atmosphere.get_absolute_airmass(
        relative_airmass.to_numpy(), pressure_pa
    )

    precipitable_water = atmosphere.gueymard94_pw(
        numpy.asarray(temp_air, dtype=float),
        numpy.asarray(relative_humidity, dtype=float),
    )

    with warnings.catch_warnings():
        # pvlib warns when inputs are clipped to the fitted range. That is
        # expected at sunrise and sunset, where airmass is enormous and there
        # is almost no irradiance to correct anyway.
        warnings.simplefilter("ignore")
        factor = spectrum.spectral_factor_firstsolar(
            precipitable_water,
            airmass_absolute,
            module_type=module_type,
        )

    factor = numpy.nan_to_num(numpy.asarray(factor, dtype=float), nan=_NEUTRAL)
    return numpy.clip(factor, _MIN_FACTOR, _MAX_FACTOR)

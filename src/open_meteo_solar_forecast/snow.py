"""Snow coverage and the DC loss it causes.

The naive approach — treating the weather model's *ground* snow depth as if it
were sitting on the modules — is badly wrong. Ground snow lies for weeks, while
snow on a tilted module slides off within hours once the sun warms it. Driving
panel losses from ground depth predicted a 59% winter energy loss in Oslo where
the physical model predicts essentially none.

This module uses the NREL/Marion coverage model, which tracks snow *on the
module*: it accumulates during snowfall events and slides off at a rate set by
tilt, plane-of-array irradiance and air temperature.

References
----------
    - Marion, B. et al. (2013). "Measured and modeled photovoltaic system
      energy losses from snow for Colorado and Wisconsin locations".
      Solar Energy 97, 112-121.
    - Ryberg, D. & Freeman, J. (2017). "Integration, Validation and Application
      of a PV Snow Coverage Model in SAM". NREL/TP-6A20-68705.

"""

from __future__ import annotations

import logging

import numpy
import pandas as pd
from pvlib import snow

from .constants import SNOW_NUM_STRINGS

_LOGGER = logging.getLogger(__name__)

# The coverage model tracks accumulation and sliding across time, and pvlib
# needs to infer the sampling frequency to do so, which takes at least three
# timestamps. Real responses carry hundreds, so this only guards degenerate
# input.
_MIN_TIMESTEPS = 3


def snow_dc_loss(  # noqa: PLR0913 - each argument is a distinct physical input
    times: pd.DatetimeIndex,
    snowfall_cm: list[float],
    snow_depth_m: list[float],
    poa_irradiance: list[float],
    temp_air: list[float],
    surface_tilt: float,
    num_strings: int = SNOW_NUM_STRINGS,
) -> numpy.ndarray:
    """Fraction of DC capacity lost to snow at each timestep.

    Args:
    ----
        times: Timezone-aware index for the series below.
        snowfall_cm: Snow that fell during each interval, in cm. This is
            Open-Meteo's ``snowfall`` variable as-is; pvlib converts it to an
            hourly rate internally using the index spacing.
        snow_depth_m: Snow on the *ground* at the start of each interval, in
            metres (Open-Meteo's ``snow_depth``). Used only to suppress module
            coverage when there is too little snow around to matter.
        poa_irradiance: Plane-of-array irradiance, W/m². Drives sliding.
        temp_air: Ambient air temperature, °C. Also drives sliding.
        surface_tilt: Module tilt from horizontal in degrees. Flat modules
            never shed snow; steep ones shed quickly.
        num_strings: Parallel cell strings along the row slant height.

    Returns:
    -------
        Array of DC loss fractions in [0, 1], one per timestep.

    """
    if len(times) < _MIN_TIMESTEPS:
        # Not enough history to model accumulation or sliding. Assume no snow
        # loss rather than guessing from ground depth, which is exactly the
        # conflation this model exists to avoid.
        _LOGGER.debug(
            "Skipping snow model: need at least %d timesteps, got %d",
            _MIN_TIMESTEPS,
            len(times),
        )
        return numpy.zeros(len(times))

    # A tracker's tilt varies over time; the coverage model is validated for
    # fixed tilt, so collapse to a representative angle.
    tilt = float(numpy.mean(numpy.asarray(surface_tilt, dtype=float)))

    snowfall = pd.Series(snowfall_cm, index=times, dtype=float)
    poa = pd.Series(poa_irradiance, index=times, dtype=float)
    temp = pd.Series(temp_air, index=times, dtype=float)
    # pvlib wants ground snow depth in cm; Open-Meteo reports metres.
    depth = pd.Series(snow_depth_m, index=times, dtype=float) * 100.0

    coverage = snow.coverage_nrel(
        snowfall,
        poa,
        temp,
        tilt,
        snow_depth=depth,
    )

    loss = snow.dc_loss_nrel(coverage.to_numpy(), num_strings)
    return numpy.clip(numpy.nan_to_num(loss, nan=0.0), 0.0, 1.0)

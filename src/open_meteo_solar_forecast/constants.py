"""Constants for the solar forecast module."""

from dataclasses import dataclass

# STC specifies a cell temperature of 25°C and an irradiance of 1000 W/m².
#
# NOCT specifies a cell temperature of 45°C, an irradiance of 800 W/m²
# and an ambient temperature of 20°C.
#
# The temperature coefficient of most solar panels is 0.004°C⁻¹.
#
# Source: https://www.researchgate.net/publication/372240079_Solar_Prediction_Strategy_for_Managing_Virtual_Power_Stations


ALPHA_TEMP = -0.004  # °C-1
G_NOCT = 800.0  # W/m2
G_STC = 1000.0  # W/m2
TEMP_NOCT_AMB = 20.0  # °C
TEMP_NOCT_CELL = 45.0  # °C
TEMP_STC_CELL = 25.0  # °C


# Ross Model Constants
#
# Source: https://www.researchgate.net/publication/275438802_Thermal_effects_of_the_extended_holographic_regions_for_holographic_planar_concentrator
@dataclass
class RossModelConstants:
    """Constants for the Ross model."""

    WELL_COOLED = 0.0200
    FREE_STANDING = 0.0208
    FLAT_ON_ROOF = 0.0260
    NOT_SO_WELL_COOLED = 0.0342
    TRANSPARENT_PV = 0.0455
    FACADE_INTEGRATED = 0.0538
    ON_SLOPED_ROOF = 0.0563

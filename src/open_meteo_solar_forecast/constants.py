"""Constants for the solar forecast module."""

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

# This is used to calculate the temperature of the solar cell.
#
# Monocrystalline PV silicon cells: 15%
# Multi-crystalline (or polycrystalline) silicon: 12%
# Amorphous series of silicon: 6%
#
# Wind speed is assumed to be 1 m/s in the NOCT conditions.
#
# Source:
# - https://www.researchgate.net/publication/343126399_Effect_of_temperature_and_wind_on_PV_Module's_efficiency_Energy_and_Resource_Utilization
# - https://crimsonpublishers.com/prsp/pdf/PRSP.000528.pdf
CELL_EFFICIENCY = 0.12  # Multi-crystalline assumed
WIND_NOCT_SPEED = 1.0  # m/s
TRANSMITTANCE_ABSORPTION = 0.9  # τα

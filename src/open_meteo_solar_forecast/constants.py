"""Constants for the solar forecast module."""

# STC specifies a cell temperature of 25°C and an irradiance of 1000 W/m².
# NOCT specifies a cell temperature of 45°C and an irradiance of 800 W/m².
# The temperature coefficient of the solar panel is 0.004°C⁻¹.
#
# Source: https://www.researchgate.net/publication/372240079_Solar_Prediction_Strategy_for_Managing_Virtual_Power_Stations
ALPHA_TEMP = -0.004  # °C-1
G_NOCT = 800.0  # W/m2
G_STC = 1000.0  # W/m2
TEMP_NOCT_AMB = 20.0  # °C
TEMP_NOCT_CELL = 45.0  # °C
TEMP_STC_CELL = 25.0  # °C

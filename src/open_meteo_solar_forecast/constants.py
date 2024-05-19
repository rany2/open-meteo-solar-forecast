"""Constants for the solar forecast module."""

# Most solar PV modules have a temperature coefficient of around -0.3% / °C to -0.5% / °C.
#
# STC is an industry-wide standard to indicate the performance of PV modules and specifies
# a cell temperature of 25°C and an irradiance of 1000 W/m2 with an air mass 1.5 (AM1. 5) spectrum.
#
# Source:
#  - https://www.eco-greenenergy.com/temperature-coefficient-of-solar-pv-module/
#  - https://sinovoltaics.com/learning-center/quality/standard-test-conditions-stc-definition-and-problems/
ALPHA_TEMP = -0.05  # °C-1 (temperature coefficient)
G_STD = 1000.0  # W/m2 (standard irradiance)
TEMP_STD = 25.0  # °C (standard cell temperature)

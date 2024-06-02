"""Constants for the solar forecast module."""

# Most solar PV modules have a temperature coefficient of around -0.3%/°C to -0.5%/°C.
# Source: https://www.eco-greenenergy.com/temperature-coefficient-of-solar-pv-module/
ALPHA_TEMP = -0.005  # °C-1 (temperature coefficient)

# STC is an industry-wide standard to indicate the performance of PV modules
# and specifies cell temperature of 25°C and an irradiance of 1000 W/m2.
# Source: https://sinovoltaics.com/learning-center/quality/standard-test-conditions-stc-definition-and-problems/
G_STC = 1000.0  # W/m2 (standard irradiance)
TEMP_STC = 25.0  # °C (standard cell temperature)

# To calculate the Nominal Operating Cell Temperature (NOCT) of a solar panel,
# an irradiance of 800 W/m2 and a cell temperature of 20°C are used. Most cells
# are rated at 45°C. The NOCT is used to estimate the temperature of a solar panel
# under real-world conditions.
# Source:
#   - https://www.pveducation.org/pvcdrom/modules-and-arrays/nominal-operating-cell-temperature
#   - https://www.sciencedirect.com/science/article/pii/S2214157X21005244
G_NOCT = 800.0  # W/m2
TEMP_NOCT_AMB = 20.0  # °C
TEMP_NOCT_CELL = 45.0  # °C

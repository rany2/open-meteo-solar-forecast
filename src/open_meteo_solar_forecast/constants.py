"""Constants for the solar forecast module."""

from pvlib import pvsystem

# STC specifies a cell temperature of 25°C and an irradiance of 1000 W/m².
# The temperature coefficient of most solar panels is 0.004°C⁻¹.
# Source: https://www.researchgate.net/publication/372240079_Solar_Prediction_Strategy_for_Managing_Virtual_Power_Stations


ALPHA_TEMP = -0.004  # °C-1
G_STC = 1000.0  # W/m2
TEMP_STC_CELL = 25.0  # °C

# --------------------------------------------------------------------------
# DC system losses
# --------------------------------------------------------------------------
# Real arrays never deliver their nameplate rating: the modules are dirty,
# slightly mismatched, wired with lossy cable, and degrade over time. Ignoring
# these losses over-predicts production by roughly 9%.
#
# We use NREL's PVWatts loss model but deliberately deviate from its stock 14.1%
# default in two places, because PVWatts estimates *annual yield* while this
# library forecasts *a specific interval*:
#
#   shading = 0      PVWatts assumes a generic 3%. This library models shading
#                    explicitly via ``use_horizon``/``horizon_map``, so keeping
#                    the generic term would double-count it.
#   availability = 0 PVWatts assumes 3% for grid/inverter downtime. That is a
#                    long-run fleet average, not a prediction for any given
#                    quarter hour; baking it in would bias every forecast low.
#   snow = 0         Modelled explicitly and time-resolved in ``snow.py``.
#
# The remainder (soiling, mismatch, wiring, connections, LID, nameplate
# tolerance) are genuine steady-state derates that apply at every timestep.
PVWATTS_DC_LOSS_PERCENT = pvsystem.pvwatts_losses(
    soiling=2,
    shading=0,
    snow=0,
    mismatch=2,
    wiring=2,
    connections=0.5,
    lid=1.5,
    nameplate_rating=1,
    age=0,
    availability=0,
)

# Multiplicative form used by the power model: ~0.9132
DC_LOSS_FACTOR = 1.0 - PVWATTS_DC_LOSS_PERCENT / 100.0

# --------------------------------------------------------------------------
# Inverter
# --------------------------------------------------------------------------
# Nominal and reference efficiencies for the PVWatts inverter model. These are
# NREL's defaults, derived from a statistical analysis of inverters
# manufactured since 2010, and require no per-device calibration.
ETA_INV_NOM = 0.96
ETA_INV_REF = 0.9637

# --------------------------------------------------------------------------
# Weather models
# --------------------------------------------------------------------------
# Averaging several numerical weather predictions cancels much of the
# model-specific error, and does so without needing any measured data. Against
# satellite-observed irradiance this cuts GHI RMSE by roughly 20% versus a
# typical single model, and still beats the *best* single model at most sites -
# which matters because you cannot know in advance which model happens to be
# best at a given location.
#
# These four were chosen because each returns every variable this library needs
# at every location tested (Europe, North America, Japan, Australia, Africa,
# South America). Others were rejected on coverage: jma_seamless supplies only
# 3 of the 10 required variables outside Japan, while ukmo_seamless and
# meteofrance_seamless omit snow_depth everywhere.
DEFAULT_WEATHER_MODELS = (
    "icon_seamless",
    "gfs_seamless",
    "ecmwf_ifs025",
    "gem_seamless",
)

# --------------------------------------------------------------------------
# Snow
# --------------------------------------------------------------------------
# Parallel-connected cell strings along a row's slant height. A 60-cell module
# in portrait orientation (by far the most common residential layout) has one.
# Landscape-mounted modules typically have three, which makes snow shedding
# more granular.
SNOW_NUM_STRINGS = 1

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
# Irradiance-dependent efficiency
# --------------------------------------------------------------------------
# A module is not equally efficient at every light level. The bare
# P = Pmax * (G / Gstc) * ... formula assumes it is, which over-predicts in dim
# conditions: at 50 W/m2 a crystalline-silicon module runs about 14% below its
# STC-relative efficiency, and the shortfall only closes above ~600 W/m2.
#
# These are the ADR model parameters from pvlib's own worked example, fitted to
# an IEC 61853-1 measurement matrix for a crystalline-silicon module. They
# describe a module class rather than any particular installation, so no
# site calibration is involved.
#
# Only the *irradiance* dependence is taken from this model. ADR also carries a
# temperature term, and its implied coefficient (-0.0029 to -0.0033 /C) differs
# from ALPHA_TEMP above. Adopting the model wholesale would silently replace
# the documented temperature model, so the factor is always evaluated at
# TEMP_STC_CELL and the existing temperature term is left to do its job.
#
# Source: A. Driesse and J. S. Stein, "From IEC 61853 power measurements to PV
# system simulations", Sandia Report SAND2020-3877, 2020.
ADR_PARAMS = {
    "k_a": 0.99924,
    "k_d": -5.49097,
    "tc_d": 0.01918,
    "k_rs": 0.06999,
    "k_rsh": 0.26144,
}

# --------------------------------------------------------------------------
# Wind speed reference height
# --------------------------------------------------------------------------
# Open-Meteo reports wind at the meteorological standard of 10 m, but the
# Faiman coefficients above were determined with wind measured near module
# height. Feeding 10 m wind straight in overestimates convective cooling and
# so under-predicts cell temperature.
#
# The obvious fix - a power-law wind profile - is the wrong tool. pvlib's
# maintainers and Driesse specifically caution that such profiles "are not
# applicable close to the ground or close to the level of the objects that
# contribute to the roughness", which is exactly where PV modules live.
#
# Instead we use a fixed empirical reduction. Driesse surveys the literature
# for 10 m -> 2 m (a nominal array height) and reports ratios of 0.51, 0.56,
# 0.67 and 0.725; this is their mean. The choice within that range is not
# critical: across a full year the four values span only ~0.7 percentage
# points of predicted energy.
#
# Source: Driesse et al. (2022), "PV Module Operating Temperature Model
# Equivalence and Parameter Translation", NREL/OSTI 2003640.
WIND_SPEED_10M_TO_MODULE = 0.616

# --------------------------------------------------------------------------
# Spectral response
# --------------------------------------------------------------------------
# Sunlight's spectrum shifts with water vapour and path length, and a module
# responds to some wavelengths better than others. Crystalline silicon
# dominates residential installations, so it is assumed here.
SPECTRAL_MODULE_TYPE = "monosi"

# --------------------------------------------------------------------------
# Ground albedo
# --------------------------------------------------------------------------
# Snow-covered ground reflects far more light onto a tilted array than bare
# ground does. Typical fresh-to-settled snow albedo is 0.6-0.9; 0.65 is a
# conservative settled-snow value.
SNOW_GROUND_ALBEDO = 0.65

# Ground snow depth (m) beyond which the ground is treated as snow-covered for
# albedo purposes. Note this is about light bouncing off the *ground*, and is
# unrelated to snow sitting on the modules, which snow.py models separately.
SNOW_ALBEDO_DEPTH_M = 0.02

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
# The first four return every variable this library needs at every location
# tested (Europe, North America, Japan, Australia, Africa, South America). The
# last two omit snow_depth everywhere, which is harmless: averaging is done per
# variable, so they contribute irradiance and are simply absent from the snow
# average. jma_seamless remains excluded, supplying only 3 of the 10 required
# variables outside Japan.
#
# Widening from four to six cut GHI RMSE by a further 2.6% against
# satellite-observed irradiance, and made trimming viable (see
# ENSEMBLE_TRIM_MIN_MODELS).
DEFAULT_WEATHER_MODELS = (
    "icon_seamless",
    "gfs_seamless",
    "ecmwf_ifs025",
    "gem_seamless",
    "ukmo_seamless",
    "meteofrance_seamless",
)

# Averaging is sensitive to a single badly wrong model. Discarding the highest
# and lowest value at each timestep before averaging removes that leverage, and
# measured a further 1.1% better than the plain mean over six models.
#
# Only applied when enough models remain afterwards to still be an average:
# below this threshold the plain mean is used instead. With the default
# ensemble that means irradiance is trimmed (6 values, 4 kept) while snow_depth
# is not (4 values, all kept).
ENSEMBLE_TRIM_MIN_MODELS = 5

# --------------------------------------------------------------------------
# Snow
# --------------------------------------------------------------------------
# Parallel-connected cell strings along a row's slant height. A 60-cell module
# in portrait orientation (by far the most common residential layout) has one.
# Landscape-mounted modules typically have three, which makes snow shedding
# more granular.
SNOW_NUM_STRINGS = 1

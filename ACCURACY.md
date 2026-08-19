# Accuracy improvement study

All findings below were measured against real Open-Meteo data and
satellite-derived irradiance observations. **No PV production data is used
anywhere**, at training time or at inference time. Every proposal works for a
brand-new user on day one with no calibration period.

Measurements were taken with a throwaway harness against the Open-Meteo
forecast, historical-forecast and satellite-radiation APIs. Figures are
reproducible from the method described in each section.

---

## Verified correct (no change needed)

The 15-minute timestamp convention was checked empirically by sweeping candidate
offsets and minimising clear-sky-index spread on the clearest 25% of samples:

| Series | Best offset | Code does |
|---|---|---|
| `shortwave_radiation` (interval mean) | **−7.5 min** | `times_avg = times_inst - 7.5min` ✅ |
| `shortwave_radiation_instant` | **0 min** | `solpos_inst` at face value ✅ |

Transposition (`perez-driesse`), IAM (`physical` + `marion_diffuse`) and the
Faiman cell-temperature model are all sound choices.

---

## Tier 1 — Systematic bias. Biggest wins, smallest diffs.  ✅ IMPLEMENTED

### 1.1 There are no system losses at all — ~9 % over-prediction

`efficiency_factor` defaults to `1.0`, so the modelled array is perfect: no
soiling, wiring, mismatch, LID or nameplate tolerance losses.

PVWatts' stock default for system losses is 14.076 %, but **the shipped value is
8.68 %**. Two PVWatts components were deliberately excluded, because PVWatts
estimates *annual yield* while this library forecasts *a specific interval*:

- `shading` (3 %) — modelled explicitly here via `use_horizon`/`horizon_map`,
  so the generic term would double-count.
- `availability` (3 %) — a fleet-average allowance for grid/inverter downtime.
  It is not a prediction about any given quarter hour, and baking it in would
  bias every forecast low.

The remainder (soiling, mismatch, wiring, connections, LID, nameplate tolerance)
are genuine steady-state derates that apply at every timestep.

Implemented as `DC_LOSS_FACTOR` in `constants.py`, applied inside `gen_power`.

### 1.2 Inverter is a hard clip with no efficiency curve — a further ~4 %

`_clamp_to_inverter` did `min(P, ac_wp)`. Real inverters have a part-load
efficiency curve; `pvlib.inverter.pvwatts` models it with no fitting required.

```
Pdc    hard-clip   pvwatts     error
 200 W    200 W     166.9 W   -16.6 %
1000 W   1000 W     949.4 W    -5.1 %
5000 W   5000 W    4800.0 W    -4.0 %
```

Over a 60-day run: **−4.32 %** versus the current hard clip.

**Bug found while implementing.** pvlib's efficiency polynomial is only valid up
to `pdc/pdc0 ≈ 1`; beyond roughly 60× its linear term drives the modelled
efficiency negative, and pvlib's floor at zero then reports an over-panelled
array as producing *nothing*. `inverter_ac_power` now clips DC input to `pdc0`
first, which is also what the MPPT does physically. Regression test:
`test_over_panelled_array_clips_instead_of_collapsing`.

### 1.3 The snow model confuses ground snow with panel snow — up to −59 %

`snowcover_factor` fed `snow_depth` — which is **ground** snow depth from the
weather model — straight into a linear panel-coverage ramp. Ground snow lies for
weeks; snow on a 35–45° panel slides off within hours. Jan–Feb, `max_snowcover_depth_cm=5`:

| Site | Library linear model | `pvlib.snow.coverage_nrel` | Disagreement |
|---|---|---|---|
| Oslo | **−59.2 %** | −0.2 % | **−59.1 %** |
| Munich | −11.3 % | −2.4 % | −9.2 % |
| Denver | −4.4 % | 0.0 % | −4.4 % |

`snow.coverage_nrel(snowfall, poa, temp_air, tilt, snow_depth)` models
accumulation *and* sliding. `snowfall` was added to the fetched variables;
`snow_depth` was already present.

The `max_snowcover_depth_cm` parameter has been **removed** — the NREL model is
always on and needs no configuration.

### Measured effect of Tier 1, live API, 5 kWp / 4.5 kW AC, 67-day window

| Site | Before | After | Change |
|---|---|---|---|
| Netherlands | 1943.7 kWh | 1700.2 kWh | **−12.53 %** |
| Oslo | 1891.2 kWh | 1655.0 kWh | **−12.49 %** |
| Munich | 1876.2 kWh | 1639.1 kWh | **−12.64 %** |

That is exactly `1 − (0.9132 × 0.958)`: the DC derate and the inverter curve
compounding. The window is snow-free, so the snow fix contributes nothing here —
its effect shows up in winter, and is covered by `tests/test_snow_model.py`.

---

## Tier 2 — Better forecast inputs. The largest accuracy gain.

### 2.1 Multi-model ensemble — 19–27 % GHI RMSE reduction  ✅ IMPLEMENTED

The library rejects multiple models outright:

```python
if "," in self.weather_model:
    raise OpenMeteoSolarForecastInvalidModel("Multiple models are not supported")
```

But Open-Meteo happily serves `models=a,b,c` and returns `variable_modelname`
keys. Validated against satellite-observed GHI, May–Jul, daytime hours:

| Site | Best single | Ensemble mean | vs best | vs typical single |
|---|---|---|---|---|
| Munich | 83.2 | **72.3** | −13.1 % | −27.4 % |
| Seville | 51.9 | **50.6** | −2.6 % | −19.1 % |
| Bergen | 96.4 | **83.5** | −13.4 % | −21.8 % |

The ensemble also beats the best single model — and you cannot know in advance
*which* model is best at a user's location without validation data. Averaging
removes that gamble. One request, no extra API calls.

**Shipped default: `icon_seamless`, `gfs_seamless`, `ecmwf_ifs025`,
`gem_seamless`.** Re-validated with exactly this four-model set over Apr–Jul:

| Site | Best single | Typical single | Ensemble | vs best | vs typical |
|---|---|---|---|---|---|
| Munich | 80.0 | 96.6 | **74.5** | −6.9 % | −22.9 % |
| Seville | 68.9 | 71.9 | **60.2** | −12.5 % | −16.2 % |
| Bergen | 90.1 | 100.5 | **81.4** | −9.7 % | −19.1 % |
| Warsaw | 86.2 | 102.4 | **78.4** | −9.1 % | −23.4 % |
| Dublin | 81.7 | 103.6 | **80.8** | −1.1 % | −22.0 % |

Model selection was driven by variable coverage, measured across Europe, North
America, Japan, Australia, Africa and South America:

| Model | Variables returned | Verdict |
|---|---|---|
| icon, gfs, ecmwf, gem | 10/10 everywhere | shipped |
| ukmo, meteofrance | 9/10 (no `snow_depth`) | usable, not default |
| jma | 3/10 outside Japan | rejected |

Cost at the default window: payload 0.64 MB → 2.73 MB (5 models) or ~2.2 MB
(4 models); latency 0.7 s → 1.4 s.

**Bonus: a longer usable horizon.** Models have different forecast lengths, and
a timestamp survives if *any* model covers it. At one site `icon_seamless`
alone truncated a 16-day forecast eight days early (last usable interval
08-26), where the ensemble reached the full horizon (09-03) and retained 76 %
of raw intervals versus 67 %.

**Implementation notes.**

- Open-Meteo only suffixes response keys with the model name when *more than
  one* model is requested; a single model returns bare keys. Both are handled.
- Keys are matched by exact `variable_model` construction, never by prefix.
  Several variable names are prefixes of others, so prefix matching would fold
  every `shortwave_radiation_instant_*` series into `shortwave_radiation`.
- Averaging happens per variable and per timestep, *before* the existing
  null-row filter. Doing it after would let one all-null series from a single
  model discard the entire dataset.

### 2.2 Pre-trained bias correction (MOS) — a further ~6 %

This is where ML fits your constraint cleanly: train **once, offline, against
satellite-observed irradiance**, ship static coefficients. At runtime it is a
dot product; the user's PV output is never involved.

Leave-one-site-out over 10 European sites (held-out site never seen in training),
19,727 samples:

| Feature set | Ensemble | Ridge | GBM |
|---|---|---|---|
| lean (7 features) | 74.4 | 70.9 (−4.6 %) | 70.1 (−5.8 %) |
| rich (17 features) | 74.4 | 70.0 (−5.9 %) | **69.4 (−6.7 %)** |

Bias is nearly eliminated: MBE **−21.7 → −4.8 W/m²**.

Per-site, rich features:

```
Bergen     -15.0 %      Vienna      -6.9 %
Dublin     -11.8 %      Warsaw      -6.7 %
Helsinki   -11.3 %      Seville     -5.6 %
Rome        -5.4 %      Lisbon      -4.8 %
Athens      -0.1 %      Munich      +1.9 %   <-- regression
```

Cloudy maritime climates gain most. **Munich regresses**, so ship this behind an
opt-in flag and widen the training set before defaulting it on.

Ridge nearly matches GBM, and its coefficients are stable across folds
(cv ≤ 0.16 except the weakly-identified `kt_ens` linear term). That makes the
shippable artefact **8 floats and zero new runtime dependencies** — no
scikit-learn at inference:

```
intercept    +0.1607 +/- 0.0087
kt_ens       +0.0385 +/- 0.0511
kt_spread    -0.0399 +/- 0.0140
cosz         +0.3338 +/- 0.0290
kt_ens2      +1.3782 +/- 0.1070
kt_ens3      -0.5483 +/- 0.0492
kt_cosz      -0.3047 +/- 0.0294
cc_frac      -0.0267 +/- 0.0042
```

---

## Tier 3 — Second-order physics. Cheap, small, safe.

| # | Improvement | pvlib call | Effect |
|---|---|---|---|
| 3.1 | Wind 10 m → module height | `atmosphere.windspeed_powerlaw` | −1.10 % (annual) |
| 3.2 | Spectral correction | `spectrum.spectral_factor_firstsolar` | +0.07 % NL summer, **+2.4 % Oslo winter** |
| 3.3 | Snow-aware ground albedo | `albedo=0.65` when snow present | **+1.5 % Oslo winter** |
| 3.4 | Thermal inertia | `temperature.prilliman` | +0.05 % energy, better 15-min shape |

3.1 matters because Faiman is driven by wind at module height, but the library
passes 10 m wind unmodified, under-predicting cell temperature by 2–4 °C.

3.2 needs precipitable water, derivable from already-available data via
`atmosphere.gueymard94_pw(temp_air, relative_humidity)` — `relative_humidity_2m`,
`dew_point_2m` and `surface_pressure` are all available at `minutely_15`.

---

## Combined effect

60-day Netherlands run, 5 kWp, all Tier 1 + Tier 3 physics fixes:

```
current (with inverter clip)   1856.7 kWh
all physics fixes              1581.4 kWh   -18.51 %
```

Most of that is removing a genuine, systematic over-prediction.

---

## Compute notes (measured, Apple M4, 10 cores)

Asked whether training could use the GPU. Measured rather than assumed:

**GPU (MPS) is slower at every scale tested.** Ridge is a closed-form normal-equation
solve — memory-bandwidth bound, and dwarfed by host↔device transfer and kernel
launch overhead:

| Problem | CPU | MPS | Speedup |
|---|---|---|---|
| real (19,727 × 7) | 0.10 ms | 2.62 ms | **0.04×** |
| 100× rows (1.97 M × 7) | 11.64 ms | 15.13 ms | 0.77× |
| synthetic 2 M × 128 | 90.80 ms | 124.63 ms | 0.73× |

**Parallelising the CV folds also makes it slower**, because scikit-learn's GBM
already saturates all 10 cores through OpenMP; running folds concurrently just
creates contention, and processes additionally pickle the dataframe 10×:

| Strategy | Wall | vs serial |
|---|---|---|
| serial folds, OpenMP within | **2.8 s** | baseline |
| thread pool over folds | 10.5 s | 0.27× |
| process pool over folds | 12.1 s | 0.23× |

**The one place concurrency genuinely wins is network I/O**, which was the actual
bottleneck all along — 20 sequential API fetches at ~4 s each:

| | Wall |
|---|---|
| sequential fetch | ~40 s |
| 4-way thread pool + disk cache | **15.1 s** (2.6×) |
| cached re-run | instant |

Concurrency above 4 trips Open-Meteo's complexity-based rate limiter, so the
loader uses a semaphore and backs off on HTTP 429.

---

## Status

| Item | State |
|---|---|
| 1.1 DC system losses | ✅ implemented |
| 1.2 inverter efficiency curve | ✅ implemented |
| 1.3 NREL snow coverage | ✅ implemented |
| 2.1 multi-model ensemble | ✅ implemented |
| 3.1–3.4 second-order physics | ⬜ pending |
| 2.2 pre-trained MOS | ⬜ pending; ship opt-in until the Munich regression is understood |

Tier 1 landed together under a version bump, since it visibly lowers everyone's
forecast — correctly so.

### Tier 1 changes

```
src/open_meteo_solar_forecast/constants.py    loss + inverter constants
src/open_meteo_solar_forecast/snow.py         NEW - NREL coverage wrapper
src/open_meteo_solar_forecast/power.py        derate + inverter model
src/open_meteo_solar_forecast/open_meteo_solar_forecast.py
tests/test_losses.py                          NEW
tests/test_snow_model.py                      NEW
tests/test_inverter.py                        NEW
```

Breaking: `max_snowcover_depth_cm` removed.

# Accuracy recommendations

Open ideas for improving forecast accuracy, and a record of ideas that were
investigated and rejected so they are not re-litigated.

**Ground rule for everything here:** no improvement may depend on the user's
measured PV output. Models may be pre-trained offline against public
observations (satellite-derived irradiance, reanalysis), but must need no
calibration period and no production data from the user.

Completed work and its measurements live in [ACCURACY.md](ACCURACY.md).

| # | Recommendation | Expected gain | Scope | Status |
|---|---|---|---|---|
| 1 | Irradiance-dependent (low-light) efficiency | 0.8–1.5 % | all users | **done** |
| 2 | Horizon sky-view factor for diffuse | 0.8–13 % | `use_horizon` users | **done** |
| 3 | Satellite-observed irradiance for the recent past | large for "now" | regional | **done**, opt-in |
| 4 | Wider ensemble + trimmed mean | −3.6 % RMSE | all users | **done** |
| 5 | Instantaneous timestamp alignment | — | — | rejected |

---

## 1. Irradiance-dependent (low-light) efficiency

**Status:** done. See `irradiance_efficiency` in `power.py`.

Measured on identical cached payloads, 5 kWp / 4.5 kW AC over 67 days:

| Site | Before | After | Change |
|---|---|---|---|
| Seville | 1884.7 kWh | 1869.2 kWh | −0.82 % |
| Denver | 1737.3 kWh | 1718.9 kWh | −1.06 % |
| Netherlands | 1816.5 kWh | 1794.5 kWh | −1.21 % |
| Sydney | 1309.0 kWh | 1292.7 kWh | −1.25 % |
| Oslo | 1720.9 kWh | 1695.7 kWh | −1.46 % |

Ordered exactly as predicted: sunniest climate least affected, cloudiest most.

A deliberately mis-oriented array (south-facing in the southern hemisphere,
collecting almost pure diffuse) showed −9.6 %, which is a useful sanity check
that the correction bites hardest exactly where the light is dimmest.

The DC model is linear in irradiance:

```
P = Pdc0 * (G / 1000) * (1 + alpha * (Tcell - 25)) * eff * losses
```

This assumes a module is exactly as efficient at 50 W/m² as at 1000 W/m². It is
not. Measured with pvlib's ADR model at a fixed 25 °C, which isolates the pure
irradiance term from any temperature effect:

| POA W/m² | Relative efficiency | Currently assumed |
|---|---|---|
| 50 | 0.860 (**−14.0 %**) | 1.000 |
| 100 | 0.906 (−9.4 %) | 1.000 |
| 200 | 0.948 (−5.2 %) | 1.000 |
| 400 | 0.981 (−1.9 %) | 1.000 |
| 600 | 0.994 (−0.6 %) | 1.000 |
| 800 | 0.999 (−0.1 %) | 1.000 |
| 1000 | 0.999 (−0.1 %) | 1.000 |

Energy-weighted over 92 days this is a systematic **over-prediction of roughly
0.9 % in a sunny climate (Seville) and 2.3 % in a cloudy one (Bergen)**. The
share of annual energy arriving below 400 W/m² is what drives the difference:
about 8 % in Seville against 35 % in Bergen.

**Trap to avoid.** Adopting the whole ADR model would silently replace the
temperature model as well. Its implied temperature coefficient is −0.0029 to
−0.0033 /°C against the library's documented −0.0040 /°C:

| POA | eta(25 °C) | eta(55 °C) | implied coefficient |
|---|---|---|---|
| 200 | 0.9481 | 0.8536 | −0.00332 /°C |
| 600 | 0.9941 | 0.9044 | −0.00301 /°C |
| 1000 | 0.9992 | 0.9117 | −0.00292 /°C |

A first measurement of full ADR showed **+2.65 %** in Seville; that was mostly
the milder temperature coefficient, not low-light physics. Apply only the
irradiance term and leave the temperature model alone.

The factor must also be normalised so it is exactly 1.0 at STC, otherwise
nameplate output at 1000 W/m² and 25 °C would shift by 0.08 %.

---

## 2. Horizon sky-view factor for diffuse

**Status:** done. See `sky_view_factor` in `sun.py`.

Oslo, 5 kWp at 40°, uniform skyline, extra loss *on top of* beam blocking:

| Skyline | Beam blocking only | With sky-view factor | Extra loss |
|---|---|---|---|
| none | 1713.8 kWh | 1713.8 kWh | 0.00 % |
| 0° | 1713.8 kWh | 1713.8 kWh | 0.00 % |
| 5° | 1713.8 kWh | 1700.0 kWh | −0.81 % |
| 10° | 1713.8 kWh | 1684.0 kWh | −1.74 % |
| 15° | 1710.8 kWh | 1663.3 kWh | −2.77 % |
| 25° | 1641.9 kWh | 1554.5 kWh | −5.32 % |
| 40° | 1199.2 kWh | 1042.5 kWh | −13.07 % |

Geometry is pinned by an analytic case: for a horizontal plane under a uniform
skyline at elevation `h`, the factor has the closed form `cos^2(h)`, matched to
1e-6. The integral is cached, so it costs 2.3 ms once and 0.06 us thereafter.

Ground reflection is deliberately left unscaled. The obstruction does shade the
ground too, but `shortwave_radiation` already describes the light reaching the
location, so scaling it again would be double-counting of an uncertain size.

### Original analysis

Horizon shading currently blocks the direct beam and its circumsolar halo when
the sun sits behind the skyline. That is correct as far as it goes, but a hill
also **permanently hides part of the sky dome**. Two consequences are not
modelled:

- isotropic sky diffuse is reduced *at all times*, including when the sun is
  well clear of the obstruction, and
- ground reflection is reduced, since the obstructed ground is itself shaded.

PVsyst computes a diffuse shading factor by integrating the horizon profile
over the sky dome. The same could be done here: the horizon map already
describes the skyline, so the sky-view factor is derivable from data already
supplied.

The effect is a pure loss and grows with skyline height, so it partly
compensates the fact that the current model treats a shaded array generously.
Magnitude not yet measured.

---

## 3. Satellite-observed irradiance for the recent past

**Status:** done, behind `use_satellite=True`. See `satellite.py`.

This is the one correction that is **not** on by default, which deliberately
breaks the convention used everywhere else. Coverage is regional and the call
costs latency, so enabling it for everyone would mean a wasted round trip for
every North American user.

How far the forecast drifts from observation, which is what substitution
recovers over the elapsed window:

| Site | Ensemble RMSE | Bias | Mean observed | Relative error |
|---|---|---|---|---|
| Seville | 59.9 | −25.7 | 533.1 | 11.2 % |
| Lisbon | 64.0 | −25.8 | 525.8 | 12.2 % |
| Rome | 65.5 | −24.8 | 502.0 | 13.0 % |
| Athens | 69.6 | −20.5 | 508.0 | 13.7 % |
| Munich | 70.3 | −5.6 | 408.9 | 17.2 % |
| Warsaw | 75.0 | −12.1 | 371.5 | 20.2 % |
| Dublin | 78.8 | −21.7 | 357.7 | 22.0 % |
| Bergen | 77.4 | −13.2 | 265.7 | 29.2 % |

The bias is negative everywhere: the ensemble systematically under-predicts
irradiance against what the satellite actually saw.

`satellite_radiation_seamless` was chosen after measuring the alternatives. It
blends sources, runs at a 10-minute native step, and was only **15 minutes**
behind real time when tested. `eumetsat_sarah3` lagged two days and
`jma_jaxa_himawari` returned non-JSON, matching the open upstream report of it
being broken.

**Two traps worth recording.** Outside coverage the API answers with a body
containing a bare `NaN` literal, which is not valid JSON, so the failure
arrives as a decode error rather than anything HTTP-shaped; the handler is
broad for that reason. And the satellite cadence (10, 15 or 30 minutes) never
matches the 15-minute grid, so averaged variables are re-averaged per interval
rather than sampled.

### Original analysis

`power_production_now` and `energy_production_today_remaining` are currently
answered from a numerical weather prediction that may be hours old. For the
recent past and the current interval, a satellite-derived *observation* is far
more accurate. This is an observation rather than user production data, so it
is allowed under the ground rule.

Open-Meteo's Satellite Radiation API offers:

| Source | Region | Cadence | Delay |
|---|---|---|---|
| DWD EUMETSAT MTG | Europe, Africa | 10 min | 20 min |
| EUMETSAT MSG | Europe, Africa, South America | 15 min | 2 h |
| EUMETSAT IODC | Europe, Africa, India | 15 min | 2 h |
| JMA Himawari | Asia, Australia, New Zealand | — | — |

**Blockers.** North America is not covered at all: NASA GOES has not been
integrated. Himawari has also been reported broken since January 2026
(open-meteo/open-meteo#1683). A request for Denver returns `latitude: nan`.

So this can only ever be an opportunistic enhancement that engages where
coverage exists, never a default. It also costs an extra API call.

---

## 4. Wider ensemble and trimmed mean

**Status:** done. Default ensemble widened to six models, with outlier
trimming.

The blocker recorded below — that trimming four models leaves only two — was
dissolved by the per-variable averaging built for #2. Because each variable is
averaged over whichever models supply it, `ukmo_seamless` and
`meteofrance_seamless` can now join despite omitting `snow_depth`: they
contribute irradiance and are simply absent from the snow average.

Validated against satellite-observed irradiance over 8 sites:

| Combiner | Mean RMSE | vs 4-model mean |
|---|---|---|
| 4 models, mean (previous default) | 71.9 | — |
| 6 models, mean | 70.1 | −2.6 % |
| 6 models, trimmed | **69.3** | **−3.6 %** |

Trimming is skipped where fewer than five models supply a variable, so
irradiance is trimmed (6 values, 4 kept) while `snow_depth` is not (4 values,
all kept).

Note that the resulting *energy* figures move in both directions by site
(−2.6 % in the Netherlands, +1.1 % in Denver). That shift is a change of
ensemble composition, not the improvement; the improvement is the RMSE
reduction against observation above.

### Original analysis

Tested on 19,727 daytime samples across 10 sites, validated against
satellite-observed irradiance:

| Combiner | Mean RMSE | vs mean |
|---|---|---|
| mean | 74.4 | — |
| median | 75.3 | **+1.22 %** (worse) |
| trimmed mean (drop min and max) | 73.7 | **−0.84 %** |

The trimmed mean won at 7 of 10 sites. But the shipped default is four models,
and dropping the extreme two would leave only two contributing. Revisit if the
default ensemble grows to six or more.

---

## 5. Instantaneous timestamp alignment — REJECTED

**Status:** investigated, evidence does not support a change. Do not redo this
without new evidence.

It was suspected that `Estimate.watts` is shifted 15 minutes, because the
library stores instantaneous power at `timestamp - 15 min` while a clear-sky
sweep suggested `shortwave_radiation_instant` is valid *at* the timestamp.

Retested using the data's own internal structure rather than a clear-sky proxy:
if the average covers `[t-15, t]`, then `avg(t)` should equal the mean of the
instantaneous values at the interval ends. RMSE against that identity:

| Site | avg over [t−15, t] | avg over [t, t+15] | same timestamp |
|---|---|---|---|
| Netherlands | 28.45 | 35.57 | **9.60** |
| Seville | **4.56** | 33.20 | 14.88 |
| Bergen | 5.86 | 14.18 | **5.76** |
| Sydney | **4.82** | 23.78 | 10.56 |

The "interval start" reading is decisively wrong everywhere, which confirms the
current handling of the *averaged* series. But "interval end" versus "same
timestamp" splits two sites each, and Bergen is effectively a tie. There is no
basis for shifting the instantaneous series.

---

## Considered and ranked lower

- **Bifacial gain.** Material for bifacial arrays, and pvlib has
  `bifacial.infinite_sheds`, but it needs row pitch, module height and a
  bifaciality factor from the user.
- **Inverter standby draw and startup threshold.** Real inverters consume a few
  watts overnight and do not start until DC clears a threshold. Watts-level
  effect on a headline figure that is currently exactly zero at night.
- **Age degradation.** Around 0.5 % per year, but needs an install date.
- **Tracker row self-shading and backtracking.** Needs row geometry.

<!--
*** To avoid retyping too much info. Do a search and replace for the following:
*** github_username, repo_name
-->

## Python API fetching Solarpanels forecast information.

## About

With this python library you can request data from [Open-Meteo](https://open-meteo.com/)
and see what your solar panels may produce in the coming days.

## Installation

```bash
pip install open-meteo-solar-forecast
```

## Data

This library returns a lot of different data, based on the API:

### Energy

- Total Estimated Energy Production - today/tomorrow (kWh)
- Estimated Energy Production - This Hour (kWh)
- Estimated Energy Production - Next Hour (kWh)
- Estimated Energy Production - Remaining today (kWh)
- `Estimate.wh_period_15m`: exact modeled energy in Wh for each 15-minute
  interval, keyed by its timezone-aware interval-start timestamp. It is derived
  from the interval-average modeled power after array combination and inverter
  clipping. `Estimate.watts` is instantaneous modeled power and is not an
  equivalent source for interval energy.

### Power

- Highest Power Peak Time - Today (datetime)
- Highest Power Peak Time - Tomorrow (datetime)
- Estimated Power Production - Now (W)
- Estimated Power Production - Next Hour (W)
- Estimated Power Production - In +6 Hours (W)
- Estimated Power Production - In +12 Hours (W)
- Estimated Power Production - In +24 Hours (W)

### API Info

- Timezone
- Rate limit
- Account type
- Rate remaining

### Validation

- API key (bool)
- Plane (bool)

## Example

```python
import asyncio

from open_meteo_solar_forecast import OpenMeteoSolarForecast


async def main() -> None:
    """Show example on how to use the library."""
    async with OpenMeteoSolarForecast(
        latitude=52.16,
        longitude=4.47,
        declination=20,
        azimuth=10,
        dc_kwp=2.160,
        use_horizon=True,
        partial_shading=True,
        horizon_map=((0, 30), (360, 30)),
    ) as forecast:
        estimate = await forecast.estimate()
        print(estimate)


if __name__ == "__main__":
    asyncio.run(main())
```

| Parameter | value type | Description |
| --------- | ---------- | ----------- |
| `base_url` | `str` | The base URL of the API (optional) |
| `api_key` | `str` | Your API key (optional) |
| `weather_model` | `str \| list[str] \| tuple[str, ...]` | Weather model(s) to average over. Defaults to a four-model ensemble; see [Weather models](#weather-models) (optional) |
| `declination` | `int \| list[int] \| tuple[int, ...]` | The tilt of the solar panels (required) |
| `azimuth` | `int \| list[int] \| tuple[int, ...]` | The direction the solar panels are facing, using the Open-Meteo convention: 0 = south, -90 = east, 90 = west, ±180 = north. To convert a compass bearing (0 = north, 90 = east, 180 = south, 270 = west), subtract 180. (required) |
| `dc_kwp` | `float \| list[float] \| tuple[float, ...]` | The size of the solar panels in kWp (required) |
| `ac_kwp` | `float \| list[float \| None] \| tuple[float \| None, ...]` | The inverter capacity in kW. A scalar models a single inverter shared by all arrays (the combined output is clamped); a list/tuple models one inverter per array (each array's output is clamped individually). `None` entries mean no limit for that array. (optional, default = no limit) |
| `tracking` | `str \| list[str] \| tuple[str, ...]` | Solar tracker type: `"none"`, `"azimuth"`, `"tilt"` or `"dual"` (optional, default = "none") |
| `use_horizon` | `bool \| list[bool] \| tuple[bool, ...]` | Whether to use horizon shading (optional, default = False) |
| `partial_shading` | `bool \| list[bool] \| tuple[bool, ...]` | Whether to use interpret horizon shading as partial [experimental] (optional, default = False) |
| `horizon_map` | `tuple of 2-tuples \| list[tuple of 2-tuples]` | Map of the horizon* (required if use_horizon = True) |
| `cache_path` | `str` | Path to a file used to cache API responses between runs (optional, default = no caching) |
| `cache_prune` | `bool` | Whether to drop cached data older than the past window from disk (optional, default = True) |
| `cache_max_age` | `float` | Serve cached data without calling the API if the cache is younger than this many seconds (optional, default = always refresh) |
| `request_timeout` | `float` | Timeout in seconds for API requests (optional, default = 15.0) |

### Multiple PV arrays

To calculate a combined forecast from multiple arrays at the same location,
pass per-array values as lists or tuples for the required parameters
(`declination`, `azimuth`, and `dc_kwp`). `latitude` and `longitude` are
shared by all arrays, so the weather data is fetched only once.

```python
async with OpenMeteoSolarForecast(
    latitude=52.16,
    longitude=4.47,
    declination=[20, 35],
    azimuth=[-90, 90],  # east and west (0 = south, -90 = east, 90 = west)
    dc_kwp=[2.4, 1.8],
    # Optional per-array values can also be lists/tuples
    efficiency_factor=[0.95, 0.97],
    use_horizon=[False, True],
    horizon_map=[
        ((0, 0), (360, 0)),
        ((0, 20), (180, 10), (360, 20)),
    ],
) as forecast:
    estimate = await forecast.estimate()
```

Scalar values are still supported and are automatically applied to all arrays
when mixed with list/tuple inputs.

### Multiple inverters

If each array is connected to its own inverter, pass `ac_kwp` as a list/tuple
with one capacity per array. Each array's output is then clamped to its own
inverter capacity before the outputs are combined:

```python
async with OpenMeteoSolarForecast(
    latitude=52.16,
    longitude=4.47,
    declination=[20, 35],
    azimuth=[-90, 90],
    dc_kwp=[2.4, 1.8],
    ac_kwp=[2.0, 1.5],  # one inverter per array
) as forecast:
    estimate = await forecast.estimate()
```

Use `None` for arrays without an inverter limit, e.g. `ac_kwp=[2.0, None]`.
A scalar `ac_kwp` keeps the previous behaviour: a single inverter shared by
all arrays, clamping the combined output.

The **horizon map** is a tuple of 2-tuples, where each 2-tuple consists of (azimuth,elevation). Azimuth is the compass direction in degrees (0° = north, 180° = south). The horizon map has to cover the whole range of azimuths that the sun travels through over the year (recommendation: plot the horizon from 0 to 360°). Elevation is the associated angle in degrees of any object (hill, tree, ...) casting a shadow on the modules. The elevation angle has to be in the range 0° (flat, ideal horizon) to 90° (in the sky directly over the modules). The map has to be monotonic on the azimuth axis, however this is not checked by the script! Elevation values in between are interpolated along the azimuth axis, thus non-monotonic values will give wrong results. The horizon map can also be passed from a text file, see the included example estimate_horizon.py.

If **partial_shading** is disabled and a shadow is detected on the module, only the diffuse irradiation will be used to calculate the power output. This is useful if the shading is predominantly from far-away objects, which can be treated as shading the whole module at once or not. If partial_shading is enabled and a shadow is detected on the module, the shadow is treated as partial. This is useful if the shading arises from close-by objects, which cast 'hard' contoured shadows on the module. In this case, an experimental calculation is used taking into account the 'sunniness' of the conditions. This is done via the ratio of diffuse and direct irradiation. A large share of diffuse irradiation (cloudy day) will let the module run as homogeneously shaded at diffuse power. A small share of diffuse irradiation (sunny) day will reduce the diffuse power even more, since hard partial shadows can shut down the module completely.

If **tracking** is set to a value other than `"none"`, the irradiance is calculated for a panel that follows the sun on the given axis. `"azimuth"` models a vertical-axis (east-west) tracker and ignores the `azimuth` parameter, `"tilt"` models a tilt-axis tracker and ignores the `declination` parameter, and `"dual"` models a dual-axis tracker and ignores both. Like the other per-array parameters, it can be passed as a list/tuple for multiple arrays.

### Weather models

By default the forecast is averaged over four numerical weather models:
`icon_seamless`, `gfs_seamless`, `ecmwf_ifs025` and `gem_seamless`.

Averaging cancels much of each model's individual error. Measured against
satellite-observed irradiance, the ensemble cuts GHI RMSE by roughly **20%**
versus a typical single model, and still beats the *best* single model at most
locations — which matters because you cannot know in advance which model happens
to be best where you live. The spread is not subtle: for one 6-day window in the
Netherlands, `icon_seamless` predicted 81.7 kWh while `gfs_seamless` predicted
125.4 kWh for the same array.

These four were chosen because each supplies every variable the model needs at
every location tested. Others were rejected on coverage: `jma_seamless` returns
only 3 of the 10 required variables outside Japan, and `ukmo_seamless` and
`meteofrance_seamless` omit `snow_depth` everywhere.

The cost is one larger request per refresh — about 2.2 MB instead of 0.64 MB,
and roughly 1.3 s instead of 0.7 s. If that matters, request a single model:

```python
async with OpenMeteoSolarForecast(
    ...,
    weather_model="icon_seamless",
) as forecast:
    estimate = await forecast.estimate()
```

Or choose your own ensemble, as a list or a comma-separated string:

```python
weather_model=["icon_seamless", "ecmwf_ifs025"]
weather_model="icon_seamless,ecmwf_ifs025"
```

Each variable is averaged over the models that actually return it, so a model
missing one field still contributes the rest. An error is raised only if no
requested model supplies a required variable. Changing the selection
invalidates any cached response automatically.

A useful side effect: models have different forecast horizons, and a timestamp
survives as long as *any* model covers it. Requesting `icon_seamless` alone
truncated one 16-day forecast eight days early, where the ensemble reached the
full horizon.

### Modelled losses

These are applied automatically and need no configuration or calibration.

**DC system losses.** A real array never delivers its nameplate rating, so a
fixed derate of ~8.7% covers soiling, module mismatch, wiring, connections,
light-induced degradation and nameplate tolerance. The figure comes from NREL's
PVWatts loss model, but deliberately excludes two of its components: *shading*,
because this library models shading explicitly via `horizon_map`, and
*availability*, because a fleet-average outage allowance does not belong in a
per-interval forecast. Use `efficiency_factor` to layer additional site-specific
derating on top.

**Inverter efficiency.** DC is converted to AC with the PVWatts inverter model
rather than a hard clip, so part-load efficiency is represented — an inverter is
noticeably less efficient at 5% load than at 80%. Output saturates at the
`ac_kwp` you configure. When `ac_kwp` is omitted, the inverter is sized to the
array nameplate, which applies a realistic efficiency curve without inventing a
clipping threshold.

**Wind speed height.** The cell-temperature model's coefficients were derived
with wind measured near module height, but the API reports the meteorological
standard of 10 m. Wind is therefore scaled by a fixed empirical factor before
use. A wind-profile power law is deliberately *not* used: such profiles are not
valid close to the ground, where modules actually sit. The factor is the mean of
values reported in the literature; the spread between them is worth only about
0.7 percentage points of annual energy.

**Spectral response.** Modules are rated against the AM1.5 reference spectrum,
but the real spectrum shifts with atmospheric water vapour and path length. The
correction is small for silicon (within about ±2%) and is derived from
temperature, humidity and pressure, all fetched automatically.

**Ground albedo.** Snow-covered ground reflects far more light onto a tilted
array than bare ground, so the albedo is raised automatically when snow is
lying. This is distinct from snow *on the modules*, below.

**Thermal inertia.** Modules have real thermal mass, so their temperature lags
the conditions driving it. This barely affects total energy (~0.05%) but
matters for instantaneous power under broken cloud, where the steady-state and
lagged temperatures can differ by several degrees. It is applied only to
`watts`, not to interval energy, where the lag averages out.

**Snow.** Snow coverage is tracked *on the modules* using the NREL/Marion model:
it accumulates during snowfall and slides off at a rate set by tilt,
plane-of-array irradiance and air temperature. This matters because snow on the
ground is a poor proxy for snow on a panel — ground snow lies for weeks, while a
tilted module sheds within hours of the sun reaching it. No configuration is
needed; the required `snowfall` and `snow_depth` data is fetched automatically.

## Contributing

Would you like to contribute to the development of this project? Then read the prepared [contribution guidelines](CONTRIBUTING.md) and go ahead!

Thank you for being involved! :heart_eyes:

## Setting up development environment

This Python project uses [uv][uv] as its dependency manager.

You need at least:

- Python 3.11+
- [uv][uv-install]

Install all packages, including all development requirements:

```bash
uv sync
```

uv creates a virtual environment in `.venv` where it installs all
necessary packages. Run commands inside it with:

```bash
uv run python
```

## License

MIT License

Copyright (c) 2021-2024 Klaas Schoute  
Copyright (c) 2024 Rany

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

[uv-install]: https://docs.astral.sh/uv/getting-started/installation/
[uv]: https://docs.astral.sh/uv/

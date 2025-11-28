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
        horizon_map=((0,30),(360,30),
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
| `declination` | `int` | The tilt of the solar panels (required) |
| `azimuth` | `int` | The direction the solar panels are facing (required) |
| `dc_kwp` | `float` | The size of the solar panels in kWp (required) |
| `use_horizon` | `bool` | Whether to use horizon shading (optional, default = False) |
| `horizon_map` | `tuple of 2-tuples` | Map of the horizon* (required if use_horizon = True) |

*) The horizon map is a tuple of 2-tuples, where each 2-tuple consists of (azimuth,elevation). Azimuth is the compass direction in degrees (0° = north, 180° = south). The horizon map has to cover the whole range of azimuths that the sun travels through over the year (recommendation: plot the horizon from 0 to 360°). Elevation is the associated angle in degrees of any object (hill, tree, ...) casting a shadow on the modules. The elevation angle has to be in the range 0° (flat, ideal horizon) to 90° (in the sky directly over the modules). The map has to be monotonic on the azimuth axis, however this is not checked by the script! Elevation values in between are interpolated along the azimuth axis, thus non-monotonic values will give wrong results. The horizon map can also be passed from a text file, see the included example estimate_horizon.py.

## Contributing

Would you like to contribute to the development of this project? Then read the prepared [contribution guidelines](CONTRIBUTING.md) and go ahead!

Thank you for being involved! :heart_eyes:

## Setting up development environment

This Python project relies on [Poetry][poetry] as its dependency manager,
providing comprehensive management and control over project dependencies.

You need at least:

- Python 3.11+
- [Poetry][poetry-install]

Install all packages, including all development requirements:

```bash
poetry install
```

Poetry creates by default an virtual environment where it installs all
necessary pip packages, to enter or exit the venv run the following commands:

```bash
poetry shell
exit
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

[poetry-install]: https://python-poetry.org/docs/#installation
[poetry]: https://python-poetry.org

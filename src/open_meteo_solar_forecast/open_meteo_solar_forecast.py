"""Asynchronous Python client for the API."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, timedelta, timezone
from datetime import datetime as dt
from typing import Any, NamedTuple, Self

import numpy
import pandas as pd
from aiohttp import ClientError, ClientSession, ClientTimeout
from pvlib import atmosphere

from .cache import (
    SECONDS_PER_DAY,
    CacheEntry,
    ResponseCache,
    fingerprint,
    merge_series,
    prune_before,
)
from .constants import SNOW_ALBEDO_DEPTH_M, SNOW_GROUND_ALBEDO
from .exceptions import (
    OpenMeteoSolarForecastAuthenticationError,
    OpenMeteoSolarForecastConfigError,
    OpenMeteoSolarForecastConnectionError,
    OpenMeteoSolarForecastError,
    OpenMeteoSolarForecastInvalidModel,
    OpenMeteoSolarForecastRatelimitError,
    OpenMeteoSolarForecastRequestError,
)
from .models import Estimate
from .params import (
    is_list_like,
    normalize_param,
    normalize_required,
    normalize_weather_models,
    validate_ac_kwp,
    validate_albedo,
    validate_azimuth,
    validate_tracking,
)
from .power import (
    _quarter_hour_energy,
    calculate_damping_coefficient,
    cell_temperature_series,
    daily_energy,
    gen_power_at_temp,
    hourly_average_power,
    inverter_ac_power,
    inverter_dc_input_limit,
    irradiance_efficiency,
    module_wind_speed,
)
from .snow import snow_dc_loss
from .spectral import spectral_factor
from .sun import (
    PlaneIrradiance,
    build_sun_times,
    check_horizon_shading,
    compute_gti,
    solar_position,
)

__all__ = ["OpenMeteoSolarForecast", "_quarter_hour_energy"]

_LOGGER = logging.getLogger(__name__)


class _ArraySeries(NamedTuple):
    """Vectorised per-timestep series precomputed for a single PV array."""

    irr_avg: numpy.ndarray
    irr_inst: numpy.ndarray
    damping: list[float]
    snow_loss: numpy.ndarray
    tcell_avg: numpy.ndarray
    tcell_inst: numpy.ndarray
    eta_irr_avg: numpy.ndarray
    eta_irr_inst: numpy.ndarray
    dc_wp: float
    pdc0: float | None


@dataclass
class OpenMeteoSolarForecast:
    """Main class for handling connections with the API."""

    azimuth: float | list[float]
    declination: float | list[float]
    dc_kwp: float | list[float]
    latitude: float
    longitude: float

    past_days: int = 92
    forecast_days: int = 16

    ac_kwp: float | list[float | None] | None = None
    api_key: str | None = None
    base_url: str | None = None
    weather_model: str | list[str] | tuple[str, ...] | None = None
    damping_morning: float | list[float] = 0.0
    damping_evening: float | list[float] = 0.0
    efficiency_factor: float | list[float] = 1.0
    tracking: str | list[str] = "none"
    use_horizon: bool | list[bool] = False
    partial_shading: bool | list[bool] = False
    horizon_map: tuple(tuple(float)) | list[tuple(tuple(float))] = ((0.0,20.0),(360.0,20.0))
    albedo: float | list[float] = 0.25
    cache_path: str | None = None
    cache_prune: bool = True
    cache_max_age: float | None = None
    request_timeout: float = 15.0

    session: ClientSession | None = None
    _close_session: bool = False

    def __post_init__(self) -> None:
        """Initialize the OpenMeteoSolarForecast object."""
        if self.base_url is None:
            self.base_url = "https://api.open-meteo.com"
        if self.ac_kwp is None:
            self.ac_kwp = float("inf")

        self.weather_model = normalize_weather_models(self.weather_model)

        self._normalize_required_params()
        self._normalize_optional_params()

    def _normalize_required_params(self) -> None:
        for attr_name in ("latitude", "longitude"):
            if is_list_like(getattr(self, attr_name)):
                raise OpenMeteoSolarForecastConfigError(
                    f"{attr_name} must be a single value shared by all arrays"
                )

        required_attr_names = (
            "azimuth",
            "declination",
            "dc_kwp",
        )
        required_values = [
            getattr(self, attr_name) for attr_name in required_attr_names
        ]
        target_len = max(
            len(value) if is_list_like(value) else 1 for value in required_values
        )

        for attr_name in required_attr_names:
            setattr(
                self,
                attr_name,
                normalize_required(attr_name, getattr(self, attr_name), target_len),
            )
        validate_azimuth(self.azimuth)

    def _normalize_optional_params(self) -> None:
        def normalize(attr_name: str, *, tuple_as_list: bool = True) -> list[Any]:
            return normalize_param(
                attr_name,
                getattr(self, attr_name),
                len(self.dc_kwp),
                tuple_as_list=tuple_as_list,
            )

        self.efficiency_factor = normalize("efficiency_factor")
        self.tracking = normalize("tracking")
        validate_tracking(self.tracking)
        self.damping_morning = normalize("damping_morning")
        self.damping_evening = normalize("damping_evening")
        self.use_horizon = normalize("use_horizon")
        self.partial_shading = normalize("partial_shading")
        self.horizon_map = normalize("horizon_map", tuple_as_list=False)
        self.albedo = normalize("albedo")
        validate_albedo(self.albedo)

        # A scalar ac_kwp models a single shared inverter that clamps the
        # combined output of all arrays. A list/tuple models one inverter per
        # array, clamping each array's output individually. None entries mean
        # that array's inverter capacity is unlimited.
        self.shared_inverter = not is_list_like(self.ac_kwp)
        self.ac_kwp = [
            float("inf") if cap is None else cap for cap in normalize("ac_kwp")
        ]
        validate_ac_kwp(self.ac_kwp)

    async def _request(
        self,
        uri: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Handle a request to the API.

        A generic method for sending/handling HTTP requests done against the API.

        Args:
        ----
            uri: Request URI, for example, '/v1/forecast'.

        Returns:
        -------
            A Python dictionary (JSON decoded) with the response from the API.

        Raises:
        ------
            OpenMeteoSolarForecastAuthenticationError: If the API key is invalid.
            OpenMeteoSolarForecastConnectionError: An error occurred while communicating
                with the API.
            OpenMeteoSolarForecastError: Received an unexpected response from the API.
            OpenMeteoSolarForecastRequestError: There is something wrong with the
                variables used in the request.
            OpenMeteoSolarForecastRatelimitError: The number of requests has exceeded
                the rate limit of the API.

        """
        if self.session is None:
            self.session = ClientSession()
            self._close_session = True

        if self.api_key:
            params = params or {}
            params["apikey"] = self.api_key

        if self.weather_model:
            params = params or {}
            params["models"] = ",".join(self.weather_model)

        response = await self.session.request(
            "GET",
            self.base_url + uri,
            params=params,
            timeout=ClientTimeout(total=self.request_timeout),
        )

        self._raise_for_response_status(response.status)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            text = await response.text()
            raise OpenMeteoSolarForecastError(
                "Unexpected response from the API",
                {"Content-Type": content_type, "response": text},
            )

        return await response.json()

    @staticmethod
    def _raise_for_response_status(status: int) -> None:
        if status in (502, 503):
            raise OpenMeteoSolarForecastConnectionError("The API is unreachable")

        if status == 400:
            raise OpenMeteoSolarForecastRequestError("Bad request")

        if status in (401, 403):
            raise OpenMeteoSolarForecastAuthenticationError("Invalid API key")

        if status == 422:
            raise OpenMeteoSolarForecastConfigError("Invalid configuration")

        if status == 429:
            raise OpenMeteoSolarForecastRatelimitError("Rate limit exceeded")

    def _array_params(self) -> list[dict[str, Any]]:
        names = (
            "azimuth",
            "declination",
            "dc_kwp",
            "efficiency_factor",
            "tracking",
            "damping_morning",
            "damping_evening",
            "use_horizon",
            "partial_shading",
            "horizon_map",
            "albedo",
            "ac_kwp",
        )
        values = zip(*(getattr(self, name) for name in names), strict=True)
        return [dict(zip(names, row, strict=True)) for row in values]

    MINUTELY_15_VARS = (
        "temperature_2m",
        "shortwave_radiation",
        "shortwave_radiation_instant",
        "diffuse_radiation",
        "diffuse_radiation_instant",
        "direct_normal_irradiance",
        "direct_normal_irradiance_instant",
        "snowfall",
        "snow_depth",
        "wind_speed_10m",
        "relative_humidity_2m",
        "surface_pressure",
    )

    def _forecast_params(self, past_days: int) -> dict[str, str]:
        return {
            "latitude": str(self.latitude),
            "longitude": str(self.longitude),
            "minutely_15": ",".join(self.MINUTELY_15_VARS),
            "wind_speed_unit": "ms",
            "forecast_days": str(self.forecast_days),
            "past_days": str(past_days),
            "timezone": "auto",
            "timeformat": "unixtime",
        }

    def _cache_fingerprint(self) -> str:
        """Fingerprint of every parameter that must invalidate the cache."""
        return fingerprint(
            {
                "latitude": str(self.latitude),
                "longitude": str(self.longitude),
                "minutely_15": ",".join(self.MINUTELY_15_VARS),
                "wind_speed_unit": "ms",
                "timeformat": "unixtime",
                "base_url": self.base_url,
                "weather_model": list(self.weather_model),
            }
        )

    def _window_start(self, now_ts: float, utc_offset: int) -> float:
        """Timestamp of local midnight ``past_days`` ago (API window start)."""
        local_now = now_ts + utc_offset
        local_midnight = local_now - (local_now % SECONDS_PER_DAY)
        return local_midnight - self.past_days * SECONDS_PER_DAY - utc_offset

    async def _fetch_forecast(self) -> Any:
        if self.cache_path is None:
            return await self._request(
                "/v1/forecast",
                params=self._forecast_params(self.past_days),
            )
        return await self._fetch_forecast_cached()

    async def _fetch_forecast_cached(self) -> Any:
        """Fetch the forecast, reusing cached past data where possible.

        If ``cache_max_age`` is set and the cache was refreshed within
        that many seconds, the API is not contacted at all and the
        cached data is served directly. Otherwise, when the cache
        already covers the requested past window, only the days elapsed
        since the last refresh are re-requested and merged into the
        cached series. On retryable request failures the cached data is
        served instead of raising.
        """
        cache = ResponseCache(self.cache_path)
        params_hash = self._cache_fingerprint()
        entry = cache.read(params_hash)
        now_ts = dt.now(UTC).timestamp()

        if (
            entry is not None
            and self.cache_max_age is not None
            and now_ts - entry.refreshed_at < self.cache_max_age
        ):
            _LOGGER.debug(
                "Cache is fresh (refreshed at %s, max age %ss); "
                "skipping API request",
                dt.fromtimestamp(entry.refreshed_at, UTC).isoformat(),
                self.cache_max_age,
            )
            return prune_before(
                entry.data, self._window_start(now_ts, entry.utc_offset)
            )

        past_days = self.past_days
        if entry is not None and entry.times[0] <= self._window_start(
            now_ts, entry.utc_offset
        ):
            # Cache covers the whole past window; only re-request stale days.
            stale = max(0.0, now_ts - entry.refreshed_at)
            past_days = min(self.past_days, math.ceil(stale / SECONDS_PER_DAY))

        try:
            data = await self._request(
                "/v1/forecast",
                params=self._forecast_params(past_days),
            )
        except (OpenMeteoSolarForecastError, ClientError, TimeoutError) as err:
            if entry is None or not getattr(err, "retryable", True):
                raise
            _LOGGER.warning(
                "Open-Meteo request failed (%s); falling back to cache "
                "refreshed at %s",
                err,
                dt.fromtimestamp(entry.refreshed_at, UTC).isoformat(),
            )
            return prune_before(
                entry.data, self._window_start(now_ts, entry.utc_offset)
            )

        if entry is not None:
            data = merge_series(entry.data, data)
        trimmed = prune_before(
            data, self._window_start(now_ts, data.get("utc_offset_seconds", 0))
        )

        cache.write(
            params_hash,
            CacheEntry(
                data=trimmed if self.cache_prune else data,
                refreshed_at=now_ts,
            ),
        )

        return trimmed

    def _model_series_keys(
        self, minutely: dict[str, list[Any]], variable: str
    ) -> list[str]:
        """Response keys holding *variable*, one per contributing model.

        Open-Meteo only suffixes keys with the model name when more than one
        model is requested; a single model returns the bare variable name.

        Matching is by exact ``variable_model`` construction rather than by
        prefix, because several variables are prefixes of others -
        ``shortwave_radiation`` would otherwise also capture every
        ``shortwave_radiation_instant_*`` series.
        """
        keys = [
            key
            for key in (f"{variable}_{model}" for model in self.weather_model)
            if key in minutely
        ]
        if not keys and variable in minutely:
            keys = [variable]
        return keys

    def _collapse_ensemble(
        self, minutely: dict[str, list[Any]]
    ) -> dict[str, list[Any]]:
        """Average each variable across the models that supplied it.

        Averaging is per variable and per timestep over whatever is actually
        present, so a model that omits one field still contributes everything
        else. This matters in practice: several models return no ``snow_depth``
        at all, and dropping them wholesale would discard good irradiance.
        """
        collapsed: dict[str, list[Any]] = {"time": minutely["time"]}
        steps = len(minutely["time"])

        for variable in self.MINUTELY_15_VARS:
            keys = self._model_series_keys(minutely, variable)
            if not keys:
                msg = (
                    f"No requested weather model returned {variable!r}. "
                    f"Requested models: {', '.join(self.weather_model)}"
                )
                raise OpenMeteoSolarForecastInvalidModel(msg)

            if len(keys) == 1:
                collapsed[variable] = minutely[keys[0]]
                continue

            series = [minutely[key] for key in keys]
            averaged: list[Any] = []
            for i in range(steps):
                present = [s[i] for s in series if s[i] is not None]
                averaged.append(sum(present) / len(present) if present else None)
            collapsed[variable] = averaged

        self._warn_on_absent_models(minutely)
        return collapsed

    def _warn_on_absent_models(self, minutely: dict[str, list[Any]]) -> None:
        """Log models that contributed nothing, so silent gaps are visible."""
        if len(self.weather_model) == 1:
            return
        for model in self.weather_model:
            supplied = [
                variable
                for variable in self.MINUTELY_15_VARS
                if any(
                    value is not None
                    for value in minutely.get(f"{variable}_{model}", [])
                )
            ]
            if not supplied:
                _LOGGER.warning(
                    "Weather model %r returned no usable data for this "
                    "location and was excluded from the ensemble",
                    model,
                )
            elif len(supplied) < len(self.MINUTELY_15_VARS):
                missing = set(self.MINUTELY_15_VARS) - set(supplied)
                _LOGGER.debug(
                    "Weather model %r supplied no %s; averaging those "
                    "variables over the remaining models",
                    model,
                    ", ".join(sorted(missing)),
                )

    @staticmethod
    def _drop_null_entries(minutely: dict[str, list[Any]]) -> dict[str, list[Any]]:
        """Remove timestamps where any weather variable is null.

        The API may return null for some variables (typically at the far end
        of the forecast horizon or for past data gaps). Since every variable
        is required for the forecast generation, drop those timestamps
        entirely so all arrays stay aligned.
        """
        keys = list(minutely.keys())
        valid_idx = [
            i
            for i in range(len(minutely["time"]))
            if all(minutely[key][i] is not None for key in keys)
        ]
        if len(valid_idx) == len(minutely["time"]):
            return minutely
        if not valid_idx:
            raise OpenMeteoSolarForecastError(
                "API returned no complete data points"
            )
        return {key: [minutely[key][i] for i in valid_idx] for key in keys}

    def _prepare_weather(self, data: Any, tz: timezone) -> dict[str, Any]:
        """Prepare location-wide weather and solar geometry shared by all arrays."""
        minutely = self._drop_null_entries(
            self._collapse_ensemble(data["minutely_15"])
        )

        time_arr = [
            dt.fromtimestamp(ts, UTC).astimezone(tz)
            for ts in minutely["time"]
        ]

        # Averaged values cover the preceding 15 minutes, so use the midpoint.
        times_inst = pd.to_datetime(minutely["time"], unit="s", utc=True)
        times_avg = times_inst - pd.Timedelta(minutes=7.5)

        daily_dates = sorted({t.date() for t in time_arr})
        sunrise_dict, sunset_dict = build_sun_times(
            daily_dates, self.latitude, self.longitude, tz
        )

        solpos_inst = solar_position(times_inst, self.latitude, self.longitude)
        solpos_avg = solar_position(times_avg, self.latitude, self.longitude)

        # Faiman's coefficients expect wind at module height, not the 10 m
        # meteorological standard the API reports.
        wind_module = [module_wind_speed(w) for w in minutely["wind_speed_10m"]]

        # Spectral mismatch depends on path length and water vapour, neither of
        # which varies by array, so compute it once for the whole location.
        spectral = spectral_factor(
            minutely["temperature_2m"],
            minutely["relative_humidity_2m"],
            minutely["surface_pressure"],
            atmosphere.get_relative_airmass(solpos_avg["apparent_zenith"]),
        )

        # Snow on the ground reflects far more onto a tilted array than bare
        # ground. This is about the ground, not the modules; snow.py handles
        # what settles on the panels.
        ground_is_snowy = (
            numpy.asarray(minutely["snow_depth"], dtype=float) > SNOW_ALBEDO_DEPTH_M
        )

        # Ambient temperature aligned to each interval. Averaged irradiance
        # pairs with the interval mean; instantaneous irradiance pairs with the
        # value at the interval start.
        temp = numpy.asarray(minutely["temperature_2m"], dtype=float)
        temp_interval_mean = temp.copy()
        temp_interval_mean[1:] = (temp[1:] + temp[:-1]) / 2.0
        temp_interval_start = temp.copy()
        temp_interval_start[1:] = temp[:-1]

        return {
            "minutely": minutely,
            "time_arr": time_arr,
            "times_index": times_inst,
            "solpos_inst": solpos_inst,
            "solpos_avg": solpos_avg,
            "sunrise": sunrise_dict,
            "sunset": sunset_dict,
            "wind_module": wind_module,
            "spectral": spectral,
            "ground_is_snowy": ground_is_snowy,
            "temp_interval_mean": temp_interval_mean,
            "temp_interval_start": temp_interval_start,
        }

    def _array_series(
        self, array: dict[str, Any], weather: dict[str, Any]
    ) -> _ArraySeries:
        """Precompute the vectorised per-timestep series for one array.

        Everything here is computed across the whole horizon at once (plane-of
        -array transposition, damping, snow coverage, horizon shading) so that
        the accumulation loop only has to index into the results.
        """
        minutely = weather["minutely"]
        time_arr = weather["time_arr"]
        solpos_inst = weather["solpos_inst"]

        # Raise the ground albedo where there is snow lying, which materially
        # increases what a tilted array collects in winter.
        albedo = numpy.where(
            weather["ground_is_snowy"], SNOW_GROUND_ALBEDO, array["albedo"]
        )
        array = {**array, "albedo": albedo}

        plane_avg = compute_gti(
            weather["solpos_avg"],
            minutely["shortwave_radiation"],
            minutely["diffuse_radiation"],
            minutely["direct_normal_irradiance"],
            array,
        )
        plane_inst = compute_gti(
            solpos_inst,
            minutely["shortwave_radiation_instant"],
            minutely["diffuse_radiation_instant"],
            minutely["direct_normal_irradiance_instant"],
            array,
        )

        sunrise_dict = weather["sunrise"]
        sunset_dict = weather["sunset"]
        damping_factors = [
            calculate_damping_coefficient(
                t,
                sunrise_dict[t.date()],
                sunset_dict[t.date()],
                array["damping_morning"],
                array["damping_evening"],
            )
            for t in time_arr
        ]

        if array["use_horizon"]:
            hmap_arr = numpy.array(array["horizon_map"]).T
            # Evaluate shading against the sun position each branch is built
            # on: the interval midpoint for averages, the timestamp itself for
            # instantaneous values.
            shading_avg = check_horizon_shading(weather["solpos_avg"], hmap_arr)
            shading_inst = check_horizon_shading(solpos_inst, hmap_arr)
        else:
            shading_avg = numpy.zeros(len(time_arr), dtype=bool)
            shading_inst = shading_avg

        irr_avg_arr = self._effective_irradiance(
            plane_avg,
            minutely["shortwave_radiation"],
            minutely["diffuse_radiation"],
            shading_avg,
            array,
        )
        irr_inst_arr = self._effective_irradiance(
            plane_inst,
            minutely["shortwave_radiation_instant"],
            minutely["diffuse_radiation_instant"],
            shading_inst,
            array,
        )

        # Spectral mismatch applies to whatever light actually reaches the
        # cell, so it is applied after the shading branch is resolved.
        spectral = weather["spectral"]
        irr_avg_arr = irr_avg_arr * spectral
        irr_inst_arr = irr_inst_arr * spectral

        times = weather["times_index"]
        wind_module = weather["wind_module"]
        tcell_avg = cell_temperature_series(
            times, irr_avg_arr, weather["temp_interval_mean"], wind_module
        )
        # Thermal inertia only makes sense for an instantaneous reading; over
        # an interval average the lag cancels out.
        tcell_inst = cell_temperature_series(
            times,
            irr_inst_arr,
            weather["temp_interval_start"],
            wind_module,
            thermal_inertia=True,
        )

        dc_wp = array["dc_kwp"] * 1000

        return _ArraySeries(
            irr_avg=irr_avg_arr,
            irr_inst=irr_inst_arr,
            damping=damping_factors,
            snow_loss=self._array_snow_loss(
                array, weather, plane_avg.total.to_numpy().tolist()
            ),
            tcell_avg=tcell_avg,
            tcell_inst=tcell_inst,
            # Modules are less efficient in dim light than the plain
            # irradiance ratio implies.
            eta_irr_avg=irradiance_efficiency(irr_avg_arr),
            eta_irr_inst=irradiance_efficiency(irr_inst_arr),
            dc_wp=dc_wp,
            # Per-array inverter (only when per-array capacities are given; a
            # shared inverter converts the combined DC output later).
            pdc0=(
                None
                if self.shared_inverter
                else inverter_dc_input_limit(array["ac_kwp"] * 1000, dc_wp)
            ),
        )

    @staticmethod
    def _effective_irradiance(
        plane: PlaneIrradiance,
        ghi: list[float],
        dhi: list[float],
        horizon_shading: numpy.ndarray,
        array: dict[str, Any],
    ) -> numpy.ndarray:
        """Irradiance reaching the modules once horizon shading is applied.

        Where the horizon hides the sun the array falls back to the
        beam-blocked plane-of-array value, which drops the direct beam and its
        circumsolar halo but keeps isotropic sky, horizon brightening and
        ground reflection. Because that is by construction a subset of the
        unobstructed total, shading can only ever reduce output.

        With ``partial_shading`` the remaining diffuse is scaled further by how
        diffuse the sky is overall.

        --- experimental empiric partial shading approach ---
        On a sunny day (low diffuse fraction) 'hard' shadows make the bypass
        diodes shut the module down almost completely. On a cloudy day (high
        diffuse fraction) there are no hard shadows and the module runs at pure
        diffuse power. In between, the effect is assumed proportional.
        Inspired by https://pvlib-python.readthedocs.io/en/stable/gallery/shading/plot_partial_module_shading_simple.html#calculating-shading-loss-across-shading-scenarios
        """
        total = plane.total.to_numpy()
        if not array["use_horizon"] or not horizon_shading.any():
            return total

        shaded = plane.beam_blocked.to_numpy()
        if array["partial_shading"]:
            diffuse = numpy.asarray(dhi, dtype=float)
            direct = numpy.asarray(ghi, dtype=float) - diffuse
            sky_total = diffuse + direct
            # Preferred over a plain diffuse/direct ratio, which collapses to
            # zero in morning and evening conditions where direct is zero.
            fraction = numpy.where(
                sky_total > 0,
                numpy.clip(
                    diffuse / numpy.where(sky_total > 0, sky_total, 1.0), 0.0, None
                ),
                1.0,
            )
            shaded = shaded * fraction

        return numpy.where(horizon_shading, shaded, total)

    def _accumulate_array_power(
        self,
        array: dict[str, Any],
        weather: dict[str, Any],
        w_avg: dict[dt, int],
        w_inst: dict[dt, int],
    ) -> None:
        """Accumulate one array's estimated power into the shared totals.

        Irradiance acronyms:
            diffuse (horizontal) irr. (DHI): contribution of diffuse (scattered) sunlight [independent of tilt]
            direct irr.: contribution of direct beam sunlight (on a horizontal plane?)
            direct normal irr. (DNI): intensity of direct sunlight on a plane perpendicular to the beam
            global horizontal irr. (GHI): sum of diffuse and direct sunlight collected on a horizontal plane (tilt = 0°)
            global tilted irr. (GTI): sum of diffuse and direct sunlight collected on a tilted plane
        """
        time_arr = weather["time_arr"]
        s = self._array_series(array, weather)
        efficiency = array["efficiency_factor"]

        for i, time in enumerate(time_arr):
            if i == 0:
                continue

            # For minutely data, the GTI start time is 15 minutes before the
            # time even for instant data (since the data is averaged over 15
            # minutes)
            time_start = time - timedelta(minutes=15)

            eff_damped = efficiency * s.damping[i]

            # Snow shades whole strings rather than attenuating irradiance,
            # so it derates DC power instead of scaling the input irradiance.
            snow_factor = 1.0 - s.snow_loss[i]

            dc_avg = (
                gen_power_at_temp(
                    s.irr_avg[i],
                    s.tcell_avg[i],
                    eff_damped * s.eta_irr_avg[i],
                    s.dc_wp,
                )
                * snow_factor
            )
            dc_inst = (
                gen_power_at_temp(
                    s.irr_inst[i],
                    s.tcell_inst[i],
                    eff_damped * s.eta_irr_inst[i],
                    s.dc_wp,
                )
                * snow_factor
            )

            if s.pdc0 is not None:
                dc_avg = inverter_ac_power(dc_avg, s.pdc0)
                dc_inst = inverter_ac_power(dc_inst, s.pdc0)

            w_avg[time_start] += round(dc_avg)
            w_inst[time_start] += round(dc_inst)

    @staticmethod
    def _array_snow_loss(
        array: dict[str, Any],
        weather: dict[str, Any],
        gti_avg_arr: list[float],
    ) -> numpy.ndarray:
        """Fraction of DC capacity this array loses to snow at each step.

        Snow is tracked *on the modules*: it accumulates during snowfall and
        slides off at a rate set by tilt, plane-of-array irradiance and air
        temperature. Plane-of-array irradiance is the right driver because it
        is what warms the panel surface and releases the snow.
        """
        minutely = weather["minutely"]
        surface_tilt = (
            weather["solpos_avg"]["apparent_zenith"].clip(0.0, 90.0).to_numpy()
            if array["tracking"] in ("tilt", "dual")
            else array["declination"]
        )
        return snow_dc_loss(
            weather["times_index"],
            minutely["snowfall"],
            minutely["snow_depth"],
            gti_avg_arr,
            minutely["temperature_2m"],
            surface_tilt=surface_tilt,
        )

    def _apply_inverter(
        self, w_avg: dict[dt, int], w_inst: dict[dt, int]
    ) -> None:
        """Convert the combined DC output to AC for a shared inverter.

        Only applies when a single inverter is shared by every array. With
        per-array inverters each array was already converted individually in
        ``_accumulate_array_power``, so the totals are AC already and the
        combined output is limited by the sum of the individual capacities.
        """
        if not self.shared_inverter:
            return

        dc_wp_total = sum(self.dc_kwp) * 1000
        pdc0 = inverter_dc_input_limit(self.ac_kwp[0] * 1000, dc_wp_total)
        for time in w_avg:
            w_avg[time] = round(inverter_ac_power(w_avg[time], pdc0))
        for time in w_inst:
            w_inst[time] = round(inverter_ac_power(w_inst[time], pdc0))

    async def estimate(self) -> Estimate:
        """Get solar production estimations from the API.

        Returns
        -------
            A Estimate object, with a estimated production forecast.

        """
        w_avg: dict[dt, int] = defaultdict(int)
        w_inst: dict[dt, int] = defaultdict(int)
        wh_days: dict[dt, int] = defaultdict(int)

        data = await self._fetch_forecast()
        tz = timezone(timedelta(seconds=data["utc_offset_seconds"]))
        weather = self._prepare_weather(data, tz)

        for array in self._array_params():
            self._accumulate_array_power(array, weather, w_avg, w_inst)

        self._apply_inverter(w_avg, w_inst)

        wh_period_15m = _quarter_hour_energy(w_avg)
        wh_period = hourly_average_power(w_avg)
        wh_days = daily_energy(wh_period, wh_days)

        return Estimate(
            watts=w_inst,
            wh_period=wh_period,
            wh_days=wh_days,
            api_timezone=tz,
            wh_period_15m=wh_period_15m,
        )

    async def close(self) -> None:
        """Close open client session."""
        if self.session and self._close_session:
            await self.session.close()

    async def __aenter__(self) -> Self:
        """Async enter.

        Returns
        -------
            The OpenMeteoSolarForecast object.

        """
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """Async exit.

        Args:
        ----
            _exc_info: Exec type.

        """
        await self.close()

"""Asynchronous Python client for the API."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, timedelta, timezone
from datetime import datetime as dt
from typing import Any, Self

import numpy
import pandas as pd
from aiohttp import ClientSession

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
    validate_ac_kwp,
    validate_azimuth,
    validate_tracking,
)
from .power import (
    _quarter_hour_energy,
    calculate_damping_coefficient,
    daily_energy,
    diffuse_fraction,
    gen_power,
    hourly_average_power,
    snowcover_factor,
)
from .sun import (
    build_sun_times,
    check_horizon_shading,
    compute_gti,
    solar_position,
)

__all__ = ["OpenMeteoSolarForecast", "_quarter_hour_energy"]


def _is_missing(*values: float | None) -> bool:
    """Check if any value is missing (None or NaN)."""
    return any(
        value is None or (isinstance(value, float) and math.isnan(value))
        for value in values
    )


@dataclass
class OpenMeteoSolarForecast:
    """Main class for handling connections with the API."""

    azimuth: float | list[float]
    declination: float | list[float]
    dc_kwp: float | list[float]
    latitude: float | list[float]
    longitude: float | list[float]

    past_days: int = 92
    forecast_days: int = 16

    ac_kwp: float | list[float | None] | None = None
    api_key: str | None = None
    base_url: str | None = None
    weather_model: str | None = None
    damping_morning: float | list[float] = 0.0
    damping_evening: float | list[float] = 0.0
    efficiency_factor: float | list[float] = 1.0
    tracking: str | list[str] = "none"
    use_horizon: bool | list[bool] = False
    partial_shading: bool | list[bool] = False
    horizon_map: tuple(tuple(float)) | list[tuple(tuple(float))] = ((0.0,20.0),(360.0,20.0))
    max_snowcover_depth_cm: float | list[float] = 0.0

    session: ClientSession | None = None
    _close_session: bool = False

    def __post_init__(self) -> None:
        """Initialize the OpenMeteoSolarForecast object."""
        if self.base_url is None:
            self.base_url = "https://api.open-meteo.com"
        if self.ac_kwp is None:
            self.ac_kwp = float("inf")

        self._normalize_required_params()
        self._normalize_optional_params()

    def _normalize_required_params(self) -> None:
        required_attr_names = (
            "azimuth",
            "declination",
            "dc_kwp",
            "latitude",
            "longitude",
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
        self.max_snowcover_depth_cm = normalize("max_snowcover_depth_cm")

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
            if "," in self.weather_model:
                raise OpenMeteoSolarForecastInvalidModel(
                    "Multiple models are not supported"
                )
            params = params or {}
            params["models"] = self.weather_model

        response = await self.session.request(
            "GET",
            self.base_url + uri,
            params=params,
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
            "latitude",
            "longitude",
            "efficiency_factor",
            "tracking",
            "damping_morning",
            "damping_evening",
            "use_horizon",
            "partial_shading",
            "horizon_map",
            "max_snowcover_depth_cm",
            "ac_kwp",
        )
        values = zip(*(getattr(self, name) for name in names), strict=True)
        return [dict(zip(names, row, strict=True)) for row in values]

    async def _fetch_forecast(self, array: dict[str, Any]) -> Any:
        params = {
            "latitude": str(array["latitude"]),
            "longitude": str(array["longitude"]),
            "minutely_15": "temperature_2m"
            ",shortwave_radiation,shortwave_radiation_instant"
            ",diffuse_radiation,diffuse_radiation_instant"
            ",direct_normal_irradiance,direct_normal_irradiance_instant"
            ",snow_depth",
            "forecast_days": str(self.forecast_days),
            "past_days": str(self.past_days),
            "timezone": "auto",
            "timeformat": "unixtime",
        }
        return await self._request(
            "/v1/forecast",
            params=params,
        )

    def _accumulate_array_power(
        self,
        array: dict[str, Any],
        data: Any,
        tz: timezone,
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
        minutely = data["minutely_15"]
        ghi_avg_arr = minutely["shortwave_radiation"]
        ghi_inst_arr = minutely["shortwave_radiation_instant"]
        dhi_avg_arr = minutely["diffuse_radiation"]
        dhi_inst_arr = minutely["diffuse_radiation_instant"]
        dni_avg_arr = minutely["direct_normal_irradiance"]
        dni_inst_arr = minutely["direct_normal_irradiance_instant"]
        snow_depth_arr = minutely["snow_depth"]
        temp_arr = minutely["temperature_2m"]

        time_arr = [
            dt.fromtimestamp(ts, UTC).astimezone(tz)
            for ts in minutely["time"]
        ]

        lat = array["latitude"]
        lon = array["longitude"]

        # Averaged values cover the preceding 15 minutes; use the interval
        # midpoint for their solar position.
        times_inst = pd.to_datetime(minutely["time"], unit="s", utc=True)
        times_avg = times_inst - pd.Timedelta(minutes=7.5)
        solpos_inst = solar_position(times_inst, lat, lon)
        solpos_avg = solar_position(times_avg, lat, lon)

        gti_avg_arr = compute_gti(
            solpos_avg, ghi_avg_arr, dhi_avg_arr, dni_avg_arr, array
        ).tolist()
        gti_inst_arr = compute_gti(
            solpos_inst, ghi_inst_arr, dhi_inst_arr, dni_inst_arr, array
        ).tolist()

        daily_dates = sorted({t.date() for t in time_arr})
        sunrise_dict, sunset_dict = build_sun_times(daily_dates, lat, lon, tz)

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

        use_horizon = array["use_horizon"]
        partial_shading = array["partial_shading"]
        max_snowcover_depth_cm = array["max_snowcover_depth_cm"]
        efficiency = array["efficiency_factor"]

        if use_horizon:
            hmap_arr = numpy.array(array["horizon_map"]).T
            horizon_shading = check_horizon_shading(solpos_inst, hmap_arr)
        else:
            horizon_shading = [False for t in time_arr]

        dc_wp = array["dc_kwp"] * 1000

        # Per-array inverter clamp (only when per-array capacities are
        # given; a shared inverter clamps the combined output below)
        ac_wp_array = (
            float("inf") if self.shared_inverter else array["ac_kwp"] * 1000
        )

        for i, time in enumerate(time_arr):
            if i == 0:
                continue

            if _is_missing(
                gti_avg_arr[i],
                gti_inst_arr[i],
                *temp_arr[i - 1 : i + 1],
            ):
                continue

            g_avg = gti_avg_arr[i]
            g_inst = gti_inst_arr[i]
            d_avg = dhi_avg_arr[i]
            d_inst = dhi_inst_arr[i]
            dr_avg = ghi_avg_arr[i] - d_avg
            dr_inst = ghi_inst_arr[i] - d_inst

            # Calculate diffuse contribution (only if partial_shading enabled).
            # Preferred over the simple ratio d/dr, because that may turn 0
            # unexpectedly in morning/evening conditions, when dr = 0.
            if use_horizon and partial_shading:
                f_avg = diffuse_fraction(d_avg, dr_avg)
                f_inst = diffuse_fraction(d_inst, dr_inst)
            else:
                f_avg = 1.0
                f_inst = 1.0

            temp_avg = (temp_arr[i] + temp_arr[i - 1]) / 2
            temp_inst = temp_arr[i - 1]

            # For minutely data, the GTI start time is 15 minutes before the
            # time even for instant data (since the data is averaged over 15
            # minutes)
            time_start = time - timedelta(minutes=15)

            eff_damped = efficiency * damping_factors[i]

            # If horizon-shaded, apply diffuse radiation and optionally the
            # diffuse/direct factor.
            # --- experimental empiric partial shading approach ---
            # On a sunny day (low f), 'hard' shadows result in the bypass
            # diodes shutting off the module almost completely. On a cloudy
            # day (high f), no 'hard' shadows are present and the module
            # operates at pure diffuse power. In between, the partial shading
            # effect is assumed to be directly dependent on f.
            # Inspired by https://pvlib-python.readthedocs.io/en/stable/gallery/shading/plot_partial_module_shading_simple.html#calculating-shading-loss-across-shading-scenarios
            if horizon_shading[i]:
                irr_avg = d_avg * f_avg
                irr_inst = d_inst * f_inst
            else:
                irr_avg = g_avg
                irr_inst = g_inst

            if max_snowcover_depth_cm > 0:
                factor = snowcover_factor(snow_depth_arr[i], max_snowcover_depth_cm)
                irr_avg *= factor
                irr_inst *= factor

            w_avg[time_start] += round(
                min(gen_power(irr_avg, temp_avg, eff_damped, dc_wp), ac_wp_array)
            )
            w_inst[time_start] += round(
                min(gen_power(irr_inst, temp_inst, eff_damped, dc_wp), ac_wp_array)
            )

    def _clamp_to_inverter(
        self, w_avg: dict[dt, int], w_inst: dict[dt, int]
    ) -> None:
        """Clamp the power generated to the AC power of the inverter(s).

        With a shared inverter the combined output is clamped to its capacity;
        with per-array inverters each array was already clamped individually,
        so the combined output is limited by the sum of all capacities.
        """
        ac_kwp_total = self.ac_kwp[0] if self.shared_inverter else sum(self.ac_kwp)
        ac_wp = ac_kwp_total * 1000
        for time in w_avg:
            w_avg[time] = min(w_avg[time], ac_wp)
        for time in w_inst:
            w_inst[time] = min(w_inst[time], ac_wp)

    async def estimate(self) -> Estimate:
        """Get solar production estimations from the API.

        Returns
        -------
            A Estimate object, with a estimated production forecast.

        """
        w_avg: dict[dt, int] = defaultdict(int)
        w_inst: dict[dt, int] = defaultdict(int)
        wh_days: dict[dt, int] = defaultdict(int)

        utc_offset = None
        tz = None
        for array in self._array_params():
            data = await self._fetch_forecast(array)

            if utc_offset is None:
                utc_offset = data["utc_offset_seconds"]
            elif utc_offset != data["utc_offset_seconds"]:
                raise OpenMeteoSolarForecastConfigError(
                    "The UTC offset is not the same for all locations"
                )
            tz = timezone(timedelta(seconds=utc_offset))

            self._accumulate_array_power(array, data, tz, w_avg, w_inst)

        self._clamp_to_inverter(w_avg, w_inst)

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

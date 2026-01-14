"""Asynchronous Python client for the API."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime as dt
from datetime import timedelta, timezone
from typing import Any, Self
import suncalc
import numpy
import pytz

from aiohttp import ClientSession

from .constants import ALPHA_TEMP, G_STC, TEMP_STC_CELL, RossModelConstants
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

    ac_kwp: float | None = None
    api_key: str | None = None
    base_url: str | None = None
    weather_model: str | None = None
    damping_morning: float | list[float] = 0.0
    damping_evening: float | list[float] = 0.0
    efficiency_factor: float | list[float] = 1.0
    use_horizon: bool | list[bool] = False
    partial_shading: bool | list[bool] = False
    horizon_map: tuple(tuple(float)) | list[tuple(tuple(float))] = ((0.0,20.0),(360.0,20.0))

    session: ClientSession | None = None
    _close_session: bool = False

    def __post_init__(self) -> None:
        """Initialize the OpenMeteoSolarForecast object."""
        if self.base_url is None:
            self.base_url = "https://api.open-meteo.com"
        if self.ac_kwp is None:
            self.ac_kwp = float("inf")

        # Validate list parameters
        if list in map(
            type,
            (
                self.azimuth,
                self.declination,
                self.dc_kwp,
                self.latitude,
                self.longitude,
            ),
        ):
            if not all(
                isinstance(param, list) and len(param) == len(self.dc_kwp)
                for param in (
                    self.azimuth,
                    self.declination,
                    self.dc_kwp,
                    self.latitude,
                    self.longitude,
                )
            ):
                raise OpenMeteoSolarForecastConfigError(
                    "The parameters must be of the same length"
                )
        else:
            self.azimuth = [self.azimuth]
            self.declination = [self.declination]
            self.dc_kwp = [self.dc_kwp]
            self.latitude = [self.latitude]
            self.longitude = [self.longitude]

        def test_param_len(attr_name: str, other_attr: list[Any]) -> list[Any]:
            """Validate the length of a param and return a list of the same length."""
            attr = getattr(self, attr_name)
            if isinstance(attr, list):
                if len(attr) != len(other_attr):
                    msg = f"{attr_name} must be the same length as the other parameters"
                    raise OpenMeteoSolarForecastConfigError(msg)
            else:
                attr = [attr] * len(other_attr)
            return attr

        self.efficiency_factor = test_param_len("efficiency_factor", self.dc_kwp)
        self.damping_morning = test_param_len("damping_morning", self.dc_kwp)
        self.damping_evening = test_param_len("damping_evening", self.dc_kwp)
        self.use_horizon = test_param_len("use_horizon", self.dc_kwp)
        self.partial_shading = test_param_len("partial_shading", self.dc_kwp)
        self.horizon_map = test_param_len("horizon_map", self.dc_kwp)

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
        # Connect as normal
        if self.session is None:
            self.session = ClientSession()
            self._close_session = True

        # Add the API key to the request
        if self.api_key:
            params = params or {}
            params["apikey"] = self.api_key

        # Add the weather model to the request
        if self.weather_model:
            if "," in self.weather_model:
                raise OpenMeteoSolarForecastInvalidModel(
                    "Multiple models are not supported"
                )
            params = params or {}
            params["models"] = self.weather_model

        # Get response from the API
        response = await self.session.request(
            "GET",
            self.base_url + uri,
            params=params,
        )

        if response.status in (502, 503):
            raise OpenMeteoSolarForecastConnectionError("The API is unreachable")

        if response.status == 400:
            raise OpenMeteoSolarForecastRequestError("Bad request")

        if response.status in (401, 403):
            raise OpenMeteoSolarForecastAuthenticationError("Invalid API key")

        if response.status == 422:
            raise OpenMeteoSolarForecastConfigError("Invalid configuration")

        if response.status == 429:
            raise OpenMeteoSolarForecastRatelimitError("Rate limit exceeded")

        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            text = await response.text()
            raise OpenMeteoSolarForecastError(
                "Unexpected response from the API",
                {"Content-Type": content_type, "response": text},
            )

        return await response.json()

    async def estimate(self) -> Estimate:
        """Get solar production estimations from the API.

        Returns
        -------
            A Estimate object, with a estimated production forecast.

        """
        w_avg: dict[dt, int] = defaultdict(int)
        w_inst: dict[dt, int] = defaultdict(int)
        wh_days: dict[dt, int] = defaultdict(int)

        def gen_power(gti: float, t_amb: float, eff: float) -> int:
            """Calculate the power generated by a solar panel.

            Formulas:
            ---------
                According to https://www.mdpi.com/2071-1050/14/3/1500 (equations 1 and 2) and Table 1,
                the temperature formula should be:
                     Tc = Ta + G * k
                where:
                    - Tc is the cell temperature
                    - Ta is the ambient temperature
                    - G is the irradiance (W/m²)
                    - k is the Ross coefficient

                For a typical residential PV installation, we use the "Not so well cooled" Ross coefficient
                from Table 1, which is 0.0342. (TODO: make this coefficient configurable.)

                References:
                    - Ross model source: https://www.researchgate.net/publication/275438802_Thermal_effects_of_the_extended_holographic_regions_for_holographic_planar_concentrator
                    - Power output formula: P = Pmax * (G / Gstc) * (1 + α * (Tc - Tstc)) * ηDC (see p.509)
                      Source: https://www.researchgate.net/publication/372240079_Solar_Prediction_Strategy_for_Managing_Virtual_Power_Stations
            """
            temp_cell = t_amb + gti * RossModelConstants.NOT_SO_WELL_COOLED
            power = dc_wp
            power *= gti / G_STC
            power *= 1 + ALPHA_TEMP * (temp_cell - TEMP_STC_CELL)
            power *= eff
            return round(max(0, power))
        
        # check if the horizon blocks out direct sunlight
        def check_horizon_shading(
            time: dt,
            lon: float,
            lat: float,
            hmap: float()
        ) -> bool:
            
            position_rad = suncalc.get_position(time, lon, lat)
            azimuth_deg = (180 + numpy.rad2deg(position_rad['azimuth'])) % 360
            altitude_deg = numpy.rad2deg(position_rad['altitude'])
            horizon_deg = numpy.interp(azimuth_deg,hmap[0],hmap[1])
            
            if altitude_deg < horizon_deg:
                shading = True
            else:
                shading = False
            
            return shading

        def calculate_damping_coefficient(
            time: dt,
            sunrise: dt,
            sunset: dt,
            damping_morning: float,
            damping_evening: float,
        ) -> float:
            """Calculate the damping coefficient for the current time.

            Args:
            ----
                time: The current time.
                sunrise: The time of sunrise.
                sunset: The time of sunset.
                damping_morning: The damping factor for the morning.
                damping_evening: The damping factor for the evening.

            Returns:
            -------
                The damping coefficient for the current time.

            Notes:
            -----
                As the damping factor decreases, the power generated by the solar
                panels increases. For example, when the damping factor is 0, the
                power generated is at its maximum and no damping is applied. When
                the damping factor is 1, the power generated is at its minimum and
                the damping is fully applied.

                This means that if a damping factor of 1.0 is applied for the morning,
                at morning_start the power generated will be 0 as the coefficient would
                be 0.0. As the time approaches morning_end, the coefficient will increase
                linearly until it reaches 1.0 at morning_end. The same applies for the
                evening, but the coefficient will decrease linearly from 1.0 to 0.0.

            """
            morning_start = sunrise
            morning_end = sunrise + (sunset - sunrise) / 2
            evening_start = morning_end
            evening_end = sunset

            def linear_damping(start: dt, end: dt, damping: float) -> float:
                """Calculate the linear damping coefficient."""
                duration = end - start
                elapsed = time - start
                damping = 1.0 - damping  # Invert the damping factor
                return (elapsed / duration) * (1.0 - damping) + damping

            if morning_start <= time <= morning_end:
                return linear_damping(morning_start, morning_end, damping_morning)

            if evening_start <= time <= evening_end:
                return linear_damping(evening_end, evening_start, damping_evening)

            return 1

        utc_offset = None
        for (
            azimuth,
            declination,
            dc_kwp,
            latitude,
            lonitude,
            efficiency,
            damping_morning,
            damping_evening,
            use_horizon,
            partial_shading,
            horizon_map,
        ) in zip(
            self.azimuth,
            self.declination,
            self.dc_kwp,
            self.latitude,
            self.longitude,
            self.efficiency_factor,
            self.damping_morning,
            self.damping_evening,
            self.use_horizon,
            self.partial_shading,
            self.horizon_map,
            strict=True,
        ):
            '''
            sorting out the confusing acronyms...
            
            diffuse (horizontal) irr. (DHI): contribution of diffuse (scattered) sunlight [independent of tilt]
            direct irr.: contribution of direct beam sunlight (on a horizontal plane?)
            direct normal irr. (DNI): intensity of direct sunlight on a plane perpendicular to the beam
            global horizontal irr. (GHI): sum of diffuse and direct sunlight collected on a horizontal plane (tilt = 0°)
            global tilted irr. (GTI): sum of diffuse and direct sunlight collected on a tilted plane
            '''
            params = {
                "latitude": str(latitude),
                "longitude": str(lonitude),
                "azimuth": str(azimuth),
                "tilt": str(declination),
                "minutely_15": "temperature_2m"
                ",global_tilted_irradiance,global_tilted_irradiance_instant,diffuse_radiation,diffuse_radiation_instant,direct_radiation,direct_radiation_instant",
                "daily": "sunrise,sunset",
                "forecast_days": str(self.forecast_days),
                "past_days": str(self.past_days),
                "timezone": "auto",
                "timeformat": "unixtime",
            }
            data = await self._request(
                "/v1/forecast",
                params=params,
            )
            gti_avg_arr = data["minutely_15"]["global_tilted_irradiance"]
            gti_inst_arr = data["minutely_15"]["global_tilted_irradiance_instant"]
            dhi_avg_arr = data["minutely_15"]["diffuse_radiation"]
            dhi_inst_arr = data["minutely_15"]["diffuse_radiation_instant"]
            dr_avg_arr = data["minutely_15"]["direct_radiation"]
            dr_inst_arr = data["minutely_15"]["direct_radiation_instant"]
            temp_arr = data["minutely_15"]["temperature_2m"]
            if utc_offset is None:
                utc_offset = data["utc_offset_seconds"]
            elif utc_offset != data["utc_offset_seconds"]:
                raise OpenMeteoSolarForecastConfigError(
                    "The UTC offset is not the same for all locations"
                )

            tz = timezone(timedelta(seconds=utc_offset))

            time_arr = [
                dt.fromtimestamp(ts, timezone.utc).astimezone(tz)
                for ts in data["minutely_15"]["time"]
            ]

            sunrise_times = [
                dt.fromtimestamp(ts, timezone.utc).astimezone(tz)
                for ts in data["daily"]["sunrise"]
            ]
            sunrise_dict = {t.date(): t for t in sunrise_times}

            sunset_times = [
                dt.fromtimestamp(ts, timezone.utc).astimezone(tz)
                for ts in data["daily"]["sunset"]
            ]
            sunset_dict = {t.date(): t for t in sunset_times}

            damping_factors = [
                calculate_damping_coefficient(
                    t,
                    sunrise_dict[t.date()],
                    sunset_dict[t.date()],
                    damping_morning,
                    damping_evening,
                )
                for t in time_arr
            ]
                     
            if use_horizon:
                hmap_arr = numpy.array(horizon_map).T # convert list of tuples to numpy array
                horizon_shading = [
                    check_horizon_shading(t,lonitude,latitude,hmap_arr)
                    for t in time_arr
                ]
            else:
                horizon_shading = [
                    False
                    for t in time_arr
                ]

            # Convert kW to W
            dc_wp = dc_kwp * 1000

            for i, time in enumerate(time_arr):
                # Skip the first element as we need the previous element to calculate
                # the average temperature for the current time
                if i == 0:
                    continue

                # Skip if any of the values are None
                if None in (
                    gti_avg_arr[i],
                    gti_inst_arr[i],
                    *temp_arr[i - 1 : i + 1],
                ):
                    continue

                # Get the GTI for average and instantaneous values
                g_avg = gti_avg_arr[i]
                g_inst = gti_inst_arr[i]
                d_avg = dhi_avg_arr[i]
                d_inst = dhi_inst_arr[i]
                dr_avg = dr_avg_arr[i]
                dr_inst = dr_inst_arr[i]
                
                # Calculate diffuse contribution (only if partial_shading enabled)
                # prefer this over simple ratio d/dr, because this may turn 0 unexpectedly in morning/evening conditions, when dr = 0 
                # clamp to minimum 0 for possible implausible sets
                if use_horizon and partial_shading:
                    if (d_avg + dr_avg) > 0:
                        f_avg = max(d_avg/(d_avg + dr_avg) , 0.0)
                    else:
                        f_avg = 1.0
                        
                    if (d_inst + dr_inst) > 0:
                        f_inst = max(d_inst/(d_inst + dr_inst) , 0.0)
                    else:
                        f_inst = 1.0
                else:
                    f_avg = 1.0
                    f_inst = 1.0
                    

                # Get the temperature for average and instantaneous values
                temp_avg = (temp_arr[i] + temp_arr[i - 1]) / 2
                temp_inst = temp_arr[i - 1]

                # For minutely data, the GTI start time is 15 minutes before the time
                # even for instant data (since the data is averaged over 15 minutes)
                time_start = time - timedelta(minutes=15)

                # Add the damping factor to the efficiency
                eff_damped = efficiency * damping_factors[i]
                
                # Check for horizon shading - if shaded, apply diffuse radiation and optionally diffuse/direct factor
                # --- experimental empiric partial shading approach ---
                # On a sunny day (low f), there are 'hard' shadows resulting in the bypass diodes shutting of the module almost completely
                # On a cloudy day (high f), no 'hard' shadows are present and the module operates at pure diffuse power
                # In between, partial shading effect is assumed to be directly dependent on f
                # inspired by https://pvlib-python.readthedocs.io/en/stable/gallery/shading/plot_partial_module_shading_simple.html#calculating-shading-loss-across-shading-scenarios
                
                if horizon_shading[i]:
                    irr_avg = d_avg * f_avg
                    irr_inst = d_inst * f_inst
                else:
                    irr_avg = g_avg
                    irr_inst = g_inst

                # Calculate and store the power generated
                w_avg[time_start] += gen_power(irr_avg, temp_avg, eff_damped)
                w_inst[time_start] += gen_power(irr_inst, temp_inst, eff_damped)

        # Clamp the power generated to the AC power
        ac_wp = self.ac_kwp * 1000  # Convert kW to W
        for time in w_avg:
            w_avg[time] = min(w_avg[time], ac_wp)
        for time in w_inst:
            w_inst[time] = min(w_inst[time], ac_wp)

        # Calculate the average power generated per hour
        wh_period: dict[dt, int] = {}
        wh_period_count: dict[dt, int] = {}
        for time, power in w_avg.items():
            hour = time.replace(minute=0, second=0, microsecond=0)
            wh_period[hour] = wh_period.get(hour, 0) + power
            wh_period_count[hour] = wh_period_count.get(hour, 0) + 1
        for time in wh_period:
            wh_period[time] /= wh_period_count[time]

        # Calculate the total energy produced per day
        for time, power in wh_period.items():
            day = time.date()
            wh_days[day] = wh_days.get(day, 0) + power

        # Return the estimate object
        return Estimate(
            watts=w_inst,
            wh_period=wh_period,
            wh_days=wh_days,
            api_timezone=tz,
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

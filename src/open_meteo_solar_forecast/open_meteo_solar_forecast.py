"""Asynchronous Python client for the API."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime as dt
from datetime import timedelta, timezone
from typing import Any, Self

from aiohttp import ClientSession

from .constants import (
    ALPHA_TEMP,
    CELL_EFFICIENCY,
    G_NOCT,
    G_STC,
    TEMP_NOCT_AMB,
    TEMP_NOCT_CELL,
    TEMP_STC_CELL,
    TRANSMITTANCE_ABSORPTION,
    WIND_NOCT_SPEED,
)
from .exceptions import (
    OpenMeteoSolarForecastAuthenticationError,
    OpenMeteoSolarForecastConfigError,
    OpenMeteoSolarForecastConnectionError,
    OpenMeteoSolarForecastError,
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
    efficiency_factor: float | list[float] = 1.0

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

        if isinstance(self.efficiency_factor, list):
            if len(self.efficiency_factor) != len(self.dc_kwp):
                raise OpenMeteoSolarForecastConfigError(
                    "The efficiency factor must be of the same length as the other "
                    "parameters"
                )
        else:
            self.efficiency_factor = [self.efficiency_factor] * len(self.dc_kwp)

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

        def gen_power(gti: float, t_amb: float, wind_speed: float, eff: float) -> int:
            """Calculate the power generated by a solar panel.

            Formulas:
            ---------
                Tc=Ta + (G/Gnoct) * (UL,noct/UL) * (Tnoct - Ta,noct) * (1 - ηcell/τα)
                τα=0.9
                ηcell=efficiency of the cell (assumed polycrystalline, so 12%)
                UL,noct/UL = hw,noct/hw,v
                hw(v) = 8.91 + 2.0 * v
                Source: https://crimsonpublishers.com/prsp/pdf/PRSP.000528.pdf

                P=Pmax * (G/Gstc) * (1 + α * (Tc-Tstc)) * ηDC (p.509)
                Source: https://www.researchgate.net/publication/372240079_Solar_Prediction_Strategy_for_Managing_Virtual_Power_Stations
            """

            def hw_v(v: float) -> float:
                return 8.91 + 2.0 * v

            temp_cell = gti / G_NOCT
            temp_cell *= hw_v(WIND_NOCT_SPEED) / hw_v(wind_speed)
            temp_cell *= TEMP_NOCT_CELL - TEMP_NOCT_AMB
            temp_cell *= 1 - (CELL_EFFICIENCY / TRANSMITTANCE_ABSORPTION)
            temp_cell += t_amb
            power = dc_wp
            power *= gti / G_STC
            power *= 1 + ALPHA_TEMP * (temp_cell - TEMP_STC_CELL)
            power *= eff
            return round(max(0, power))

        utc_offset = None
        for az, dec, dc_kwp, lat, lon, eff in zip(
            self.azimuth,
            self.declination,
            self.dc_kwp,
            self.latitude,
            self.longitude,
            self.efficiency_factor,
            strict=True,
        ):
            params = {
                "latitude": str(lat),
                "longitude": str(lon),
                "azimuth": str(az),
                "tilt": str(dec),
                "minutely_15": "temperature_2m,wind_speed_10m"
                ",global_tilted_irradiance,global_tilted_irradiance_instant",
                "forecast_days": str(self.forecast_days),
                "past_days": str(self.past_days),
                "timezone": "auto",
            }
            data = await self._request(
                "/v1/forecast",
                params=params,
            )
            gti_avg_arr = data["minutely_15"]["global_tilted_irradiance"]
            gti_inst_arr = data["minutely_15"]["global_tilted_irradiance_instant"]
            temp_arr = data["minutely_15"]["temperature_2m"]
            wind_arr = [
                wind_speed * 1000 / 3600 if wind_speed is not None else None
                for wind_speed in data["minutely_15"]["wind_speed_10m"]
            ]
            if utc_offset is None:
                utc_offset = data["utc_offset_seconds"]
            elif utc_offset != data["utc_offset_seconds"]:
                raise OpenMeteoSolarForecastConfigError(
                    "The UTC offset is not the same for all locations"
                )
            time_arr = [
                dt.strptime(time, "%Y-%m-%dT%H:%M").replace(
                    tzinfo=timezone(timedelta(seconds=utc_offset))
                )
                for time in data["minutely_15"]["time"]
            ]

            # Convert kW to W
            dc_wp = dc_kwp * 1000

            for i, time in enumerate(time_arr):
                # Skip the first element as we need the previous element to calculate
                # the average temperature and wind speed for the current time
                if i - 1 < 0:
                    continue

                # Skip none-values
                if None in (
                    gti_avg_arr[i],
                    gti_inst_arr[i],
                    *temp_arr[i - 1 : i + 1],
                    *wind_arr[i - 1 : i + 1],
                ):
                    continue

                # Get the GTI for average and instantaneous values
                g_avg = gti_avg_arr[i]
                g_inst = gti_inst_arr[i]

                # Get the temp and wind speed for average and instantaneous values
                temp_avg = (temp_arr[i] + temp_arr[i - 1]) / 2
                wind_avg = (wind_arr[i] + wind_arr[i - 1]) / 2
                temp_inst = temp_arr[i - 1]
                wind_inst = wind_arr[i - 1]

                # For minutely data, the GTI start time is 15 minutes before the time
                # even for instant data (since the data is averaged over 15 minutes)
                time_start = time - timedelta(minutes=15)

                # Calculate and store the power generated
                w_avg[time_start] += gen_power(g_avg, temp_avg, wind_avg, eff)
                w_inst[time_start] += gen_power(g_inst, temp_inst, wind_inst, eff)

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
            api_timezone=timezone(timedelta(seconds=utc_offset)),
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

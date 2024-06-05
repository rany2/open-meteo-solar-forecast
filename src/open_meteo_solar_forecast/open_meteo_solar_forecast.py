"""Asynchronous Python client for the API."""

from __future__ import annotations

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

    azimuth: float
    declination: float
    kwp: float
    latitude: float
    longitude: float

    past_days: int = 92
    forecast_days: int = 16

    base_url: str | None = None
    api_key: str | None = None
    efficiency_factor: float = 1.0

    session: ClientSession | None = None
    _close_session: bool = False

    def __post_init__(self) -> None:
        """Initialize the OpenMeteoSolarForecast object."""
        if self.base_url is None:
            self.base_url = "https://api.open-meteo.com"

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
        params = {
            "latitude": str(self.latitude),
            "longitude": str(self.longitude),
            "azimuth": str(self.azimuth),
            "tilt": str(self.declination),
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
        gti_instant_arr = data["minutely_15"]["global_tilted_irradiance_instant"]
        temp_arr = data["minutely_15"]["temperature_2m"]
        wind_arr = [
            wind_speed * 1000 / 3600
            for wind_speed in data["minutely_15"]["wind_speed_10m"]
        ]
        utc_offset = data["utc_offset_seconds"]
        time_arr = [
            dt.strptime(time, "%Y-%m-%dT%H:%M").replace(
                tzinfo=timezone(timedelta(seconds=utc_offset))
            )
            for time in data["minutely_15"]["time"]
        ]

        peak_power = self.kwp * 1000  # Convert kW to W

        w_avg: dict[dt, int] = {}
        w_inst: dict[dt, int] = {}
        wh_days: dict[dt, int] = {}

        def gen_power(gti: float, t_amb: float, wind_speed: float) -> int:
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
            power = (
                peak_power
                * (gti / G_STC)
                * (1 + ALPHA_TEMP * (temp_cell - TEMP_STC_CELL))
            ) * self.efficiency_factor
            return round(max(0, power))

        for i, time in enumerate(time_arr):
            # If any of the values are missing, skip the iteration
            if None in (
                gti_avg_arr[i],
                gti_instant_arr[i],
                *(temp_arr[i], temp_arr[i - 1] if i > 0 else temp_arr[i]),
                *(wind_arr[i], wind_arr[i - 1] if i > 0 else wind_arr[i]),
            ):
                continue

            # Total radiation received on a tilted pane
            g_avg = gti_avg_arr[i]
            g_inst = gti_instant_arr[i]

            # Get the temperature and wind speed for instant and average values
            temp_avg = (temp_arr[i] + temp_arr[i - 1]) / 2 if i > 0 else temp_arr[i]
            wind_avg = (wind_arr[i] + wind_arr[i - 1]) / 2 if i > 0 else wind_arr[i]
            temp_inst = temp_arr[i]
            wind_inst = wind_arr[i]

            # For minutely data, the average is taken over 15 minutes whereas
            # the instant data is for the current minute only
            time_start_inst = time
            time_start_avg = time - timedelta(minutes=15)

            # Calculate and store the power generated
            w_avg[time_start_avg] = gen_power(g_avg, temp_avg, wind_avg)
            w_inst[time_start_inst] = gen_power(g_inst, temp_inst, wind_inst)

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

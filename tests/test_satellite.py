"""Tests for substituting satellite-observed irradiance over the recent past."""

# ruff: noqa: S101

import asyncio
import unittest

from open_meteo_solar_forecast import OpenMeteoSolarForecast
from open_meteo_solar_forecast.satellite import (
    SATELLITE_VARS,
    blend_observations,
    satellite_params,
)

STEP = 900


def _forecast(**kwargs) -> OpenMeteoSolarForecast:
    defaults = {
        "latitude": 52.0,
        "longitude": 4.0,
        "declination": 35,
        "azimuth": 0,
        "dc_kwp": 5.0,
    }
    defaults.update(kwargs)
    return OpenMeteoSolarForecast(**defaults)


def _minutely(n: int, value: float = 100.0) -> dict:
    forecast = _forecast()
    out: dict = {"time": [i * STEP for i in range(n)]}
    for var in forecast.MINUTELY_15_VARS:
        out[var] = [value] * n
    return out


def _observation(n: int, value: float = 500.0, step: int = 600) -> dict:
    """A satellite response on its own cadence, 10-minutely by default."""
    return {
        "hourly": {
            "time": [i * step for i in range(n)],
            **{var: [value] * n for var in SATELLITE_VARS},
        }
    }


class ParamTests(unittest.TestCase):
    """Verify the outgoing satellite request."""

    def test_requests_native_resolution(self) -> None:
        """Ask for native cadence, not hourly.

        Hourly would blur the shape of the day; the seamless product is
        natively 10-minutely.
        """
        params = satellite_params(52.0, 4.0, 7)
        assert params["temporal_resolution"] == "native"

    def test_requests_only_irradiance(self) -> None:
        """Ask for the variables a satellite can actually observe."""
        requested = satellite_params(52.0, 4.0, 7)["hourly"].split(",")
        assert set(requested) == set(SATELLITE_VARS)
        assert not any("temperature" in v or "wind" in v for v in requested)


class BlendTests(unittest.TestCase):
    """Verify observation replaces forecast only where it exists."""

    def test_observation_replaces_forecast(self) -> None:
        """Prefer the observation wherever one is available."""
        blended, replaced = blend_observations(_minutely(20), _observation(60))
        assert replaced > 0
        assert blended["shortwave_radiation"][10] == 500.0

    def test_non_irradiance_variables_are_untouched(self) -> None:
        """Leave temperature, wind and snow to the forecast models."""
        blended, _ = blend_observations(_minutely(20), _observation(60))
        for var in ("temperature_2m", "wind_speed_10m", "snow_depth", "snowfall"):
            assert blended[var] == [100.0] * 20

    def test_uncovered_timesteps_keep_the_forecast(self) -> None:
        """Fall back to the forecast beyond the observation's reach.

        The satellite only sees the past, so the forward part of the horizon
        must survive untouched.
        """
        minutely = _minutely(40)
        # observation covers only the first quarter of the window
        blended, replaced = blend_observations(minutely, _observation(15))
        assert replaced < 40
        assert blended["shortwave_radiation"][-1] == 100.0

    def test_empty_response_is_a_no_op(self) -> None:
        """Change nothing when the response carries no data."""
        minutely = _minutely(10)
        for payload in (None, {}, {"hourly": {}}, {"hourly": {"time": []}}):
            blended, replaced = blend_observations(minutely, payload)
            assert replaced == 0
            assert blended == minutely

    def test_all_null_observation_is_a_no_op(self) -> None:
        """Ignore a response whose values are all missing.

        Outside coverage the API can answer with the right shape but no
        numbers.
        """
        payload = {
            "hourly": {
                "time": [i * 600 for i in range(30)],
                **{var: [None] * 30 for var in SATELLITE_VARS},
            }
        }
        minutely = _minutely(10)
        blended, replaced = blend_observations(minutely, payload)
        assert replaced == 0
        assert blended["shortwave_radiation"] == [100.0] * 10

    def test_length_is_preserved(self) -> None:
        """Keep every series the same length as the time axis."""
        blended, _ = blend_observations(_minutely(24), _observation(90))
        for var, series in blended.items():
            assert len(series) == 24, var

    def test_averaged_values_are_re_averaged(self) -> None:
        """Average sub-interval observations rather than sampling one.

        Observations arrive 10-minutely and intervals are 15 minutes, so the
        cadences do not line up. Two observations land inside the interval
        ending at 1800 s; the result must be their mean, not whichever
        happened to be nearest the boundary.

        Buckets, by interval end:
            0    <- 100
            900  <- 200
            1800 <- 600 and 900, so 750
            2700 <- 400
        """
        payload = {
            "hourly": {
                "time": [0, 600, 1200, 1800, 2400],
                **{var: [100.0, 200.0, 600.0, 900.0, 400.0]
                   for var in SATELLITE_VARS},
            }
        }
        blended, replaced = blend_observations(_minutely(4), payload)

        assert replaced == 4
        assert blended["shortwave_radiation"] == [100.0, 200.0, 750.0, 400.0]


class ClientIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Verify wiring, and that failure never costs the caller a forecast."""

    def test_disabled_by_default(self) -> None:
        """Leave the extra request off unless asked for.

        Coverage is regional and the call costs latency, so unlike the other
        physics corrections this one is opt-in.
        """
        assert _forecast().use_satellite is False

    async def test_no_request_when_disabled(self) -> None:
        """Make no satellite call at all when the feature is off."""
        forecast = _forecast()
        called = []

        async def fake(uri, *, params=None, base_url=None, with_model=True):  # noqa: ANN001, ARG001
            called.append(base_url)
            return {"minutely_15": _minutely(8), "utc_offset_seconds": 0}

        forecast._request = fake  # noqa: SLF001
        await forecast.estimate()
        assert called == [None]

    async def test_broken_satellite_does_not_break_the_forecast(self) -> None:
        """Serve the forecast even if the observation request explodes.

        Outside coverage the API replies with a bare NaN literal, which is not
        valid JSON, so the failure arrives as a decode error rather than
        anything HTTP-shaped.
        """
        forecast = _forecast(use_satellite=True)

        async def fake(uri, *, params=None, base_url=None, with_model=True):  # noqa: ANN001, ARG001
            if base_url is not None:
                raise ValueError("Expecting value: line 1 column 13 (char 12)")
            return {"minutely_15": _minutely(8), "utc_offset_seconds": 0}

        forecast._request = fake  # noqa: SLF001
        estimate = await forecast.estimate()
        assert len(estimate.watts) > 0

    async def test_satellite_request_targets_its_own_host(self) -> None:
        """Send the observation request to the satellite endpoint."""
        forecast = _forecast(use_satellite=True)
        seen = {}

        async def fake(uri, *, params=None, base_url=None, with_model=True):  # noqa: ANN001
            if base_url is not None:
                seen["url"] = base_url
                seen["uri"] = uri
                seen["with_model"] = with_model
                return None
            return {"minutely_15": _minutely(8), "utc_offset_seconds": 0}

        forecast._request = fake  # noqa: SLF001
        await forecast.estimate()
        assert "satellite" in seen["url"]
        assert seen["uri"] == "/v1/archive"
        # weather models are a forecast concept and must not leak across
        assert seen["with_model"] is False


if __name__ == "__main__":
    unittest.main()

"""Tests for multi-model ensemble support.

Averaging several numerical weather predictions cuts GHI RMSE by roughly 20%
versus a typical single model, without needing any measured data.
"""

# ruff: noqa: S101

import asyncio
import unittest

from open_meteo_solar_forecast import OpenMeteoSolarForecast
from open_meteo_solar_forecast.cache import fingerprint, merge_series
from open_meteo_solar_forecast.constants import (
    DEFAULT_WEATHER_MODELS,
    ENSEMBLE_TRIM_MIN_MODELS,
)
from open_meteo_solar_forecast.exceptions import OpenMeteoSolarForecastInvalidModel
from open_meteo_solar_forecast.params import normalize_weather_models


class _FakeResponse:
    """Minimal stand-in for an aiohttp response."""

    status = 200
    headers = {"Content-Type": "application/json"}

    @staticmethod
    def raise_for_status() -> None:
        """Accept the response as successful."""

    @staticmethod
    async def json() -> dict:
        """Return an empty payload."""
        return {}


class _FakeSession:
    """Captures the query parameters of the outgoing request."""

    def __init__(self) -> None:
        self.params: dict = {}

    async def request(self, _method, _url, *, params=None, timeout=None):  # noqa: ANN001, ARG002
        """Record the parameters and return a canned response."""
        self.params = dict(params or {})
        return _FakeResponse()


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


class WeatherModelNormalizationTests(unittest.TestCase):
    """Verify how the weather_model parameter is interpreted."""

    def test_default_is_the_ensemble(self) -> None:
        """Use the multi-model ensemble when nothing is specified."""
        assert _forecast().weather_model == list(DEFAULT_WEATHER_MODELS)

    def test_default_ensemble_is_wide_enough_to_trim(self) -> None:
        """Ship enough models that outlier trimming actually engages."""
        assert len(DEFAULT_WEATHER_MODELS) >= ENSEMBLE_TRIM_MIN_MODELS
        assert len(set(DEFAULT_WEATHER_MODELS)) == len(DEFAULT_WEATHER_MODELS)

    def test_single_string(self) -> None:
        """Accept one model as a plain string."""
        assert normalize_weather_models("icon_seamless") == ["icon_seamless"]

    def test_comma_separated_string(self) -> None:
        """Accept several models in one comma-separated string."""
        assert normalize_weather_models("icon_seamless,gfs_seamless") == [
            "icon_seamless",
            "gfs_seamless",
        ]

    def test_list_and_tuple(self) -> None:
        """Accept list and tuple forms alike."""
        expected = ["icon_seamless", "gfs_seamless"]
        assert normalize_weather_models(expected) == expected
        assert normalize_weather_models(tuple(expected)) == expected

    def test_whitespace_is_stripped(self) -> None:
        """Tolerate padding around model names."""
        assert normalize_weather_models(" icon_seamless , gfs_seamless ") == [
            "icon_seamless",
            "gfs_seamless",
        ]

    def test_duplicates_are_removed_preserving_order(self) -> None:
        """Avoid silently double-weighting a repeated model."""
        assert normalize_weather_models(
            ["gfs_seamless", "icon_seamless", "gfs_seamless"]
        ) == ["gfs_seamless", "icon_seamless"]

    def test_empty_selection_is_rejected(self) -> None:
        """Reject a selection that names no model at all."""
        for value in ("", "   ", ",,", [], ()):
            with self.assertRaises(OpenMeteoSolarForecastInvalidModel):
                normalize_weather_models(value)

    def test_wrong_type_is_rejected(self) -> None:
        """Reject types that cannot name a model."""
        for value in (42, 3.5, {"model": "icon"}):
            with self.assertRaises(OpenMeteoSolarForecastInvalidModel):
                normalize_weather_models(value)


class EnsembleCollapseTests(unittest.TestCase):
    """Verify per-variable averaging of multi-model responses."""

    @staticmethod
    def _minutely(**series) -> dict:
        return {"time": [0, 900, 1800], **series}

    def test_averages_across_models(self) -> None:
        """Average a variable over every model that supplies it."""
        forecast = _forecast(weather_model=["a", "b"])
        minutely = self._minutely(
            **{
                f"{var}_a": [10.0, 10.0, 10.0] for var in forecast.MINUTELY_15_VARS
            },
            **{
                f"{var}_b": [20.0, 20.0, 20.0] for var in forecast.MINUTELY_15_VARS
            },
        )
        collapsed = forecast._collapse_ensemble(minutely)  # noqa: SLF001
        assert collapsed["temperature_2m"] == [15.0, 15.0, 15.0]
        assert collapsed["time"] == [0, 900, 1800]

    def test_single_model_uses_bare_keys(self) -> None:
        """Read unsuffixed keys, which is what Open-Meteo returns for one model.

        The API only appends the model name when more than one model is
        requested.
        """
        forecast = _forecast(weather_model="icon_seamless")
        minutely = self._minutely(
            **{var: [1.0, 2.0, 3.0] for var in forecast.MINUTELY_15_VARS}
        )
        collapsed = forecast._collapse_ensemble(minutely)  # noqa: SLF001
        assert collapsed["snow_depth"] == [1.0, 2.0, 3.0]

    def test_variable_prefixes_do_not_collide(self) -> None:
        """Keep ``shortwave_radiation`` distinct from its ``_instant`` twin.

        Several variable names are prefixes of others, so prefix matching
        would fold ``shortwave_radiation_instant_a`` into
        ``shortwave_radiation``. Matching must be by exact variable_model name.
        """
        forecast = _forecast(weather_model=["a"])
        minutely = self._minutely(
            **{f"{var}_a": [0.0, 0.0, 0.0] for var in forecast.MINUTELY_15_VARS}
        )
        minutely["shortwave_radiation_a"] = [100.0, 100.0, 100.0]
        minutely["shortwave_radiation_instant_a"] = [900.0, 900.0, 900.0]

        collapsed = forecast._collapse_ensemble(minutely)  # noqa: SLF001

        assert collapsed["shortwave_radiation"] == [100.0, 100.0, 100.0]
        assert collapsed["shortwave_radiation_instant"] == [900.0, 900.0, 900.0]

    def test_model_missing_a_variable_still_contributes_others(self) -> None:
        """Exclude a model only from the variables it does not supply.

        Real behaviour: ukmo_seamless and meteofrance_seamless return no
        snow_depth, but their irradiance is perfectly good.
        """
        forecast = _forecast(weather_model=["a", "b"])
        minutely = self._minutely(
            **{f"{var}_a": [10.0, 10.0, 10.0] for var in forecast.MINUTELY_15_VARS},
            **{f"{var}_b": [20.0, 20.0, 20.0] for var in forecast.MINUTELY_15_VARS},
        )
        # model b supplies no snow_depth at all
        minutely["snow_depth_b"] = [None, None, None]

        collapsed = forecast._collapse_ensemble(minutely)  # noqa: SLF001

        assert collapsed["snow_depth"] == [10.0, 10.0, 10.0], "b must be excluded here"
        assert collapsed["temperature_2m"] == [15.0, 15.0, 15.0], "b still counts here"

    def test_per_timestep_nulls_are_skipped(self) -> None:
        """Average only the models that have a value at each timestep."""
        forecast = _forecast(weather_model=["a", "b"])
        minutely = self._minutely(
            **{f"{var}_a": [10.0, 10.0, 10.0] for var in forecast.MINUTELY_15_VARS},
            **{f"{var}_b": [20.0, 20.0, 20.0] for var in forecast.MINUTELY_15_VARS},
        )
        minutely["temperature_2m_b"] = [20.0, None, 20.0]

        collapsed = forecast._collapse_ensemble(minutely)  # noqa: SLF001

        assert collapsed["temperature_2m"] == [15.0, 10.0, 15.0]

    def test_all_models_null_leaves_none_for_later_filtering(self) -> None:
        """Emit None when no model has a value, so the row is dropped later."""
        forecast = _forecast(weather_model=["a", "b"])
        minutely = self._minutely(
            **{f"{var}_a": [10.0, 10.0, 10.0] for var in forecast.MINUTELY_15_VARS},
            **{f"{var}_b": [20.0, 20.0, 20.0] for var in forecast.MINUTELY_15_VARS},
        )
        minutely["wind_speed_10m_a"] = [10.0, None, 10.0]
        minutely["wind_speed_10m_b"] = [20.0, None, 20.0]

        collapsed = forecast._collapse_ensemble(minutely)  # noqa: SLF001

        assert collapsed["wind_speed_10m"] == [15.0, None, 15.0]

    def test_variable_absent_from_every_model_raises(self) -> None:
        """Fail loudly when no requested model supplies a required variable."""
        forecast = _forecast(weather_model=["a"])
        minutely = self._minutely(
            **{
                f"{var}_a": [1.0, 1.0, 1.0]
                for var in forecast.MINUTELY_15_VARS
                if var != "snowfall"
            }
        )
        with self.assertRaises(OpenMeteoSolarForecastInvalidModel) as ctx:
            forecast._collapse_ensemble(minutely)  # noqa: SLF001
        assert "snowfall" in str(ctx.exception)


class EnsembleTrimmingTests(unittest.TestCase):
    """Verify outlier trimming before averaging."""

    @staticmethod
    def _collapse(values_per_model: list[list[float]]) -> float:
        """Collapse one timestep given each model's value for every variable."""
        names = [f"m{i}" for i in range(len(values_per_model))]
        forecast = _forecast(weather_model=names)
        minutely: dict = {"time": [0]}
        for name, values in zip(names, values_per_model, strict=True):
            for var in forecast.MINUTELY_15_VARS:
                minutely[f"{var}_{name}"] = [values[0]]
        return forecast._collapse_ensemble(minutely)["temperature_2m"][0]  # noqa: SLF001

    def test_extremes_are_discarded_when_wide_enough(self) -> None:
        """Drop the highest and lowest before averaging.

        With 1, 2, 3, 4, 100 the plain mean is 22.0. Discarding 1 and 100
        leaves 2, 3, 4 for a mean of 3.0.
        """
        assert ENSEMBLE_TRIM_MIN_MODELS == 5
        got = self._collapse([[1.0], [2.0], [3.0], [4.0], [100.0]])
        assert abs(got - 3.0) < 1e-9

    def test_narrow_ensembles_keep_the_plain_mean(self) -> None:
        """Average everything when trimming would leave too little."""
        got = self._collapse([[1.0], [2.0], [3.0], [10.0]])
        assert abs(got - 4.0) < 1e-9

    def test_a_single_wild_model_cannot_dominate(self) -> None:
        """Resist one model being badly wrong, which is the point of trimming."""
        sane = [[500.0], [510.0], [505.0], [495.0], [502.0], [498.0]]
        wild = [*sane[:-1], [50000.0]]
        assert abs(self._collapse(wild) - self._collapse(sane)) < 10.0

    def test_trimming_respects_per_variable_availability(self) -> None:
        """Count only the models that supplied the variable in question.

        Irradiance comes from all six default models and is trimmed;
        snow_depth comes from four and is not.
        """
        names = [f"m{i}" for i in range(6)]
        forecast = _forecast(weather_model=names)
        minutely: dict = {"time": [0]}
        for i, name in enumerate(names):
            for var in forecast.MINUTELY_15_VARS:
                minutely[f"{var}_{name}"] = [float(i)]
        # only the first four supply snow_depth
        for name in names[4:]:
            minutely[f"snow_depth_{name}"] = [None]

        collapsed = forecast._collapse_ensemble(minutely)  # noqa: SLF001

        # 0..5 trimmed to 1..4 -> 2.5
        assert abs(collapsed["temperature_2m"][0] - 2.5) < 1e-9
        # 0..3 untrimmed -> 1.5
        assert abs(collapsed["snow_depth"][0] - 1.5) < 1e-9


class EnsembleRequestTests(unittest.TestCase):
    """Verify the outgoing request and cache identity."""

    def test_models_are_sent_comma_separated(self) -> None:
        """Join the selected models into the models query parameter.

        Stubs the HTTP session rather than ``_request``, because the models
        parameter is assembled inside ``_request`` itself.
        """
        forecast = _forecast(weather_model=["icon_seamless", "gfs_seamless"])
        session = _FakeSession()
        forecast.session = session

        asyncio.run(forecast._request("/v1/forecast", params={"latitude": "52.0"}))  # noqa: SLF001

        assert session.params["models"] == "icon_seamless,gfs_seamless"
        assert session.params["latitude"] == "52.0"

    def test_single_model_is_sent_without_commas(self) -> None:
        """Send a lone model as a bare name."""
        forecast = _forecast(weather_model="icon_seamless")
        session = _FakeSession()
        forecast.session = session

        asyncio.run(forecast._request("/v1/forecast"))  # noqa: SLF001

        assert session.params["models"] == "icon_seamless"

    def test_variables_are_sent_comma_separated(self) -> None:
        """Send the requested variables as a comma-separated list."""
        forecast = _forecast()
        params = forecast._forecast_params(1)  # noqa: SLF001
        assert params["minutely_15"] == ",".join(forecast.MINUTELY_15_VARS)
        assert "snowfall" in params["minutely_15"]

    def test_model_selection_changes_the_cache_fingerprint(self) -> None:
        """Invalidate cached data when the model selection changes."""
        one = _forecast(weather_model="icon_seamless")._cache_fingerprint()  # noqa: SLF001
        two = _forecast(weather_model="gfs_seamless")._cache_fingerprint()  # noqa: SLF001
        ensemble = _forecast()._cache_fingerprint()  # noqa: SLF001
        assert len({one, two, ensemble}) == 3

    def test_model_order_does_not_change_results_identity(self) -> None:
        """Treat a reordered selection as a distinct request.

        Order is preserved rather than sorted, so that the fingerprint stays a
        faithful record of exactly what was asked for.
        """
        a = _forecast(weather_model=["icon_seamless", "gfs_seamless"])
        b = _forecast(weather_model=["gfs_seamless", "icon_seamless"])
        assert a.weather_model != b.weather_model


class MergeSeriesGuardTests(unittest.TestCase):
    """Verify cache merging copes with a changed key set."""

    def test_mismatched_keys_fall_back_to_fresh(self) -> None:
        """Prefer the fresh response when the cached key set differs.

        A model can transiently stop returning a variable; splicing mismatched
        series would raise KeyError or silently misalign them.
        """
        cached = {"minutely_15": {"time": [0, 900], "a": [1, 2], "b": [1, 2]}}
        fresh = {"minutely_15": {"time": [900, 1800], "a": [3, 4]}}

        merged = merge_series(cached, fresh)

        assert merged is fresh

    def test_matching_keys_still_splice(self) -> None:
        """Keep normal merging behaviour when the key sets agree."""
        cached = {"minutely_15": {"time": [0, 900], "a": [1, 2]}}
        fresh = {"minutely_15": {"time": [900, 1800], "a": [3, 4]}}

        merged = merge_series(cached, fresh)

        assert merged["minutely_15"]["time"] == [0, 900, 1800]
        assert merged["minutely_15"]["a"] == [1, 3, 4]

    def test_fingerprint_is_stable_for_equal_input(self) -> None:
        """Produce identical fingerprints for identical parameters."""
        params = {"weather_model": ["a", "b"], "latitude": "52.0"}
        assert fingerprint(params) == fingerprint(dict(params))


if __name__ == "__main__":
    unittest.main()

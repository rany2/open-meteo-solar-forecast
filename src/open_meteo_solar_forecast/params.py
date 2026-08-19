"""Parameter normalization and validation helpers."""

from __future__ import annotations

from typing import Any

from .constants import DEFAULT_WEATHER_MODELS
from .exceptions import (
    OpenMeteoSolarForecastConfigError,
    OpenMeteoSolarForecastInvalidModel,
)

VALID_TRACKING = {"none", "azimuth", "tilt", "dual"}


def is_list_like(value: Any, *, tuple_as_list: bool = True) -> bool:
    """Check if value should be interpreted as a list of per-array values."""
    if isinstance(value, list):
        return True
    return tuple_as_list and isinstance(value, tuple)


def normalize_required(name: str, value: Any, target_len: int) -> list[Any]:
    """Normalize a required parameter to a list of per-array values."""
    if is_list_like(value):
        value_list = list(value)
        if len(value_list) == target_len:
            return value_list
        if len(value_list) == 1:
            return value_list * target_len
        msg = f"{name} must be length 1 or match other array parameters"
        raise OpenMeteoSolarForecastConfigError(msg)
    return [value] * target_len


def normalize_param(
    name: str,
    value: Any,
    target_len: int,
    *,
    tuple_as_list: bool = True,
) -> list[Any]:
    """Validate the length of a param and return a list of the same length."""
    if is_list_like(value, tuple_as_list=tuple_as_list):
        value_list = list(value)
        if len(value_list) == target_len:
            return value_list
        if len(value_list) == 1:
            return value_list * target_len
        msg = f"{name} must be the same length as the other parameters"
        raise OpenMeteoSolarForecastConfigError(msg)
    return [value] * target_len


def validate_azimuth(values: list[float]) -> None:
    """Validate azimuth values against the Open-Meteo convention."""
    for azimuth in values:
        if not -180 <= azimuth <= 180:
            msg = (
                f"azimuth {azimuth} is out of range [-180, 180]. "
                "Azimuth uses the Open-Meteo convention: "
                "0 = South, -90 = East, 90 = West, +-180 = North. "
                "To convert a compass bearing (0 = North, 90 = East, "
                "180 = South, 270 = West), subtract 180."
            )
            raise OpenMeteoSolarForecastConfigError(msg)


def validate_tracking(values: list[str]) -> None:
    """Validate tracking mode values."""
    for tracking in values:
        if tracking not in VALID_TRACKING:
            msg = (
                f"tracking must be one of {sorted(VALID_TRACKING)}, got {tracking!r}"
            )
            raise OpenMeteoSolarForecastConfigError(msg)


def validate_albedo(values: list[float]) -> None:
    """Validate ground albedo values."""
    for albedo in values:
        if not 0.0 <= albedo <= 1.0:
            msg = f"albedo must be within [0, 1], got {albedo}"
            raise OpenMeteoSolarForecastConfigError(msg)


def normalize_weather_models(value: Any) -> list[str]:
    """Normalize the weather model selection to a list of model names.

    Accepts ``None`` for the default ensemble, a single name, a
    comma-separated string, or a list/tuple of names. Duplicates are removed
    while preserving order, because requesting the same model twice would
    silently double its weight in the average.
    """
    if value is None:
        return list(DEFAULT_WEATHER_MODELS)

    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, list | tuple):
        candidates = [str(item) for item in value]
    else:
        msg = (
            "weather_model must be a string, a list/tuple of strings, or None; "
            f"got {type(value).__name__}"
        )
        raise OpenMeteoSolarForecastInvalidModel(msg)

    models: list[str] = []
    for candidate in candidates:
        name = candidate.strip()
        if name and name not in models:
            models.append(name)

    if not models:
        msg = "weather_model must name at least one model"
        raise OpenMeteoSolarForecastInvalidModel(msg)

    return models


def validate_ac_kwp(values: list[float]) -> None:
    """Validate inverter capacity values."""
    for ac_kwp in values:
        if ac_kwp <= 0:
            msg = f"ac_kwp must be greater than 0, got {ac_kwp}"
            raise OpenMeteoSolarForecastConfigError(msg)

"""Exceptions for the OpenMeteoSolarForecast API client."""


class OpenMeteoSolarForecastError(Exception):
    """Generic OpenMeteoSolarForecast exception."""


class OpenMeteoSolarForecastConnectionError(OpenMeteoSolarForecastError):
    """OpenMeteoSolarForecast connection exception."""


class OpenMeteoSolarForecastConfigError(OpenMeteoSolarForecastError):
    """OpenMeteoSolarForecast configuration exception."""


class OpenMeteoSolarForecastAuthenticationError(OpenMeteoSolarForecastError):
    """OpenMeteoSolarForecast authentication exception."""


class OpenMeteoSolarForecastRequestError(OpenMeteoSolarForecastError):
    """OpenMeteoSolarForecast request exception."""


class OpenMeteoSolarForecastRatelimitError(OpenMeteoSolarForecastRequestError):
    """OpenMeteoSolarForecast rate limit exception."""


class OpenMeteoSolarForecastInvalidModel(OpenMeteoSolarForecastError):
    """OpenMeteoSolarForecast invalid model exception."""

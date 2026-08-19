"""Exceptions for the OpenMeteoSolarForecast API client."""


class OpenMeteoSolarForecastError(Exception):
    """Generic OpenMeteoSolarForecast exception.

    ``retryable`` marks errors that may succeed on a later attempt
    (outages, rate limits). Non-retryable errors indicate a problem in
    the configuration or request that will not resolve on its own.
    """

    retryable = True


class OpenMeteoSolarForecastConnectionError(OpenMeteoSolarForecastError):
    """OpenMeteoSolarForecast connection exception."""


class OpenMeteoSolarForecastConfigError(OpenMeteoSolarForecastError):
    """OpenMeteoSolarForecast configuration exception."""

    retryable = False


class OpenMeteoSolarForecastAuthenticationError(OpenMeteoSolarForecastError):
    """OpenMeteoSolarForecast authentication exception."""

    retryable = False


class OpenMeteoSolarForecastRequestError(OpenMeteoSolarForecastError):
    """OpenMeteoSolarForecast request exception."""

    retryable = False


class OpenMeteoSolarForecastRatelimitError(OpenMeteoSolarForecastRequestError):
    """OpenMeteoSolarForecast rate limit exception."""

    retryable = True


class OpenMeteoSolarForecastInvalidModel(OpenMeteoSolarForecastError):
    """OpenMeteoSolarForecast invalid model exception."""

    retryable = False

"""Example of how to get an estimate from the Forecast.Solar API."""

import asyncio
import dataclasses  # noqa
from datetime import timedelta
from pprint import pprint  # noqa

from open_meteo_solar_forecast import OpenMeteoSolarForecast


async def main() -> None:
    """Get an estimate from the Forecast.Solar API."""
    async with OpenMeteoSolarForecast(
        latitude=52.16,
        longitude=4.47,
        declination=20,
        azimuth=10,
        dc_kwp=2.160,
        efficiency_factor=0.9,
    ) as forecast:
        estimate = await forecast.estimate()

        # Uncomment this if you want to see what's in the estimate arrays
        # pprint(dataclasses.asdict(estimate))
        print()
        print(f"energy_production_today: {estimate.energy_production_today}")
        print(
            "energy_production_today_remaining: "
            f"{estimate.energy_production_today_remaining}"
        )
        print(
            f"power_highest_peak_time_today: {estimate.power_highest_peak_time_today}"
        )
        print(f"energy_production_tomorrow: {estimate.energy_production_tomorrow}")
        print(
            "power_highest_peak_time_tomorrow: "
            f"{estimate.power_highest_peak_time_tomorrow}"
        )
        print()
        print(f"power_production_now: {estimate.power_production_now}")
        print(
            "power_production in 1 hour: "
            f"{estimate.power_production_at_time(estimate.now() + timedelta(hours=1))}"
        )
        print(
            "power_production in 6 hours: "
            f"{estimate.power_production_at_time(estimate.now() + timedelta(hours=6))}"
        )
        print(
            "power_production in 12 hours: "
            f"{estimate.power_production_at_time(estimate.now() + timedelta(hours=12))}"
        )
        print(
            "power_production in 24 hours: "
            f"{estimate.power_production_at_time(estimate.now() + timedelta(hours=24))}"
        )
        print()
        print(f"energy_current_hour: {estimate.energy_current_hour}")
        print(f"energy_production next hour: {estimate.sum_energy_production(1)}")
        print(f"energy_production next 6 hours: {estimate.sum_energy_production(6)}")
        print(f"energy_production next 12 hours: {estimate.sum_energy_production(12)}")
        print(f"energy_production next 24 hours: {estimate.sum_energy_production(24)}")
        print(f"timezone: {estimate.timezone}")


if __name__ == "__main__":
    asyncio.run(main())

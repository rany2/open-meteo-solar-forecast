"""Example of how to get an estimate from the Forecast.Solar API."""

import asyncio
import dataclasses  # noqa
from datetime import timedelta
from pprint import pprint  # noqa
from open_meteo_solar_forecast import OpenMeteoSolarForecast


async def main() -> None:
    """Get an estimate from the Forecast.Solar API."""
    async with OpenMeteoSolarForecast(
        latitude=51.4,
        longitude=11.9,
        declination=30,
        azimuth=15,
        dc_kwp=0.45,
        efficiency_factor=0.9,
        use_horizon=True,
        horizon_map=((0,7.2),(16,6.1),(19.6,4),(26.8,5.6),(45,9.8),(53.4,13.7),(102.7,19.8),(138.6,16.6),(145.1,12.7),(146.6,14.4),(191.9,20.8),(210.7,20.1),(209.9,32.1),(215.3,48.5),(219.6,52),(235.2,47),(249.3,40),(255.2,36),(265.1,28),(271.7,20),(277.7,18.4),(282.2,18),(288.8,13.4),(292.6,15.5),(300.7,17),(306,21.1),(310.2,21),(314.8,12.6),(325.6,10.7),(332.3,6.7),(334.9,7.1),(342.8,5.8),(360,7.2)), # tuple of 2-tuples
    ) as forecast:
        estimate = await forecast.estimate()

        # Uncomment this if you want to see what's in the estimate arrays
        #pprint(dataclasses.asdict(estimate))
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
    event_loop = asyncio.get_event_loop()
    asyncio.ensure_future(main(),loop=event_loop)
    #asyncio.run(main())
    

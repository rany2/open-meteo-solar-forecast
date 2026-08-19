"""Example of how to get an estimate from the Forecast.Solar API."""

import asyncio
import dataclasses  # noqa
#from datetime import timedelta
from pathlib import Path
from pprint import pprint  # noqa
from open_meteo_solar_forecast import OpenMeteoSolarForecast
import numpy
import matplotlib.pyplot as plt
import pandas as pd

EXAMPLES_DIR = Path(__file__).resolve().parent

async def main() -> None:
    
    horizon_data = numpy.genfromtxt(EXAMPLES_DIR / "horizon_complex.txt", delimiter="\t", dtype=float)
    hm = tuple([tuple(row) for row in horizon_data])
    
    max_snowcover_depth_cm = 5 # cm
    
    latitude=51.4
    longitude=11.9
    declination=27
    azimuth=15
    dc_kwp=0.45
    efficiency_factor=0.9
    past_days = 5
    forecast_days = 3
    
    """Get an estimate from the Forecast.Solar API."""
    async with OpenMeteoSolarForecast(
        latitude=latitude,
        longitude=longitude,
        declination=declination,
        azimuth=azimuth,
        dc_kwp=dc_kwp,
        efficiency_factor=efficiency_factor,
        use_horizon=False,
        horizon_map=hm, # tuple of 2-tuples
        partial_shading=False,
        max_snowcover_depth_cm=max_snowcover_depth_cm,
        past_days=past_days,
        forecast_days=forecast_days,
    ) as forecast:
        estimate_unshaded = await forecast.estimate()
        
    async with OpenMeteoSolarForecast(
        latitude=latitude,
        longitude=longitude,
        declination=declination,
        azimuth=azimuth,
        dc_kwp=dc_kwp,
        efficiency_factor=efficiency_factor,
        use_horizon=True,
        horizon_map=hm, # tuple of 2-tuples
        partial_shading=False,
        max_snowcover_depth_cm=max_snowcover_depth_cm,
        past_days=past_days,
        forecast_days=forecast_days,
    ) as forecast2:
        estimate_shaded = await forecast2.estimate()
        
    async with OpenMeteoSolarForecast(
        latitude=latitude,
        longitude=longitude,
        declination=declination,
        azimuth=azimuth,
        dc_kwp=dc_kwp,
        efficiency_factor=efficiency_factor,
        use_horizon=True,
        horizon_map=hm, # tuple of 2-tuples
        partial_shading=True,
        max_snowcover_depth_cm=max_snowcover_depth_cm,
        past_days=past_days,
        forecast_days=forecast_days,
    ) as forecast3:
        estimate_shaded2 = await forecast3.estimate()
        
        
    
    # set True here to plot forecast data
    if True:
        estimate_unshaded_df = pd.DataFrame(estimate_unshaded.watts.items(), columns=['DateTime','unshaded'])
        estimate_unshaded_df.set_index('DateTime', inplace=True)
        
        estimate_shaded_df = pd.DataFrame(estimate_shaded.watts.items(), columns=['DateTime','shaded'])
        estimate_shaded_df.set_index('DateTime', inplace=True)
        
        estimate_shaded2_df = pd.DataFrame(estimate_shaded2.watts.items(), columns=['DateTime','partially shaded'])
        estimate_shaded2_df.set_index('DateTime', inplace=True)
        
        estimate_period_unshaded_df = pd.DataFrame(estimate_unshaded.wh_period.items(), columns=['DateTime','unshaded'])
        estimate_period_unshaded_df.set_index('DateTime', inplace=True)
        
        estimate_period_shaded_df = pd.DataFrame(estimate_shaded.wh_period.items(), columns=['DateTime','shaded'])
        estimate_period_shaded_df.set_index('DateTime', inplace=True)
        
        estimate_period_shaded2_df = pd.DataFrame(estimate_shaded2.wh_period.items(), columns=['DateTime','partially shaded'])
        estimate_period_shaded2_df.set_index('DateTime', inplace=True)
        
        estimate_daily_unshaded_df = pd.DataFrame(estimate_unshaded.wh_days.items(), columns=['DateTime','unshaded'])
        estimate_daily_unshaded_df.set_index('DateTime', inplace=True)
        
        estimate_daily_shaded_df = pd.DataFrame(estimate_shaded.wh_days.items(), columns=['DateTime','shaded'])
        estimate_daily_shaded_df.set_index('DateTime', inplace=True)
        
        estimate_daily_shaded2_df = pd.DataFrame(estimate_shaded2.wh_days.items(), columns=['DateTime','partially shaded'])
        estimate_daily_shaded2_df.set_index('DateTime', inplace=True)
        
        ax = estimate_unshaded_df.plot(label='unshaded',color='orange',linewidth=1)
        estimate_shaded_df.plot(ax=ax,label='shaded',color='grey',linewidth=1)
        estimate_shaded2_df.plot(ax=ax,label='partially shaded',color='black',linewidth=0.5)
        plt.ylabel('Module power / W')
        plt.show()
        
        ax = estimate_period_unshaded_df.plot(label='unshaded',color='orange',linewidth=1)
        estimate_period_shaded_df.plot(ax=ax,label='shaded',color='grey',linewidth=1)
        estimate_period_shaded2_df.plot(ax=ax,label='partially shaded',color='black',linewidth=0.5)
        plt.ylabel('Hourly energy / Wh')
        plt.show()
        
        ax = estimate_daily_unshaded_df.plot.bar(label='unshaded',color='orange',linewidth=1)
        estimate_daily_shaded_df.plot.bar(ax=ax,label='shaded',color='grey',linewidth=1)
        estimate_daily_shaded2_df.plot.bar(ax=ax,label='partially shaded',color='black',linewidth=0.5)
        plt.ylabel('Daily energy / Wh')
        plt.show()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        asyncio.ensure_future(main())

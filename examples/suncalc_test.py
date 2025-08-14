# -*- coding: utf-8 -*-
"""
Created on Thu Aug 14 11:38:53 2025

@author: thoma
"""

from suncalc import get_position, get_times
import datetime
import pytz
import numpy

localtime = pytz.timezone('Europe/Berlin')
utctime = pytz.timezone('UTC')
date = datetime.datetime(2025,8,14,11,54,0).astimezone(tz=localtime)
latitude_deg = 51.4
longitude_deg = 11.9

position_rad = get_position(date, longitude_deg, latitude_deg)
times = get_times(date, longitude_deg, latitude_deg)

az_deg = (180 + numpy.rad2deg(position_rad['azimuth'])) % 360
alt_deg = numpy.rad2deg(position_rad['altitude'])

print("altitude: " + str(alt_deg) + "°")
print("azimuth (N = 0°, S = 180°): " + str(az_deg) + "°")
print(times)
# -*- coding: utf-8 -*-
"""
Created on Thu Aug 14 12:13:49 2025

@author: thoma
"""

import numpy

horizon_map=[[0,0],[180,30],[360,0]]

x = numpy.array(horizon_map).T

print(str(numpy.interp(90,x[0],x[1])))

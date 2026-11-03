"""Explicit input conversion; all coordinates sent to a device remain WGS84.

GCJ-02 forward formula adapted from https://github.com/wandergis/coordtransform.
The inverse iteratively solves that approximate formula. Numerical convergence
is not a guarantee of real-world positioning accuracy. The rectangular bounds
below are a coarse applicability check, not a geographic border.

The MIT License (MIT)
Copyright (c) 2015 记忆的残骸

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import math

from .models import Coordinate


def _wgs84_to_gcj02(latitude, longitude):
    x, y = longitude - 105.0, latitude - 35.0
    pi, sin = math.pi, math.sin
    dlat = -100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    dlat += (20*sin(6*x*pi) + 20*sin(2*x*pi)) * 2/3
    dlat += (20*sin(y*pi) + 40*sin(y*pi/3)) * 2/3
    dlat += (160*sin(y*pi/12) + 320*sin(y*pi/30)) * 2/3
    dlon = 300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    dlon += (20*sin(6*x*pi) + 20*sin(2*x*pi)) * 2/3
    dlon += (20*sin(x*pi) + 40*sin(x*pi/3)) * 2/3
    dlon += (150*sin(x*pi/12) + 300*sin(x*pi/30)) * 2/3
    axis, eccentricity_squared = 6378245.0, 0.00669342162296594323
    radlat = math.radians(latitude)
    magic = 1 - eccentricity_squared * sin(radlat)**2
    dlat *= 180 / ((axis * (1 - eccentricity_squared) / (magic * math.sqrt(magic))) * pi)
    dlon *= 180 / ((axis / math.sqrt(magic) * math.cos(radlat)) * pi)
    return latitude + dlat, longitude + dlon


def to_wgs84(latitude: float, longitude: float, *, source: str = "wgs84") -> Coordinate:
    """Convert an explicitly identified input to the device's WGS84 convention.

    WGS84 passes through unchanged. GCJ-02 uses an approximate numerical inverse;
    inputs outside its coarse supported bounds raise ValueError. No source is
    inferred from a map provider, and BD-09 is not supported.
    """
    if source not in ("wgs84", "gcj02"):
        raise ValueError("坐标系仅支持 wgs84 或 gcj02")
    coordinate = Coordinate(latitude, longitude)
    if source == "wgs84":
        return coordinate
    if not (3.86 < latitude < 53.55 and 73.66 < longitude < 135.05):
        raise ValueError("GCJ-02 输入超出当前支持的近似范围；请确认坐标系，WGS84 坐标无需转换")
    guess_lat, guess_lon = latitude, longitude
    for _ in range(12):
        projected_lat, projected_lon = _wgs84_to_gcj02(guess_lat, guess_lon)
        error_lat, error_lon = projected_lat - latitude, projected_lon - longitude
        if max(abs(error_lat), abs(error_lon)) < 1e-10:
            return Coordinate(guess_lat, guess_lon)
        guess_lat -= error_lat
        guess_lon -= error_lon
    raise ValueError("GCJ-02 坐标转换未收敛，请检查输入")

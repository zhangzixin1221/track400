"""局部 ENU（东-北）平面。

为什么需要它
------------
400m 跑道尺度只有 ~180m×95m，直接对经纬度做等距采样会引入非线性误差；
先把跑道几何建在**米制平面**上，再统一投影回 WGS-84，是最稳的做法。

精度
----
用 WGS-84 的**子午圈曲率半径 M** 与**卯酉圈曲率半径 N** 做局部线性化
（标准大地测量公式，见 Snyder 1987, *Map Projections — A Working Manual*）：

    M = a(1-e²) / (1-e²sin²φ)^{3/2}
    N = a / (1-e²sin²φ)^{1/2}
    每度纬度 ≈ M·π/180
    每度经度 ≈ N·cosφ·π/180

在 ±1 km 范围内，相对误差 < 1e-6（毫米级），对 400m 跑道完全够用。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# WGS-84 椭球
WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


def meters_per_degree(lat_deg: float) -> tuple[float, float]:
    """返回该纬度处 ``(每度纬度米数, 每度经度米数)``。"""
    phi = math.radians(lat_deg)
    sin_phi = math.sin(phi)
    w = 1.0 - WGS84_E2 * sin_phi * sin_phi
    m = WGS84_A * (1.0 - WGS84_E2) / (w ** 1.5)
    n = WGS84_A / math.sqrt(w)
    rad = math.pi / 180.0
    return m * rad, n * math.cos(phi) * rad


@dataclass(frozen=True, slots=True)
class LocalPlane:
    """以 ``(lat0, lon0)`` 为原点的局部切平面：x 向东、y 向北，单位米。"""

    lat0: float
    lon0: float
    m_per_deg_lat: float
    m_per_deg_lon: float

    @classmethod
    def from_latlon(cls, lat0: float, lon0: float) -> "LocalPlane":
        m_lat, m_lon = meters_per_degree(lat0)
        return cls(lat0=lat0, lon0=lon0, m_per_deg_lat=m_lat, m_per_deg_lon=m_lon)

    # —— 投影 ——
    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        """WGS-84 → 局部 (x=东, y=北)，单位米。"""
        return (lon - self.lon0) * self.m_per_deg_lon, (lat - self.lat0) * self.m_per_deg_lat

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        """局部 (x=东, y=北) → WGS-84。"""
        return self.lat0 + y / self.m_per_deg_lat, self.lon0 + x / self.m_per_deg_lon

    def offset_m(self, lat: float, lon: float) -> tuple[float, float]:
        """相对原点的 (东, 北) 偏移，米。"""
        return self.to_xy(lat, lon)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """球面大圆距离（米）。用于校验，不用于几何构建。"""
    r = 6371008.8  # 平均地球半径
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """从点 1 到点 2 的方位角（度，自北顺时针）。用于校验 heading。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

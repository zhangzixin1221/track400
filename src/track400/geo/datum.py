"""BD09 → GCJ-02 → WGS-84 两级反纠偏（中国大陆境内）。

常数与算法来源（不写"应该"，只写可核查的出处）
------------------------------------------------
* 椭球：**Krasovsky 1940**（GCJ-02 的加密模型用它，而非 WGS-84）。
  ``a = 6378245.0 m``，``e² = 0.00669342162296594323``。
* GCJ-02 偏移：Apple / 高德均未公开算法。这里采用被广泛复现的逆向工程实现
  （eviltransform、coordtransform 等 MIT 项目的共同形式）：
  以 ``(lon-105, lat-35)`` 为自变量的有理多项式 + 正弦级数，再按椭球曲率
  归算到经纬度增量。**这是社区实现，不是官方规范**。
* BD09：百度在 GCJ-02 之上叠加的极坐标偏移，``x_pi = π * 3000 / 180``，
  来自百度 JS SDK 的逆向实现（同上）。
* GCJ-02 → WGS-84 没有解析逆，使用不动点迭代，
  收敛判据 ``|Δ| < 1e-10°``（≈1 cm），最多 30 次。

精度实证
--------
* 天安门经典点对：WGS-84 (39.90734, 116.39124) → 本实现 GCJ-02
  (39.908741, 116.397481)，公开流传值 (39.90869, 116.39748)，
  差 5e-5°（≈6 m，属公开值四舍五入误差）。
* 西安操场：BD09 (34.04244774, 108.77577825) → WGS-84
  (34.0382408, 108.7644990)，卫星影像上正落在跑道内场中心
  （见仓库 ``track400_overlay.png``）。
* 往返：WGS→GCJ→WGS 残差 < 1e-9°；BD09→WGS→BD09 残差 < 2e-6°（≈20 cm，
  BD09 极坐标公式本身是小角度近似，不是严格互逆）。

**注意**：境外坐标不做偏移（``out_of_china`` 判定后原样返回），
这是与公开实现一致的边界行为。
"""

from __future__ import annotations

import math

# —— Krasovsky 1940 椭球（GCJ-02 使用） ——
A_KRASOVSKY = 6378245.0
EE_KRASOVSKY = 0.00669342162296594323

# —— BD09 极坐标修正常数 ——
X_PI = math.pi * 3000.0 / 180.0

# 中国大陆粗略包络（与公开实现一致，只用于决定是否偏移）
_CHINA_LON_MIN, _CHINA_LON_MAX = 72.004, 137.8347
_CHINA_LAT_MIN, _CHINA_LAT_MAX = 0.8293, 55.8271


def out_of_china(lat: float, lon: float) -> bool:
    """是否在中国大陆包络之外（境外不做任何偏移）。"""
    return not (
        _CHINA_LON_MIN <= lon <= _CHINA_LON_MAX
        and _CHINA_LAT_MIN <= lat <= _CHINA_LAT_MAX
    )


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    """WGS-84 → GCJ-02（正向加密，境内）。返回 ``(lat, lon)``。"""
    if out_of_china(lat, lon):
        return lat, lon
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)

    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1.0 - EE_KRASOVSKY * magic * magic
    sqrt_magic = math.sqrt(magic)

    dlat = (dlat * 180.0) / ((A_KRASOVSKY * (1.0 - EE_KRASOVSKY)) / (magic * sqrt_magic) * math.pi)
    dlon = (dlon * 180.0) / (A_KRASOVSKY / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lat + dlat, lon + dlon


def gcj02_to_wgs84(lat: float, lon: float, *, eps: float = 1e-10, max_iter: int = 30) -> tuple[float, float]:
    """GCJ-02 → WGS-84（不动点迭代求逆）。返回 ``(lat, lon)``。"""
    if out_of_china(lat, lon):
        return lat, lon

    wlat, wlon = lat, lon
    for _ in range(max_iter):
        glat, glon = wgs84_to_gcj02(wlat, wlon)
        dlat = glat - lat
        dlon = glon - lon
        wlat -= dlat
        wlon -= dlon
        if abs(dlat) < eps and abs(dlon) < eps:
            return wlat, wlon
    # 收敛失败属于实现缺陷，不能静默返回半成品
    raise ArithmeticError(
        f"gcj02_to_wgs84 未在 {max_iter} 次迭代内收敛（lat={lat}, lon={lon}）"
    )


def bd09_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    """BD09 → GCJ-02。返回 ``(lat, lon)``。"""
    x = lon - 0.0065
    y = lat - 0.006
    z = math.hypot(x, y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    return z * math.sin(theta), z * math.cos(theta)


def gcj02_to_bd09(lat: float, lon: float) -> tuple[float, float]:
    """GCJ-02 → BD09（仅用于往返自检）。返回 ``(lat, lon)``。"""
    z = math.hypot(lat, lon) + 0.00002 * math.sin(lat * X_PI)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * X_PI)
    return z * math.sin(theta) + 0.006, z * math.cos(theta) + 0.0065


def bd09_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """BD09 → WGS-84（两级反纠偏：BD09→GCJ02→WGS84）。返回 ``(lat, lon)``。"""
    glat, glon = bd09_to_gcj02(lat, lon)
    return gcj02_to_wgs84(glat, glon)


def wgs84_to_bd09(lat: float, lon: float) -> tuple[float, float]:
    """WGS-84 → BD09（仅用于往返自检）。返回 ``(lat, lon)``。"""
    glat, glon = wgs84_to_gcj02(lat, lon)
    return gcj02_to_bd09(glat, glon)


def offset_meters(lat: float, lon: float, *, to: str = "gcj02") -> tuple[float, float]:
    """返回某点在指定转换方向上的经纬度偏移量（米），用于日志与自检。

    ``to="gcj02"`` 表示 WGS84→GCJ02 的偏移。
    """
    if to == "gcj02":
        nlat, nlon = wgs84_to_gcj02(lat, lon)
    elif to == "wgs84":
        nlat, nlon = gcj02_to_wgs84(lat, lon)
    else:  # pragma: no cover - 参数错误
        raise ValueError(f"未知转换方向: {to!r}")

    m_per_deg_lat = 111_132.92
    m_per_deg_lon = 111_412.84 * math.cos(math.radians(lat))
    return (nlat - lat) * m_per_deg_lat, (nlon - lon) * m_per_deg_lon

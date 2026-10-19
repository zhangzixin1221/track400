"""坐标转换单测：已知点对、往返残差、偏移方向。"""

from __future__ import annotations

import pytest

from track400.geo.datum import (
    bd09_to_gcj02,
    bd09_to_wgs84,
    gcj02_to_bd09,
    gcj02_to_wgs84,
    offset_meters,
    out_of_china,
    wgs84_to_bd09,
    wgs84_to_gcj02,
)

# 天安门经典点对（公开流传值，5 位小数）
TIANANMEN_WGS = (39.90734, 116.39124)
TIANANMEN_GCJ = (39.90869, 116.39748)

# 用户给的操场中心（BD09）与卫星影像核验后的 WGS-84
XIAN_BD09 = (34.04244774, 108.77577825)
XIAN_WGS = (34.0382408, 108.7644990)


def test_known_pair_tiananmen() -> None:
    """WGS→GCJ 必须复现天安门公开点对（容差 2e-4° ≈ 20 m，防符号/量级错误）。"""
    lat, lon = wgs84_to_gcj02(*TIANANMEN_WGS)
    assert lat == pytest.approx(TIANANMEN_GCJ[0], abs=2e-4)
    assert lon == pytest.approx(TIANANMEN_GCJ[1], abs=2e-4)


def test_reverse_known_pair_tiananmen() -> None:
    lat, lon = gcj02_to_wgs84(*TIANANMEN_GCJ)
    assert lat == pytest.approx(TIANANMEN_WGS[0], abs=2e-4)
    assert lon == pytest.approx(TIANANMEN_WGS[1], abs=2e-4)


def test_xian_center_matches_satellite() -> None:
    """BD09→WGS84 结果必须落在卫星影像上的跑道中心（见 track400_overlay.png）。"""
    lat, lon = bd09_to_wgs84(*XIAN_BD09)
    assert lat == pytest.approx(XIAN_WGS[0], abs=2e-6)
    assert lon == pytest.approx(XIAN_WGS[1], abs=2e-6)


def test_round_trip_wgs_gcj() -> None:
    for lat, lon in (XIAN_WGS, TIANANMEN_WGS, (22.5431, 114.0579), (30.5728, 104.0668)):
        g = wgs84_to_gcj02(lat, lon)
        back = gcj02_to_wgs84(*g)
        assert back[0] == pytest.approx(lat, abs=1e-9)
        assert back[1] == pytest.approx(lon, abs=1e-9)


def test_round_trip_bd_wgs() -> None:
    """BD09→WGS84→BD09 往返：BD09 极坐标公式本身是小角度近似，残差 ~6e-7°（≈6 cm）。"""
    for lat, lon in (XIAN_BD09, (39.915, 116.404), (31.2304, 121.4737)):
        w = bd09_to_wgs84(lat, lon)
        back = wgs84_to_bd09(*w)
        assert back[0] == pytest.approx(lat, abs=2e-6)
        assert back[1] == pytest.approx(lon, abs=2e-6)


def test_bd_gcj_round_trip() -> None:
    g = bd09_to_gcj02(*XIAN_BD09)
    b = gcj02_to_bd09(*g)
    assert b[0] == pytest.approx(XIAN_BD09[0], abs=1e-6)
    assert b[1] == pytest.approx(XIAN_BD09[1], abs=1e-6)


def test_out_of_china_untouched() -> None:
    assert out_of_china(40.0, -74.0) is True
    assert wgs84_to_gcj02(40.0, -74.0) == (40.0, -74.0)
    assert gcj02_to_wgs84(40.0, -74.0) == (40.0, -74.0)


def test_gcj_offset_direction_in_xian() -> None:
    """西安一带实测：GCJ 相对 WGS 向东偏约 +435 m、向南偏约 -167 m（方向随地区变化）。"""
    dlat_m, dlon_m = offset_meters(*XIAN_WGS, to="gcj02")
    assert dlat_m < 0
    assert dlon_m > 0
    assert 50 < abs(dlat_m) < 600
    assert 100 < abs(dlon_m) < 900


def test_bd09_to_wgs84_total_offset() -> None:
    """BD09→WGS84 的总偏移约为 -0.0042° lat / -0.0113° lon（约 465 m 南 + 1040 m 西）。"""
    lat, lon = bd09_to_wgs84(*XIAN_BD09)
    assert (lat - XIAN_BD09[0]) == pytest.approx(-0.004207, abs=5e-5)
    assert (lon - XIAN_BD09[1]) == pytest.approx(-0.011279, abs=5e-5)

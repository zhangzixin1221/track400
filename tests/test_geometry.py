"""跑道几何单测：道次半径、圈长校验、闭合、朝向、连续性。"""

from __future__ import annotations

import math

import pytest

from track400.errors import LaneError
from track400.geo.enu import haversine_m
from track400.track.geometry import (
    INNER_RADIUS_M,
    LANE_WIDTH_M,
    STRAIGHT_M,
    lane_radius,
    lap_length,
    perimeter_check,
    position,
)

R2 = lane_radius(2)
P2 = lap_length(2)
ARC2 = math.pi * R2


def test_lane_radius_values() -> None:
    assert lane_radius(1) == pytest.approx(36.80)
    assert lane_radius(2) == pytest.approx(37.92)
    assert lane_radius(8) == pytest.approx(45.24)


def test_reference_perimeters() -> None:
    """业务锁定值：P(1)=400.00、P(2)=407.04、P(8)=453.03。"""
    chk = perimeter_check()
    assert chk[1] == pytest.approx(400.00, abs=0.01)
    assert chk[2] == pytest.approx(407.04, abs=0.01)
    assert chk[8] == pytest.approx(453.03, abs=0.01)


def test_lane2_closed_form() -> None:
    assert P2 == pytest.approx(2 * STRAIGHT_M + 2 * math.pi * (INNER_RADIUS_M + LANE_WIDTH_M + 0.20))


def test_invalid_lane() -> None:
    for bad in (0, -1, 9, 100):
        with pytest.raises(LaneError):
            lane_radius(bad)


def test_closure_exact() -> None:
    """走满一圈后坐标必须精确回到起点（解析闭合，误差 < 1e-9 m）。"""
    a = position(0.0, R2)
    b = position(P2, R2)
    assert a.x == pytest.approx(b.x, abs=1e-9)
    assert a.y == pytest.approx(b.y, abs=1e-9)
    assert a.heading == pytest.approx(b.heading, abs=1e-9)


def test_chord_sum_converges_to_perimeter() -> None:
    """数值积分校验：弦长和收敛到圈长，误差 < 0.01 m。"""
    n = 200_000
    ds = P2 / n
    prev = position(0.0, R2)
    total = 0.0
    for k in range(1, n + 1):
        cur = position(k * ds, R2)
        total += math.hypot(cur.x - prev.x, cur.y - prev.y)
        prev = cur
    assert total == pytest.approx(P2, abs=0.01)


def test_heading_on_straights() -> None:
    assert position(0.0, R2).heading == pytest.approx(0.0)
    assert position(STRAIGHT_M - 0.001, R2).heading == pytest.approx(0.0)
    west_start = STRAIGHT_M + ARC2
    assert position(west_start + 0.001, R2).heading == pytest.approx(180.0)


def test_heading_on_curves() -> None:
    north_mid = STRAIGHT_M + ARC2 / 2
    assert position(north_mid, R2).heading == pytest.approx(270.0, abs=1e-6)
    south_start = 2 * STRAIGHT_M + ARC2
    south_mid = south_start + ARC2 / 2
    assert position(south_mid, R2).heading == pytest.approx(90.0, abs=1e-6)


def test_position_continuity_at_segments() -> None:
    """各段边界两侧坐标连续（差值 < 1e-6 m）。"""
    boundaries = [STRAIGHT_M, STRAIGHT_M + ARC2, 2 * STRAIGHT_M + ARC2]
    for s in boundaries:
        before = position(s - 1e-6, R2)
        after = position(s + 1e-6, R2)
        assert math.hypot(before.x - after.x, before.y - after.y) < 1e-5


def test_start_point_is_south_end_of_east_straight() -> None:
    p = position(0.0, R2)
    assert p.x == pytest.approx(R2)
    assert p.y == pytest.approx(-STRAIGHT_M / 2)
    assert p.segment == "straight_east"


def test_full_lap_returns_start_in_latlon() -> None:
    """一圈后经纬度闭合误差 < 1 m（这里平面→球面换算后应远小于该阈值）。"""
    from track400.geo.enu import LocalPlane

    plane = LocalPlane.from_latlon(34.0382408, 108.7644990)
    lat0, lon0 = plane.to_latlon(position(0.0, R2).x, position(0.0, R2).y)
    end = position(P2, R2)
    lat1, lon1 = plane.to_latlon(end.x, end.y)
    assert haversine_m(lat0, lon0, lat1, lon1) < 1.0

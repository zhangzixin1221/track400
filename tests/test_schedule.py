"""计划/配速单测：时长、距离、配速误差、时间戳单调、闭合。"""

from __future__ import annotations

import pytest

from track400.errors import ConfigError, PaceError
from track400.geo.enu import haversine_m
from track400.pacing.schedule import (
    build_plan,
    format_pace,
    pace_to_speed,
    speed_to_pace,
)

SPEED = pace_to_speed(240.0)  # 4'00"/km = 4.1667 m/s
CENTER = (34.0382408, 108.7644990)


def _plan(**kw):
    base = dict(lane=2, speed=SPEED, dt=1.0, duration=660.0, center_lat=CENTER[0], center_lon=CENTER[1])
    base.update(kw)
    return build_plan(**base)


def test_pace_conversion() -> None:
    assert SPEED == pytest.approx(4.1666667, abs=1e-6)
    assert speed_to_pace(SPEED) == pytest.approx(240.0)
    assert format_pace(240.0) == "4'00\"/km"


def test_default_pace_3_10() -> None:
    """默认配置改成 3'10"/km 后，速度与格式都要对。"""
    v = pace_to_speed(190.0)
    assert v == pytest.approx(5.2631579, abs=1e-7)
    assert format_pace(190.0) == "3'10\"/km"


def test_distance_mode_5km() -> None:
    """默认目标：5 km @ 3'10"/km → 950 s、12.28 圈、951 点。"""
    p = build_plan(
        lane=2,
        speed=pace_to_speed(190.0),
        dt=1.0,
        distance=5000.0,
        center_lat=CENTER[0],
        center_lon=CENTER[1],
    )
    assert p.total_distance == pytest.approx(5000.0)
    assert p.duration == pytest.approx(950.0, abs=1e-9)
    assert p.laps_completed == pytest.approx(12.2838, abs=1e-3)
    assert p.mean_speed() == pytest.approx(5.2631579, rel=1e-6)
    assert len(p.points) == 951


def test_plan_660s_basics() -> None:
    p = _plan()
    assert p.duration == pytest.approx(660.0)
    assert p.total_distance == pytest.approx(2750.0, abs=1e-6)
    assert len(p.points) == 661
    assert p.perimeter == pytest.approx(407.04, abs=0.01)
    assert p.lap_time == pytest.approx(97.69, abs=0.01)
    assert p.laps_completed == pytest.approx(6.7559, abs=1e-3)


def test_mean_speed_within_acceptance() -> None:
    p = _plan()
    assert p.mean_speed() == pytest.approx(4.1667, abs=0.05)


def test_pace_error_per_interval_below_1pct() -> None:
    p = _plan()
    for a, b in zip(p.points, p.points[1:]):
        v = (b.s - a.s) / (b.t - a.t)
        assert v == pytest.approx(SPEED, rel=0.01)


def test_timestamps_strictly_increasing() -> None:
    p = _plan()
    for a, b in zip(p.points, p.points[1:]):
        assert b.t > a.t


def test_start_point_geometry() -> None:
    p = _plan()
    assert p.start.x == pytest.approx(37.92)
    assert p.start.y == pytest.approx(-84.39 / 2)
    assert p.start.lap == 1
    assert p.start.heading == pytest.approx(0.0)


def test_start_latlon_is_center_plus_offset() -> None:
    p = _plan()
    # 起点在中心正南 42.195 m、正东 37.92 m
    from track400.geo.enu import LocalPlane

    plane = LocalPlane.from_latlon(*CENTER)
    lat, lon = plane.to_latlon(37.92, -42.195)
    assert p.start.lat == pytest.approx(lat, abs=1e-12)
    assert p.start.lon == pytest.approx(lon, abs=1e-12)


def test_single_lap_closure_under_1m() -> None:
    p = build_plan(
        lane=2,
        speed=SPEED,
        dt=1.0,
        laps=1.0,
        center_lat=CENTER[0],
        center_lon=CENTER[1],
    )
    d = haversine_m(p.start.lat, p.start.lon, p.end.lat, p.end.lon)
    assert d < 1.0
    assert d == pytest.approx(0.0, abs=1e-6)
    assert p.end.s == pytest.approx(p.perimeter, abs=1e-6)


def test_laps_mode_duration() -> None:
    p = build_plan(
        lane=2,
        speed=SPEED,
        dt=1.0,
        laps=7.0,
        center_lat=CENTER[0],
        center_lon=CENTER[1],
    )
    assert p.total_distance == pytest.approx(7 * p.perimeter, abs=1e-9)
    assert p.duration == pytest.approx(7 * 407.0373 / SPEED, abs=0.5)
    assert p.duration == pytest.approx(684.0, abs=1.0)


def test_duration_and_laps_mutually_exclusive() -> None:
    with pytest.raises(ConfigError):
        build_plan(lane=2, speed=SPEED, dt=1.0, center_lat=CENTER[0], center_lon=CENTER[1])
    with pytest.raises(ConfigError):
        build_plan(
            lane=2, speed=SPEED, dt=1.0, duration=660.0, laps=7.0,
            center_lat=CENTER[0], center_lon=CENTER[1],
        )


def test_invalid_speed() -> None:
    with pytest.raises(PaceError):
        pace_to_speed(0)

"""采样单测：时间轴、等间距、分段覆盖、角位移。"""

from __future__ import annotations

import math

import pytest

from track400.errors import DtError
from track400.track.geometry import lane_radius
from track400.track.sampling import max_angular_step, sample, timeline

SPEED = 1000.0 / 240.0  # 4'00"/km
R2 = lane_radius(2)


def test_timeline_660s_dt1() -> None:
    ts = timeline(660.0, 1.0)
    assert len(ts) == 661
    assert ts[0] == 0.0
    assert ts[-1] == 660.0
    assert all(b - a == pytest.approx(1.0) for a, b in zip(ts, ts[1:]))


def test_timeline_partial_last_step() -> None:
    ts = timeline(684.2, 1.0)
    assert ts[-1] == pytest.approx(684.2)
    assert ts[-1] - ts[-2] == pytest.approx(0.2)


def test_dt_bounds_rejected() -> None:
    for bad in (0.0, -1.0, 0.4, 1.1, 2.0):
        with pytest.raises(DtError):
            timeline(660.0, bad)


def test_sample_count_and_spacing() -> None:
    smp = sample(radius=R2, speed=SPEED, dt=1.0, duration_s=660.0)
    assert len(smp) == 661
    assert smp[0].s == 0.0
    assert smp[-1].s == pytest.approx(2750.0, abs=1e-6)
    for a, b in zip(smp, smp[1:]):
        assert b.s - a.s == pytest.approx(SPEED, abs=1e-9)
        assert b.t - a.t == pytest.approx(1.0, abs=1e-12)


def test_segments_all_covered() -> None:
    smp = sample(radius=R2, speed=SPEED, dt=1.0, duration_s=660.0)
    segs = {s.segment for s in smp}
    assert segs == {"straight_east", "curve_north", "straight_west", "curve_south"}


def test_lap_indices_increase() -> None:
    smp = sample(radius=R2, speed=SPEED, dt=1.0, duration_s=660.0)
    laps = [s.lap for s in smp]
    assert laps == sorted(laps)
    assert laps[0] == 1
    assert laps[-1] == 7  # 2750 m / 407.04 m ≈ 6.756 → 第 7 圈


def test_angular_step_reasonable() -> None:
    dtheta = max_angular_step(R2, SPEED * 1.0)
    assert dtheta == pytest.approx(math.radians(6.30), abs=0.02)
    assert dtheta < math.radians(10)

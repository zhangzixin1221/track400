"""控制器单测：时间轴、暂停/恢复、断线等待、保活、stop 必 clear。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from track400.clock import VirtualClock
from track400.controller import Controller, State
from track400.device.fake import FakeDevice
from track400.pacing.schedule import build_plan, pace_to_speed

CENTER = (34.0382408, 108.7644990)


def make_plan(duration: float = 60.0, dt: float = 1.0, lane: int = 2):
    return build_plan(
        lane=lane,
        speed=pace_to_speed(240.0),
        dt=dt,
        duration=duration,
        center_lat=CENTER[0],
        center_lon=CENTER[1],
    )


def test_full_run_virtual_clock(tmp_path: Path) -> None:
    """660 s 计划在虚拟时钟下瞬时跑完，时间轴必须精确。"""
    plan = make_plan(660.0)
    clock = VirtualClock()
    dev = FakeDevice(tmp_path / "run.jsonl", now=clock.now)
    ctl = Controller(plan, dev, clock=clock)

    final = asyncio.run(ctl.run())

    assert final is State.STOPPED
    assert ctl.sets == 661
    assert dev.cleared is True
    assert len(dev.sent) == 661
    assert dev.sent[0][0].t == 0.0
    assert dev.sent[-1][0].t == pytest.approx(660.0)
    walls = [w for _, w in dev.sent]
    gaps = [b - a for a, b in zip(walls, walls[1:])]
    assert max(gaps) == pytest.approx(1.0, abs=1e-9)
    assert min(gaps) == pytest.approx(1.0, abs=1e-9)


def test_stop_midway_still_clears(tmp_path: Path) -> None:
    plan = make_plan(60.0)
    clock = VirtualClock()
    dev = FakeDevice(tmp_path / "stop.jsonl", now=clock.now)
    ctl: Controller

    def on_status(st) -> None:
        if st.index >= 20:
            ctl.stop()

    ctl = Controller(plan, dev, clock=clock, on_status=on_status)
    final = asyncio.run(ctl.run())

    assert final is State.STOPPED
    assert 20 <= ctl.sets <= 22
    assert dev.cleared is True
    assert len(dev.sent) == ctl.sets


def test_pause_resume_preserves_spacing(tmp_path: Path) -> None:
    plan = make_plan(60.0)
    clock = VirtualClock()
    dev = FakeDevice(tmp_path / "pause.jsonl", now=clock.now)
    ctl: Controller
    paused = {"hit": False}

    def on_status(st) -> None:
        if st.index == 10 and not paused["hit"]:
            paused["hit"] = True
            ctl.pause()

    ctl = Controller(plan, dev, clock=clock, on_status=on_status)

    async def go() -> State:
        task = asyncio.create_task(ctl.run())
        while ctl.state is not State.PAUSED:
            await asyncio.sleep(0)
        clock.advance(30.0)  # 显式推进虚拟时钟，确定性暂停 30 s
        for _ in range(3):
            await asyncio.sleep(0)
        ctl.resume()
        return await task

    final = asyncio.run(go())
    assert final is State.STOPPED
    assert ctl.sets == 61
    walls = [w for _, w in dev.sent]
    gap = walls[11] - walls[10]
    assert gap >= 30.0  # 暂停时长必须计入墙钟，但不能压缩配速


def test_keepalive_during_pause(tmp_path: Path) -> None:
    plan = make_plan(20.0)
    clock = VirtualClock()
    dev = FakeDevice(tmp_path / "keepalive.jsonl", now=clock.now)
    ctl: Controller

    def on_status(st) -> None:
        if st.index == 2:
            ctl.pause()

    ctl = Controller(plan, dev, clock=clock, keepalive_s=5.0, on_status=on_status)

    async def go() -> State:
        task = asyncio.create_task(ctl.run())
        while ctl.state is not State.PAUSED:
            await asyncio.sleep(0)
        for _ in range(6):  # 6 × 5 s，每 5 s 一次保活
            clock.advance(5.0)
            for _ in range(3):
                await asyncio.sleep(0)
        ctl.resume()
        return await task

    asyncio.run(go())
    assert ctl.keepalive_count >= 4
    assert dev.cleared is True


def test_reconnect_waits_for_resume_then_continues(tmp_path: Path) -> None:
    plan = make_plan(30.0)
    clock = VirtualClock()
    dev = FakeDevice(tmp_path / "reconnect.jsonl", now=clock.now, fail_after=10, fail_times=1)
    ctl: Controller
    seen: list[State] = []
    resumed = {"done": False}

    def on_status(st) -> None:
        seen.append(st.state)
        if st.state is State.RECONNECTED and not resumed["done"]:
            resumed["done"] = True
            ctl.resume()

    ctl = Controller(plan, dev, clock=clock, reconnect_interval_s=1.0, on_status=on_status)
    final = asyncio.run(ctl.run())

    assert final is State.STOPPED
    assert State.LOST in seen
    assert State.RECONNECTED in seen
    assert ctl.reconnects == 1
    assert ctl.sets == 31
    assert dev.cleared is True
    # 断线点被重投，序列不跳号
    idx = [s.index for s, _ in dev.sent]
    assert idx == list(range(31))


def test_stop_before_start_clears(tmp_path: Path) -> None:
    plan = make_plan(10.0)
    clock = VirtualClock()
    dev = FakeDevice(tmp_path / "early.jsonl", now=clock.now)
    ctl = Controller(plan, dev, clock=clock)
    ctl.stop()
    final = asyncio.run(ctl.run())
    assert final is State.STOPPED
    assert ctl.sets == 0
    assert dev.cleared is True


def test_user_stop_flag(tmp_path: Path) -> None:
    """区分「用户中断」与「正常跑完」——CLI 据此返回 130 或 0。"""
    plan = make_plan(5.0)
    clock = VirtualClock()
    dev = FakeDevice(tmp_path / "u.jsonl", now=clock.now)
    ctl = Controller(plan, dev, clock=clock)
    assert ctl.user_stopped is False
    ctl.stop()
    assert ctl.user_stopped is True


def test_auto_resume_after_reconnect(tmp_path: Path) -> None:
    plan = make_plan(10.0)
    clock = VirtualClock()
    dev = FakeDevice(tmp_path / "auto.jsonl", now=clock.now, fail_after=3, fail_times=1)
    ctl = Controller(
        plan,
        dev,
        clock=clock,
        reconnect_interval_s=1.0,
        auto_resume_on_reconnect=True,
    )
    final = asyncio.run(ctl.run())
    assert final is State.STOPPED
    assert ctl.reconnects == 1
    assert ctl.sets == 11
    assert dev.cleared is True

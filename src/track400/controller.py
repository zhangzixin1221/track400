"""控制面：时间轴推进、暂停/恢复、保活、断线重连、安全退出。

状态机
------
    IDLE ──run──▶ RUNNING ──pause──▶ PAUSED ──resume──▶ RUNNING
                     │                 │
                     ├──stop───────────┴──▶ STOPPED（finally 必 clear）
                     │
                     └──DeviceError──▶ LOST ──probe 成功──▶ RECONNECTED
                                                              │
                                                        等 resume（按你的要求，
                                                        不自动续跑）

时间轴
------
每个点有绝对截止时刻 ``anchor + t + paused_total``。
暂停时长在 resume 时累加进 ``paused_total``，因此**暂停不会压缩配速**。
`stop` 走 ``finally``，无论 Ctrl+C、异常还是正常结束都会调用 ``device.clear()``。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .clock import Clock, RealClock
from .device.base import DeviceSample, IDevice
from .errors import DeviceError
from .pacing.schedule import Plan, TimedPoint


class State(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    LOST = "lost"
    RECONNECTED = "reconnected"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class Status:
    state: State
    index: int
    total: int
    t: float
    s: float
    lap: int
    s_in_lap: float
    remaining: float
    message: str = ""


class _Stopped(Exception):
    """内部信号：用户要求停止。"""


class Controller:
    """驱动 ``Plan`` 逐点注入。"""

    POLL_S = 0.05

    def __init__(
        self,
        plan: Plan,
        device: IDevice,
        *,
        clock: Clock | None = None,
        keepalive_s: float = 10.0,
        reconnect_interval_s: float = 2.0,
        auto_resume_on_reconnect: bool = False,
        on_status: Callable[[Status], None] | None = None,
    ) -> None:
        self.plan = plan
        self.device = device
        self._clock = clock or RealClock()
        self._keepalive_s = keepalive_s
        self._reconnect_interval_s = reconnect_interval_s
        self._auto_resume = auto_resume_on_reconnect
        self._on_status = on_status or (lambda _st: None)

        self._state = State.IDLE
        self._stop_flag = False
        self._user_stop = False
        self._paused = False
        self._resume_evt = asyncio.Event()

        self._anchor = 0.0
        self._paused_total = 0.0
        self._pause_started: float | None = None

        self._last_point: TimedPoint | None = None
        self._last_sent = 0.0
        self._last_status_t = -1.0
        self._kept_alive = 0
        self._sets = 0
        self.reconnects = 0

    # —— 控制面 ——
    def pause(self) -> None:
        if self._state in (State.RUNNING, State.RECONNECTED):
            self._paused = True

    def resume(self) -> None:
        self._paused = False
        self._resume_evt.set()

    def stop(self) -> None:
        self._user_stop = True
        self._stop_flag = True
        self._resume_evt.set()

    @property
    def user_stopped(self) -> bool:
        """是否由用户/信号主动停止（区别于跑完全程）。"""
        return self._user_stop

    @property
    def state(self) -> State:
        return self._state

    @property
    def sets(self) -> int:
        return self._sets

    @property
    def keepalive_count(self) -> int:
        return self._kept_alive

    # —— 主循环 ——
    async def run(self) -> State:
        """执行整条计划；返回终态。异常时也会 clear。"""
        await self.device.probe()
        await self.device.open()
        self._anchor = self._clock.now()
        self._state = State.RUNNING

        try:
            for point in self.plan.points:
                if not await self._wait_until(point):
                    break
                await self._deliver(point)
                self._emit(point)
        except _Stopped:
            pass
        finally:
            self._state = State.STOPPED
            await self._safe_clear()
            try:
                await self.device.close()
            except DeviceError:
                pass
            final = self._last_point or self.plan.points[0]
            self._emit(final, message="stopped")
        return self._state

    # —— 时间轴 ——
    async def _wait_until(self, point: TimedPoint) -> bool:
        while True:
            if self._stop_flag:
                return False

            if self._paused:
                if self._pause_started is None:
                    self._pause_started = self._clock.now()
                    self._set_state(State.PAUSED, point)
                await self._clock.sleep(self.POLL_S)
                await self._maybe_keepalive()
                continue

            if self._pause_started is not None:
                self._paused_total += self._clock.now() - self._pause_started
                self._pause_started = None
                self._set_state(State.RUNNING, point)

            deadline = self._anchor + point.t + self._paused_total
            remaining = deadline - self._clock.now()
            if remaining <= 0:
                return True
            await self._clock.sleep(min(remaining, self.POLL_S))

    # —— 注入 ——
    async def _deliver(self, point: TimedPoint) -> None:
        while True:
            if self._stop_flag:
                raise _Stopped
            try:
                await self.device.set(self._sample(point))
                self._last_point = point
                self._last_sent = self._clock.now()
                self._sets += 1
                return
            except DeviceError as exc:
                await self._recover(exc)

    async def _recover(self, exc: DeviceError) -> None:
        self._set_state(State.LOST, self._last_point, message=str(exc))
        wait_start = self._clock.now()

        while not self._stop_flag:
            try:
                await self.device.close()
            except DeviceError:
                pass
            await self._clock.sleep(self._reconnect_interval_s)
            try:
                await self.device.probe()
                await self.device.open()
                break
            except DeviceError:
                continue
        else:
            raise _Stopped

        self.reconnects += 1
        self._paused = True
        self._resume_evt.clear()
        self._set_state(State.RECONNECTED, self._last_point, message="已重连，等待 resume")
        if self._auto_resume:
            self._resume_evt.set()

        # 按你的要求：重连成功不自动续跑，必须显式 resume
        while not self._stop_flag and not self._resume_evt.is_set():
            await self._clock.sleep(self.POLL_S)
            await self._maybe_keepalive()

        if self._stop_flag:
            raise _Stopped

        # 整段中断（含重连等待 + 人工确认等待）都从时间轴里扣掉，配速不受影响
        self._paused_total += self._clock.now() - wait_start
        self._resume_evt.clear()
        self._paused = False
        self._set_state(State.RUNNING, self._last_point)

    async def _maybe_keepalive(self) -> None:
        """暂停期间按 ``keepalive_s`` 重发最后一个点（幂等）。"""
        if self._last_point is None:
            return
        if self._clock.now() - self._last_sent < self._keepalive_s:
            return
        try:
            await self.device.set(self._sample(self._last_point))
            self._kept_alive += 1
        except DeviceError:
            return  # 重连由主循环在 resume 后处理
        self._last_sent = self._clock.now()

    async def _safe_clear(self) -> None:
        try:
            await self.device.clear()
        except DeviceError:
            # stop 阶段不能再抛，否则会掩盖真实错误；记录后由调用方决定
            self._emit(self._last_point or self.plan.points[0], message="clear 失败：真实定位可能未恢复")

    # —— 状态 ——
    def _sample(self, point: TimedPoint) -> DeviceSample:
        return DeviceSample(
            index=point.index,
            t=point.t,
            s=point.s,
            lat=point.lat,
            lon=point.lon,
            lap=point.lap,
            s_in_lap=point.s_in_lap,
            heading=point.heading,
        )

    def _emit(self, point: TimedPoint, message: str = "") -> None:
        st = Status(
            state=self._state,
            index=point.index,
            total=len(self.plan.points),
            t=point.t,
            s=point.s,
            lap=point.lap,
            s_in_lap=point.s_in_lap,
            remaining=max(0.0, self.plan.duration - point.t),
            message=message,
        )
        self._last_status_t = point.t
        self._on_status(st)

    def _set_state(self, state: State, point: TimedPoint | None, message: str = "") -> None:
        if self._state is state:
            return
        self._state = state
        ref = point or self._last_point or self.plan.points[0]
        self._emit(ref, message=message or state.value)

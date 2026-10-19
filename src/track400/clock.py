"""时钟抽象：让 660 s 的计划可以在毫秒内确定性跑完。

* :class:`RealClock` —— 真机使用，``time.monotonic`` + ``asyncio.sleep``。
* :class:`VirtualClock` —— 测试/干跑使用，``sleep`` 直接推进虚拟时间，
  不占用真实时间；同一事件循环内的所有任务共享同一条时间轴。
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """单调时间（秒）。"""

    async def sleep(self, seconds: float) -> None:
        """等待 ``seconds`` 秒。"""


class RealClock:
    """真实时钟。"""

    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        if seconds > 0:
            await asyncio.sleep(seconds)


class VirtualClock:
    """虚拟时钟：``sleep(d)`` 只把 ``d`` 加到内部时间上，并让出一次调度。"""

    __slots__ = ("_t",)

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    async def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self._t += seconds
        await asyncio.sleep(0)

    def advance(self, seconds: float) -> None:
        """手动推进（测试用）。"""
        self._t += seconds


class ScaledClock:
    """把任意时钟的时间轴按 ``factor`` 加速（``factor=60`` 即 60 倍速）。

    仅用于干跑/调试；真机配速验收必须用 1.0。
    """

    def __init__(self, base: Clock, factor: float) -> None:
        if factor <= 0:
            raise ValueError(f"factor 必须为正，收到 {factor!r}")
        self._base = base
        self._factor = float(factor)
        self._t0 = base.now()

    def now(self) -> float:
        return self._t0 + (self._base.now() - self._t0) * self._factor

    async def sleep(self, seconds: float) -> None:
        await self._base.sleep(seconds / self._factor)

"""FakeDevice：无设备时的落盘实现。

每收到一个点就追加一行 JSONL，字段足以离线复算圈数/配速/闭合：

    {"type":"set","i":0,"t":0.0,"s":0.0,"lat":34.0378604,"lon":108.7649096,
     "lap":1,"s_in_lap":0.0,"heading":0.0,"wall":0.0}

``wall`` 是注入时刻的时钟读数（由控制器注入的 clock 提供），
用于验证「暂停后时间轴是否被正确平移」。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from ..errors import DeviceError
from .base import DeviceInfo, DeviceSample, IDevice


class FakeDevice(IDevice):
    """把坐标流写进 JSONL，可选模拟延迟与断线。"""

    def __init__(
        self,
        path: str | Path,
        *,
        fail_after: int | None = None,
        fail_times: int = 1,
        latency_s: float = 0.0,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.path = Path(path)
        self.sent: list[tuple[DeviceSample, float]] = []  # (sample, wall)
        self.cleared = False
        self.closed = False
        self.open_count = 0

        self._now = now or time.monotonic
        self._latency = latency_s
        self._fail_after = fail_after
        self._fail_left = fail_times if fail_after is not None else 0
        self._file = None

    # —— IDevice ——
    async def probe(self) -> DeviceInfo:
        return DeviceInfo(
            udid="FAKE-0000",
            name="FakeDevice",
            ios_version="0.0",
            driver="fake",
        )

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 首次 open 截断，重连时追加，避免断线重连把前半段坐标流冲掉
        mode = "w" if self.open_count == 0 else "a"
        self._file = self.path.open(mode, encoding="utf-8", newline="\n")
        self.open_count += 1
        self.closed = False
        self._write({"type": "meta", "driver": "fake", "open_count": self.open_count})

    async def set(self, sample: DeviceSample) -> None:
        if self._file is None:
            raise DeviceError("FakeDevice 未 open()", hint="先调用 open()")
        if self._latency > 0:
            await asyncio.sleep(self._latency)

        if self._fail_left and len(self.sent) >= (self._fail_after or 0):
            self._fail_left -= 1
            raise DeviceError(
                "模拟断线：USB 连接丢失",
                hint="重插线缆后控制器会重连，并等待 resume 再续跑",
            )

        wall = self._now()
        self.sent.append((sample, wall))
        self._write({"type": "set", **asdict(sample), "wall": wall})

    async def clear(self) -> None:
        self.cleared = True
        self._write({"type": "clear"})

    async def close(self) -> None:
        self.closed = True
        self._write({"type": "close"})
        if self._file is not None:
            self._file.close()
            self._file = None

    # —— 内部 ——
    def _write(self, obj: dict) -> None:
        assert self._file is not None
        self._file.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._file.flush()

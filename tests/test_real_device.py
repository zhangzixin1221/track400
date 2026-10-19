"""RealDevice 单测：不接设备，只验证包装层的错误映射与资源语义。"""

from __future__ import annotations

import asyncio

import pytest

from track400.device.base import DeviceSample
from track400.device.real import RealDevice
from track400.errors import DeviceError


class _StubLS:
    def __init__(self, *, fail_on_set: bool = False) -> None:
        self.calls: list[tuple[float, float]] = []
        self.cleared = 0
        self.closed = 0
        self._fail_on_set = fail_on_set

    async def set(self, lat: float, lon: float) -> None:
        if self._fail_on_set:
            raise RuntimeError("DTX 断线")
        self.calls.append((lat, lon))

    async def clear(self) -> None:
        self.cleared += 1

    async def close(self) -> None:
        self.closed += 1


def _sample() -> DeviceSample:
    return DeviceSample(
        index=0,
        t=0.0,
        s=0.0,
        lat=34.0378604,
        lon=108.7649096,
        lap=1,
        s_in_lap=0.0,
        heading=0.0,
    )


def test_set_before_open_raises() -> None:
    dev = RealDevice()
    with pytest.raises(DeviceError, match="会话未打开"):
        asyncio.run(dev.set(_sample()))


def test_clear_before_open_is_noop() -> None:
    dev = RealDevice()
    asyncio.run(dev.clear())
    assert dev.clears == 0


def test_set_forwards_and_records_latency() -> None:
    dev = RealDevice()
    stub = _StubLS()
    dev._ls = stub

    asyncio.run(dev.set(_sample()))
    assert stub.calls == [(34.0378604, 108.7649096)]
    assert len(dev.latencies) == 1
    assert dev.latencies[0] >= 0.0


def test_set_failure_wrapped_as_device_error() -> None:
    dev = RealDevice()
    dev._ls = _StubLS(fail_on_set=True)

    with pytest.raises(DeviceError, match="注入坐标失败"):
        asyncio.run(dev.set(_sample()))


def test_clear_counts_and_close_releases() -> None:
    dev = RealDevice()
    stub = _StubLS()
    dev._ls = stub

    asyncio.run(dev.clear())
    assert stub.cleared == 1
    assert dev.clears == 1

    asyncio.run(dev.close())
    assert stub.closed == 1
    assert dev._ls is None
    # 幂等：再关一次不应抛
    asyncio.run(dev.close())

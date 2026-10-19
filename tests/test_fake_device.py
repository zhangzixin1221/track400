"""FakeDevice 单测：JSONL 结构、断线注入、clear/close 语义。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from track400.device.base import DeviceSample
from track400.device.fake import FakeDevice
from track400.errors import DeviceError


def _sample(i: int, t: float) -> DeviceSample:
    return DeviceSample(
        index=i,
        t=t,
        s=t * 4.1666667,
        lat=34.038,
        lon=108.764,
        lap=1,
        s_in_lap=0.0,
        heading=0.0,
    )


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "fake.jsonl"
    dev = FakeDevice(path, now=lambda: 123.5)

    async def go() -> None:
        await dev.probe()
        await dev.open()
        await dev.set(_sample(0, 0.0))
        await dev.set(_sample(1, 1.0))
        await dev.clear()
        await dev.close()

    asyncio.run(go())
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["type"] == "meta"
    assert [r["type"] for r in rows] == ["meta", "set", "set", "clear", "close"]
    assert rows[1]["lat"] == 34.038
    assert rows[2]["t"] == 1.0
    assert rows[1]["wall"] == 123.5
    assert dev.cleared is True
    assert dev.closed is True


def test_fail_after_n_points(tmp_path: Path) -> None:
    dev = FakeDevice(tmp_path / "f.jsonl", fail_after=2, fail_times=1)

    async def go() -> None:
        await dev.open()
        for i in range(3):
            if i < 2:
                await dev.set(_sample(i, float(i)))
            else:
                with pytest.raises(DeviceError):
                    await dev.set(_sample(i, float(i)))
        await dev.clear()
        await dev.close()

    asyncio.run(go())
    assert len(dev.sent) == 2
    assert dev.cleared


def test_set_without_open_raises(tmp_path: Path) -> None:
    dev = FakeDevice(tmp_path / "x.jsonl")

    async def go() -> None:
        with pytest.raises(DeviceError, match="未 open"):
            await dev.set(_sample(0, 0.0))

    asyncio.run(go())

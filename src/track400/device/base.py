"""设备抽象层：``IDevice`` 接口与数据载体。

设计约束
--------
* 控制器只依赖本模块，**不 import pymobiledevice3**；
  真机实现放在 ``device/real.py``（Step 5），无设备环境也能跑全链路。
* 每次注入都携带完整上下文（``DeviceSample``），
  这样 FakeDevice 能落盘出一份可审计的坐标流，
  RealDevice 也能据此打印耗时。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """设备探测结果。"""

    udid: str
    name: str
    ios_version: str
    driver: str  # "fake" / "pymobiledevice3-dvt"


@dataclass(frozen=True, slots=True)
class DeviceSample:
    """一次位置注入的完整上下文。"""

    index: int
    t: float  # 相对起跑时刻的秒数
    s: float  # 累计距离（米）
    lat: float
    lon: float
    lap: int
    s_in_lap: float
    heading: float


class IDevice(ABC):
    """位置注入设备的最小接口。"""

    @abstractmethod
    async def probe(self) -> DeviceInfo:
        """探测设备是否可用（不改变设备状态）。"""

    @abstractmethod
    async def open(self) -> None:
        """建立注入会话（真机：隧道 + DVT + LocationSimulation）。"""

    @abstractmethod
    async def set(self, sample: DeviceSample) -> None:
        """把设备位置设为 ``sample`` 的经纬度。"""

    @abstractmethod
    async def clear(self) -> None:
        """停止模拟，恢复真实定位。``stop`` 路径必须调用。"""

    @abstractmethod
    async def close(self) -> None:
        """释放会话资源（不负责 clear，clear 由控制器显式调用）。"""

"""真机注入层：USB → 无 root userspace RSD 隧道 → DVT → LocationSimulation。

调用点核实状态
--------------
实测环境：iPhone 16 Pro Max（iPhone17,2）/ iOS 27.0.1 (24A446) / Windows 10 / pymobiledevice3 11.36.0。

========  ==================================================  ==================================================
#         调用                                                状态
========  ==================================================  ==================================================
1         ``create_using_usbmux(serial=...)``                  **已核实**：lockdown info 正常返回
2         ``UserspaceRsdTunnel(serial).aopen()``               **已核实**：非管理员 2.4 s 建成
3         ``rsd.get_service_port("...dtservicehub")``          **已核实**：DDI 已挂载时返回端口；缺失抛 InvalidServiceError
4         ``DvtProvider(rsd).connect()``                       **已核实**：``dvt device-information`` 通
5         ``LocationSimulation(dvt).connect()``                **已核实**：通道打开成功
6         ``set(lat, lon)`` → simulateLocationWithLatitude…    **已核实（协议层）**：DTX 调用被接受；视觉覆盖待验收
7         ``clear()`` → stopLocationSimulation                 **已核实**：CLI clear 退出码 0
8         ``auto_mount(rsd)``（DDI 缺失时）                    **未核实**：本机 raw.githubusercontent.com 被 hosts 拦截，路径保留
9         锁屏 / 11 分钟长连接                                  **未核实**
========  ==================================================  ==================================================

约束
----
* ``UserspaceRsdTunnel`` 是**进程级单例**：同一进程同时只能有一条隧道。
  因此 ``open()`` 前必须保证上一次 ``close()`` 已完成；失败路径也要回滚。
* 所有调用都在同一个 asyncio 事件循环里串行执行（控制器保证）。
"""

from __future__ import annotations

import time
from typing import Any

from ..errors import DeviceError
from .base import DeviceInfo, DeviceSample, IDevice

DDI_SERVICE = "com.apple.instruments.dtservicehub"


def _exc_chain(exc: BaseException | None) -> list[str]:
    """把异常链压成 ``Name(msg) ← Name(msg)`` 形式，空消息的异常也能看清类型。"""
    out: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        name = type(cur).__name__
        msg = str(cur).strip()
        out.append(f"{name}({msg})" if msg else name)
        cur = cur.__cause__ or cur.__context__
    return out


def _format_exc(exc: BaseException) -> str:
    return " ← ".join(_exc_chain(exc))


# usbmuxd（Apple Mobile Device Service）没跑起来时的特征
_USBMUXD_MARKERS = ("usbmuxd", "usbmuxd", "connectionfailedtousbmuxd", "winerror 1225")


def _connect_hint(exc: BaseException) -> str:
    """连接失败时给出可执行的修复命令，而不是泛泛的四条检查。"""
    chain = " ".join(_exc_chain(exc)).lower()
    if any(marker in chain for marker in _USBMUXD_MARKERS):
        return (
            "usbmuxd 没在运行 —— 也就是 Windows 侧的「Apple Mobile Device Service」被停了，"
            "电脑根本看不到 iPhone（跟数据线、信任无关）。\n"
            "  最省事：双击项目根目录的 fix-usbmuxd.bat（会弹 UAC，点「是」）。\n"
            "  或【管理员】PowerShell 执行：\n"
            "      Set-Service 'Apple Mobile Device Service' -StartupType Automatic\n"
            "      Start-Service 'Apple Mobile Device Service'\n"
            "  不想开管理员窗口：打开一次「Apple Devices / Apple 设备」应用，它会把服务拉起来。\n"
            "  服务起来后重跑本命令；仍失败再查数据线 / 「信任此电脑」/ 开发者模式。"
        )
    return (
        "检查：① 数据线是否支持数据传输；② 手机是否已「信任此电脑」；"
        "③ 设置→隐私与安全性→开发者模式是否开启；④ Apple Mobile Device Service 是否在运行"
    )


class RealDevice(IDevice):
    """通过 pymobiledevice3 的 DVT 通道注入位置。"""

    def __init__(self, udid: str | None = None, *, autopair: bool = True) -> None:
        self.udid = udid
        self._autopair = autopair

        self._tunnel: Any = None
        self._rsd: Any = None
        self._dvt: Any = None
        self._ls: Any = None

        self.latencies: list[float] = []
        self.open_seconds: float = 0.0
        self.clears: int = 0

    # —— 探测 ——
    async def probe(self) -> DeviceInfo:
        from pymobiledevice3.lockdown import create_using_usbmux

        try:
            lockdown = await create_using_usbmux(serial=self.udid, autopair=self._autopair)
        except Exception as exc:
            raise DeviceError(
                f"无法连接设备: {_format_exc(exc)}",
                hint=_connect_hint(exc),
            ) from exc

        try:
            return DeviceInfo(
                udid=str(lockdown.udid),
                name=str(lockdown.display_name or "iPhone"),
                ios_version=str(lockdown.product_version),
                driver="pymobiledevice3-dvt",
            )
        finally:
            try:
                await lockdown.close()
            except Exception:
                pass

    # —— 会话 ——
    async def open(self) -> None:
        if self._ls is not None:
            return

        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel

        t0 = time.perf_counter()
        try:
            self._tunnel = UserspaceRsdTunnel(serial=self.udid, autopair=self._autopair)
            self._rsd = await self._tunnel.aopen()
        except Exception as exc:
            await self._close_tunnel()
            raise DeviceError(
                f"RSD 隧道建立失败: {_format_exc(exc)}",
                hint=(
                    "① 先解锁手机一次（iOS 17+ 重启后需解锁才提供开发者服务）；"
                    "② 确认同一进程没有别的隧道在跑（userspace 隧道是单例）；"
                    "③ 重新插拔 USB 后重试"
                ),
            ) from exc

        if not self._ddi_ready():
            await self._mount_ddi()

        try:
            from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
            from pymobiledevice3.services.dvt.instruments.location_simulation import (
                LocationSimulation,
            )

            self._dvt = DvtProvider(self._rsd)
            await self._dvt.connect()
            self._ls = LocationSimulation(self._dvt)
            await self._ls.connect()
        except Exception as exc:
            await self.close()
            raise DeviceError(
                f"DVT 通道打开失败: {exc}",
                hint="多半是开发者镜像（DDI）未挂载或已失效；重启手机后需要重新挂载",
            ) from exc

        self.open_seconds = time.perf_counter() - t0

    async def set(self, sample: DeviceSample) -> None:
        if self._ls is None:
            raise DeviceError("设备会话未打开", hint="先调用 open()")
        t0 = time.perf_counter()
        try:
            await self._ls.set(sample.lat, sample.lon)
        except Exception as exc:
            raise DeviceError(
                f"注入坐标失败（t={sample.t:.1f}s lat={sample.lat:.7f} lon={sample.lon:.7f}）: {exc}",
                hint="若为断线，重插 USB；控制器会重连并等待 resume",
            ) from exc
        self.latencies.append(time.perf_counter() - t0)

    async def clear(self) -> None:
        if self._ls is None:
            return
        try:
            await self._ls.clear()
            self.clears += 1
        except Exception as exc:
            raise DeviceError(
                f"恢复真实定位失败: {exc}",
                hint="手动执行 `pymobiledevice3 developer dvt simulate-location clear` 兜底",
            ) from exc

    async def close(self) -> None:
        if self._ls is not None:
            try:
                await self._ls.close()
            except Exception:
                pass
            self._ls = None
        if self._dvt is not None:
            try:
                await self._dvt.close()
            except Exception:
                pass
            self._dvt = None
        self._rsd = None
        await self._close_tunnel()

    # —— DDI ——
    def _ddi_ready(self) -> bool:
        from pymobiledevice3.exceptions import InvalidServiceError

        try:
            self._rsd.get_service_port(DDI_SERVICE)  # type: ignore[union-attr]
            return True
        except InvalidServiceError:
            return False
        except Exception:
            return False

    async def _mount_ddi(self) -> None:
        from pymobiledevice3.services.mobile_image_mounter import auto_mount

        try:
            await auto_mount(self._rsd)
        except Exception as exc:
            raise DeviceError(
                f"开发者镜像（DDI）未挂载，自动挂载失败: {exc}",
                hint=(
                    "三条修复路径（按成功率排序）："
                    "① 用 Xcode / Apple Configurator 对该机挂载一次 DDI；"
                    "② 修好 raw.githubusercontent.com 的访问后重试（本机 hosts 把它指到了 127.0.0.1）；"
                    "③ 手动下载 Personalized DDI 后用 `pymobiledevice3 mounter` 指定镜像挂载"
                ),
            ) from exc

        if not self._ddi_ready():
            raise DeviceError(
                "DDI 挂载命令返回成功，但 dtservicehub 仍不可见",
                hint="重启手机后再挂载一次；确认开发者模式未被关闭",
            )

    # —— 清理 ——
    async def _close_tunnel(self) -> None:
        tunnel, self._tunnel = self._tunnel, None
        if tunnel is None:
            return
        try:
            await tunnel.aclose()
        except Exception:
            pass

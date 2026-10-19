"""track400 命令行入口。

用法
----
::

    # 默认配置：5 km @ 3'10"/km（950 s，约 12.28 圈）
    track400

    # 无设备干跑（60 倍速）
    track400 --fake --speedup 60 --pace 3:10 --distance 5km

    # 真机，指定道次
    track400 --pace 3:10 --distance 5km --lane 2

    # 百度坐标直接给
    track400 --bd09 34.04244774,108.77577825 --laps 12

运行期控制
----------
* ``p`` 暂停 / ``r`` 继续 / ``s`` 停止（仅在交互式终端里可用；POSIX 上需回车确认）
* ``Ctrl+C`` 等价于停止，退出码 130
* 无论哪条路径，``stop`` 都会走 ``finally`` 调用 ``clear()`` 恢复真实定位

退出码
------
``0`` 正常跑完；``1`` 运行错误（带错误码与自愈建议）；``2`` 参数错误；``130`` 用户中断。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .clock import RealClock, ScaledClock
from .controller import Controller, State
from .device.fake import FakeDevice
from .errors import ConfigError, Track400Error
from .geo.datum import bd09_to_wgs84
from .gpx import write_gpx
from .pacing.schedule import (
    DEFAULT_DISTANCE_M,
    DEFAULT_PACE_SEC_PER_KM,
    build_plan,
    format_pace,
    parse_pace,
    speed_to_pace,
)
from .render import ProgressRenderer, format_mmss
from . import __version__

# 卫星影像核验后的操场中心（WGS-84）
DEFAULT_CENTER = (34.0382408, 108.7644990)

# 默认配速文本（3'10"/km），由秒/公里常量派生，避免两处写死
DEFAULT_PACE_TEXT = f"{int(DEFAULT_PACE_SEC_PER_KM) // 60}:{int(DEFAULT_PACE_SEC_PER_KM) % 60:02d}"


# ----------------------------------------------------------------------
# 参数
# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="track400",
        description="沿标准 400m 跑道连续绕圈，经 iPhone 开发者通道注入位置",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    center = ap.add_argument_group("位置")
    center.add_argument("--lat", type=float, help="操场中心纬度（WGS-84）")
    center.add_argument("--lon", type=float, help="操场中心经度（WGS-84）")
    center.add_argument(
        "--bd09",
        metavar="LAT,LON",
        help="操场中心（百度 BD09），内部自动两级反纠偏到 WGS-84",
    )

    run = ap.add_argument_group("跑步参数")
    run.add_argument("--pace", default=DEFAULT_PACE_TEXT, help="配速，如 3:10 或 190（秒/公里）")
    run.add_argument("--lane", type=int, default=2, help="道次 1..8")
    target = run.add_mutually_exclusive_group()
    target.add_argument("--laps", type=float, help="跑几圈（三选一）")
    target.add_argument("--duration", type=float, help="总时长秒数（三选一）")
    target.add_argument(
        "--distance",
        default=None,
        metavar="5km",
        help=f"总距离，支持 5km / 5000m / 5000（默认 {DEFAULT_DISTANCE_M / 1000:g}km）",
    )
    run.add_argument("--heading", type=float, default=0.0, help="起跑朝向（度，自北顺时针）")
    run.add_argument("--dt", type=float, default=1.0, help="采样间隔 0.5~1.0 秒")

    dev = ap.add_argument_group("设备")
    dev.add_argument("--fake", action="store_true", help="不接手机，坐标流落盘到 JSONL")
    dev.add_argument("--out", default=None, help="FakeDevice 的 JSONL 输出路径")
    dev.add_argument("--udid", default=None, help="目标设备 UDID（默认第一台 USB 设备）")
    dev.add_argument(
        "--resume-after-reconnect",
        action="store_true",
        help="断线重连后自动续跑（默认停下来等你按 r）",
    )
    dev.add_argument("--keepalive", type=float, default=10.0, help="暂停期间保活重发间隔（秒）")

    extra = ap.add_argument_group("其它")
    extra.add_argument("--gpx-out", default=None, help="同时写出一份 GPX")
    extra.add_argument(
        "--speedup",
        type=float,
        default=1.0,
        help="时间加速倍数，仅允许与 --fake 同用（干跑用）",
    )
    extra.add_argument("--every", type=float, default=1.0, help="进度刷新间隔（秒）")
    extra.add_argument("--verbose", "-v", action="count", default=0, help="日志详细程度（可叠加）")
    extra.add_argument("--version", action="version", version=f"track400 {__version__}")
    return ap


def _setup_logging(verbose: int) -> None:
    level = logging.DEBUG if verbose >= 2 else (logging.INFO if verbose == 1 else logging.WARNING)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # pymobiledevice3 默认会打一条 "Trying again over a no-root userspace tunnel" 的 WARNING
    logging.getLogger("pymobiledevice3").setLevel(
        logging.INFO if verbose else logging.ERROR
    )


def _parse_bd09(text: str) -> tuple[float, float]:
    raw = text.replace("，", ",").strip()
    parts = [p for p in raw.split(",") if p.strip()]
    if len(parts) != 2:
        raise ConfigError(
            f"--bd09 需要 '纬度,经度' 两个数，收到 {text!r}",
            hint="示例：--bd09 34.04244774,108.77577825",
        )
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise ConfigError(f"--bd09 解析失败: {text!r}") from exc
    return lat, lon


def resolve_center(args: argparse.Namespace) -> tuple[float, float]:
    """优先级：--bd09 > (--lat,--lon) > 内置默认中心。"""
    if args.bd09 is not None:
        if args.lat is not None or args.lon is not None:
            raise ConfigError("--bd09 与 --lat/--lon 不能同时使用")
        lat, lon = _parse_bd09(args.bd09)
        return bd09_to_wgs84(lat, lon)

    if (args.lat is None) != (args.lon is None):
        raise ConfigError(
            "--lat 与 --lon 必须同时提供",
            hint="要么两个都给（WGS-84），要么用 --bd09 给百度坐标",
        )
    if args.lat is not None:
        if not (-90.0 <= args.lat <= 90.0):
            raise ConfigError(f"纬度越界: {args.lat}")
        if not (-180.0 <= args.lon <= 180.0):
            raise ConfigError(f"经度越界: {args.lon}")
        return args.lat, args.lon

    return DEFAULT_CENTER


def _parse_distance(text: str) -> float:
    """解析距离文本为米：``5km`` / ``5000m`` / ``5000`` / ``5.0``（公里）。"""
    s = str(text).strip().lower().replace(" ", "")
    try:
        if s.endswith("km"):
            return float(s[:-2]) * 1000.0
        if s.endswith("k"):
            return float(s[:-1]) * 1000.0
        if s.endswith("m"):
            return float(s[:-1])
        return float(s)
    except ValueError as exc:
        raise ConfigError(
            f"无法解析距离 {text!r}",
            hint="用法：--distance 5km / --distance 5000m / --distance 5000",
        ) from exc


def resolve_target(args: argparse.Namespace) -> dict[str, float]:
    """把 --duration / --laps / --distance 归一成 build_plan 的参数。

    三者都没给时，默认 **5 km**。
    """
    if args.duration is not None:
        return {"duration": float(args.duration)}
    if args.laps is not None:
        return {"laps": float(args.laps)}
    if args.distance is not None:
        return {"distance": _parse_distance(args.distance)}
    return {"distance": DEFAULT_DISTANCE_M}


# ----------------------------------------------------------------------
# 键盘控制
# ----------------------------------------------------------------------
class _Keyboard:
    """在交互式终端里把 p/r/s 投递回事件循环。"""

    def __init__(self, loop: asyncio.AbstractEventLoop, ctl: Controller) -> None:
        self.loop = loop
        self.ctl = ctl
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if not sys.stdin.isatty():
            return False
        self._thread = threading.Thread(target=self._run, name="track400-keys", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _post(self, action: str) -> None:
        def apply() -> None:
            if action == "pause":
                self.ctl.pause()
            elif action == "resume":
                self.ctl.resume()
            else:
                self.ctl.stop()

        self.loop.call_soon_threadsafe(apply)

    def _handle(self, ch: str) -> None:
        mapping = {"p": ("pause", "暂停"), "r": ("resume", "继续"), "s": ("stop", "停止"), "q": ("stop", "停止")}
        if ch in mapping:
            action, label = mapping[ch]
            self._post(action)
            sys.stdout.write(f"\n[控制] {label}\n")
            sys.stdout.flush()

    def _run(self) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                while not self._stop.is_set():
                    if msvcrt.kbhit():
                        self._handle(msvcrt.getwch().lower())
                    time.sleep(0.05)
            else:
                import select

                while not self._stop.is_set():
                    ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if ready:
                        self._handle(sys.stdin.read(1).lower())
        except Exception:
            return


# ----------------------------------------------------------------------
# 装配与运行
# ----------------------------------------------------------------------
def _make_device(args: argparse.Namespace, clock: Any) -> Any:
    if args.fake:
        out = Path(args.out) if args.out else Path("runs") / f"fake_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
        print(f"设备  : FakeDevice（无手机），落盘 {out}")
        return FakeDevice(out, now=clock.now)

    from .device.real import RealDevice

    print("设备  : 正在连接 iPhone …")
    return RealDevice(args.udid)


async def _amain(
    args: argparse.Namespace,
    plan: Any,
    device: Any,
    renderer: ProgressRenderer,
    clock: Any,
) -> int:
    loop = asyncio.get_running_loop()
    ctl = Controller(
        plan,
        device,
        clock=clock,
        keepalive_s=args.keepalive,
        auto_resume_on_reconnect=args.resume_after_reconnect,
        on_status=renderer,
    )

    keys = _Keyboard(loop, ctl)
    has_keys = keys.start()
    if has_keys:
        print("控制  : p 暂停 / r 继续 / s 停止（Ctrl+C 亦可）")
    else:
        print("控制  : 非交互终端，仅 Ctrl+C 可停止")

    old_handler = signal.getsignal(signal.SIGINT)

    def _on_sigint(signum: int, frame: Any) -> None:
        loop.call_soon_threadsafe(ctl.stop)

    try:
        signal.signal(signal.SIGINT, _on_sigint)
    except (ValueError, OSError):
        pass  # 非主线程等场景，退化为默认行为

    try:
        final = await ctl.run()
    finally:
        keys.stop()
        try:
            signal.signal(signal.SIGINT, old_handler)
        except (ValueError, OSError):
            pass
        renderer.finish()

    elapsed = max(plan.duration, 0.0)
    print(
        f"\n完成  : {final.value} | 注入 {ctl.sets} 点 | 重连 {ctl.reconnects} 次 | "
        f"保活 {ctl.keepalive_count} 次 | 计划 {format_mmss(elapsed)}"
    )
    if hasattr(device, "latencies") and device.latencies:
        lat = sorted(device.latencies)
        print(
            f"延迟  : 中位 {lat[len(lat) // 2] * 1000:.1f} ms | max {lat[-1] * 1000:.1f} ms"
        )

    if ctl.user_stopped:
        return 130
    return 0


def run(args: argparse.Namespace) -> int:
    center = resolve_center(args)
    pace_s = parse_pace(args.pace)
    speed = 1000.0 / pace_s

    if args.duration is None and args.laps is None and args.distance is None:
        print(f"目标  : 未指定，使用默认 {DEFAULT_DISTANCE_M / 1000:g} km")
    if args.speedup != 1.0 and not args.fake:
        raise ConfigError(
            "--speedup 只允许与 --fake 同用",
            hint="真机请用 1.0，否则定位会跳变，不符合验收条件",
        )

    plan = build_plan(
        lane=args.lane,
        speed=speed,
        dt=args.dt,
        center_lat=center[0],
        center_lon=center[1],
        heading=args.heading,
        **resolve_target(args),
    )

    print("== track400 ==")
    print(f"中心  : {center[0]:.7f}, {center[1]:.7f} (WGS-84)")
    print(f"计划  : {plan.summary_line()}")
    print(f"配速  : {format_pace(speed_to_pace(plan.speed))} | 单圈 {plan.lap_time:.3f} s")
    print(f"起点  : {plan.start.lat:.7f}, {plan.start.lon:.7f} heading={plan.start.heading:.1f}°")

    if args.gpx_out:
        path = write_gpx(plan, args.gpx_out, name=f"track400 lane{plan.lane}")
        print(f"GPX   : {path}")

    base_clock = RealClock()
    clock = ScaledClock(base_clock, args.speedup) if args.speedup != 1.0 else base_clock
    device = _make_device(args, clock)
    renderer = ProgressRenderer(plan, every_s=args.every)

    return asyncio.run(_amain(args, plan, device, renderer, clock))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        return run(args)
    except Track400Error as exc:
        print(f"\n错误[{exc.code}]: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"建议: {exc.hint}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

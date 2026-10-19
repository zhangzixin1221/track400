#!/usr/bin/env python3
"""真机验证脚本：短时注入 → 观察状态 → clear。

    python tools/live_test.py --probe-only
    python tools/live_test.py --seconds 10 --pace 6:00

默认用修正后的操场中心（34.0382408, 108.7644990）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from track400.clock import RealClock  # noqa: E402
from track400.controller import Controller  # noqa: E402
from track400.device.real import RealDevice  # noqa: E402
from track400.errors import Track400Error  # noqa: E402
from track400.pacing.schedule import build_plan, format_pace, parse_pace, speed_to_pace  # noqa: E402
from track400.render import ProgressRenderer  # noqa: E402

CENTER = (34.0382408, 108.7644990)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="track400 真机验证")
    ap.add_argument("--udid", default=None)
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--pace", default="6:00")
    ap.add_argument("--lane", type=int, default=2)
    ap.add_argument("--dt", type=float, default=1.0)
    ap.add_argument("--every", type=float, default=1.0)
    args = ap.parse_args(argv)

    dev = RealDevice(args.udid)

    if args.probe_only:
        try:
            info = asyncio.run(dev.probe())
        except Track400Error as exc:
            print(f"FAIL {type(exc).__name__}: {exc}")
            if exc.hint:
                print(f"     提示: {exc.hint}")
            return 1
        print(f"设备: {info.name} | iOS {info.ios_version} | UDID {info.udid} | driver {info.driver}")
        return 0

    plan = build_plan(
        lane=args.lane,
        speed=1000.0 / parse_pace(args.pace),
        dt=args.dt,
        duration=args.seconds,
        center_lat=CENTER[0],
        center_lon=CENTER[1],
    )
    renderer = ProgressRenderer(plan, every_s=args.every)
    ctl = Controller(plan, dev, clock=RealClock(), on_status=renderer)

    print("== 真机计划 ==")
    print(" ", plan.summary_line())
    print(f"  配速 {format_pace(speed_to_pace(plan.speed))} | 起点 ({plan.start.lat:.7f},{plan.start.lon:.7f})")
    print("== 进度 ==")

    try:
        final = asyncio.run(ctl.run())
    except Track400Error as exc:
        print(f"\nFAIL {type(exc).__name__}: {exc}")
        if exc.hint:
            print(f"     提示: {exc.hint}")
        return 1
    finally:
        renderer.finish()

    lat = sorted(dev.latencies)
    print(f"\n终态: {final.value} | 注入 {ctl.sets} 点 | 重连 {ctl.reconnects} 次 | clear {dev.clears} 次")
    print(f"会话建立耗时: {dev.open_seconds:.2f} s")
    if lat:
        print(
            f"单点注入延迟: min {lat[0]*1000:.1f} ms | "
            f"中位 {lat[len(lat)//2]*1000:.1f} ms | max {lat[-1]*1000:.1f} ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""无设备全链路干跑：FakeDevice + 控制器 + 进度显示。

默认用 :class:`VirtualClock`，660 s 的计划在毫秒内跑完，但**虚拟时间轴是精确的**
（点间隔仍为 Δt），所以圈数/配速/剩余时间的显示与真机完全一致。

    python tools/dry_run.py --lane 2 --pace 4:00 --duration 660
    python tools/dry_run.py --laps 7 --every 30
    python tools/dry_run.py --real          # 按真实时间跑 11 分钟（验证显示刷新）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from track400.clock import RealClock, VirtualClock  # noqa: E402
from track400.controller import Controller  # noqa: E402
from track400.device.fake import FakeDevice  # noqa: E402
from track400.errors import Track400Error  # noqa: E402
from track400.pacing.schedule import build_plan, format_pace, parse_pace, speed_to_pace  # noqa: E402
from track400.render import ProgressRenderer  # noqa: E402

CENTER = (34.0382408, 108.7644990)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="track400 无设备干跑")
    ap.add_argument("--lane", type=int, default=2)
    ap.add_argument("--pace", default="3:10", help="配速，如 3:10 或 190（秒/公里）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--duration", type=float, default=None, help="总时长（秒）")
    g.add_argument("--laps", type=float, default=None, help="圈数")
    ap.add_argument("--dt", type=float, default=1.0, help="采样间隔 0.5~1.0")
    ap.add_argument("--out", default="runs/fake_lane2.jsonl")
    ap.add_argument("--every", type=float, default=60.0, help="进度打印间隔（虚拟秒）")
    ap.add_argument("--real", action="store_true", help="用真实时钟（会真的跑满时长）")
    ap.add_argument("--keepalive", type=float, default=10.0)
    return ap.parse_args(argv)


def _summarize_jsonl(path: Path, expected: int) -> int:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    sets = [r for r in rows if r.get("type") == "set"]
    clears = [r for r in rows if r.get("type") == "clear"]
    closes = [r for r in rows if r.get("type") == "close"]

    ok = True
    print("\n== 落盘校验 ==")
    print(f"  set 行数 : {len(sets)}（期望 {expected}）")
    print(f"  clear    : {len(clears)} 次")
    print(f"  close    : {len(closes)} 次")
    if len(sets) != expected:
        print("  ✗ 点数不符")
        ok = False
    if not clears:
        print("  ✗ stop 后没有 clear —— 真实定位不会恢复！")
        ok = False
    if sets:
        ts = [r["t"] for r in sets]
        ds = [b - a for a, b in zip(ts, ts[1:])]
        same = all(abs(d - 1.0) < 1e-9 for d in ds)
        print(f"  首/末 t  : {ts[0]:.3f} / {ts[-1]:.3f} s")
        print(f"  Δt 恒定  : {same}")
        print(f"  末点     : ({sets[-1]['lat']:.7f}, {sets[-1]['lon']:.7f}) lap={sets[-1]['lap']}")
        ok = ok and same
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.duration is None and args.laps is None:
        args.duration = 950.0  # 默认 5 km @ 3'10"/km

    pace_s = parse_pace(args.pace)
    plan = build_plan(
        lane=args.lane,
        speed=1000.0 / pace_s,
        dt=args.dt,
        duration=args.duration,
        laps=args.laps,
        center_lat=CENTER[0],
        center_lon=CENTER[1],
    )

    clock = RealClock() if args.real else VirtualClock()
    out = Path(args.out)
    device = FakeDevice(out, now=clock.now)
    renderer = ProgressRenderer(plan, every_s=args.every)
    ctl = Controller(plan, device, clock=clock, keepalive_s=args.keepalive, on_status=renderer)

    print("== 计划 ==")
    print(" ", plan.summary_line())
    print(f"  配速 {format_pace(speed_to_pace(plan.speed))} | 单圈 {plan.lap_time:.3f} s")
    print(f"  时钟 {'真实（会跑满）' if args.real else '虚拟（瞬时）'} | 落盘 {out}")
    print("== 进度 ==")

    t_start = clock.now()
    try:
        final = asyncio.run(ctl.run())
    except Track400Error as exc:
        print(f"\nFAIL {type(exc).__name__}: {exc}")
        if exc.hint:
            print(f"     提示: {exc.hint}")
        return 1
    finally:
        renderer.finish()
    elapsed = clock.now() - t_start

    print(f"\n终态: {final.value} | 注入 {ctl.sets} 点 | 重连 {ctl.reconnects} 次 | 保活 {ctl.keepalive_count} 次")
    print(f"耗时: {elapsed:.1f} s（计划 {plan.duration:.1f} s）")
    return _summarize_jsonl(out, len(plan.points))


if __name__ == "__main__":
    raise SystemExit(main())

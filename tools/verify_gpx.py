#!/usr/bin/env python3
"""独立 GPX 校验脚本（不依赖 track400 的其它模块也能跑）。

用法::

    python tools/verify_gpx.py runs/route.gpx
    python tools/verify_gpx.py runs/route.gpx --points 661 --duration 660 --dt 1.0 \
        --distance 2750 --lane 2

退出码：0 = 全部通过；1 = 校验失败；2 = 参数/文件错误。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from track400.errors import Track400Error  # noqa: E402
from track400.gpx import validate_gpx  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="校验 track400 生成的 GPX")
    ap.add_argument("gpx", type=Path, help="GPX 文件路径")
    ap.add_argument("--points", type=int, default=None, help="期望点数")
    ap.add_argument("--duration", type=float, default=None, help="期望总时长（秒）")
    ap.add_argument("--dt", type=float, default=None, help="期望采样间隔（秒）")
    ap.add_argument("--distance", type=float, default=None, help="期望总距离（米）")
    ap.add_argument("--lane", type=int, default=None, help="期望道次")
    args = ap.parse_args(argv)

    try:
        stats = validate_gpx(
            args.gpx,
            expect_points=args.points,
            expect_duration=args.duration,
            expect_dt=args.dt,
            expect_distance=args.distance,
            expect_lane=args.lane,
        )
    except Track400Error as exc:
        print(f"FAIL  {type(exc).__name__}: {exc}")
        if exc.hint:
            print(f"      提示: {exc.hint}")
        return 1

    print(f"文件      : {args.gpx}")
    print(f"点数      : {stats.points}")
    print(f"首/末时间 : {stats.first_time.isoformat()}  ->  {stats.last_time.isoformat()}")
    print(f"总时长    : {stats.duration:.6f} s")
    print(f"Δt        : [{stats.dt_min:.6f}, {stats.dt_max:.6f}] s")
    print(f"总距离    : {stats.distance:.3f} m")
    print(f"道次      : {stats.lane}")
    if stats.segments:
        print("段落点数  : " + ", ".join(f"{k}={v}" for k, v in sorted(stats.segments.items())))
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

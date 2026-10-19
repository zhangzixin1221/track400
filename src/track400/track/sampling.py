"""等间距采样：沿跑道按固定弧长步进取点。

采样策略
--------
* 位置由 ``geometry.position(s)`` 解析给出，**不需要**逐段拼装；
  直道/半圆的分段性由位置函数本身保证（不会在切点处丢点或重复点）。
* 步长 ``ds = v * dt``（默认 4.1667 m / 1.0 s）。
* 弯道角位移 ``dθ = ds / R``；``dt`` 过大时 ``dθ`` 会明显，
  表现为屏幕上"瞬移"。默认 1.0 s、第 2 道时 ``dθ ≈ 6.3°``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator

from ..errors import DtError, MathError
from .geometry import STRAIGHT_M, Fix, position


@dataclass(frozen=True, slots=True)
class Sample:
    """时间轴上第 k 个采样点（纯几何，尚未投影到经纬度）。"""

    index: int
    t: float  # 相对起跑时刻的秒数
    s: float  # 累计弧长（米）
    x: float  # 东（米）
    y: float  # 北（米）
    heading: float  # 度，自北顺时针
    segment: str
    lap: int  # 1 起
    s_in_lap: float


def timeline(duration_s: float, dt: float) -> list[float]:
    """生成时间轴：``0, dt, 2dt, ...``，末点精确等于 ``duration_s``。

    末段可能短于 ``dt``（当总时长不是 ``dt`` 的整数倍时），
    这是有意的：总时长是业务硬约束，不能被采样间隔改写。
    """
    if dt <= 0:
        raise DtError(f"采样间隔必须为正，收到 {dt!r}")
    if not (0.5 <= dt <= 1.0):
        raise DtError(
            f"采样间隔 dt={dt} 超出允许区间 [0.5, 1.0] s",
            hint="dt 过大会在弯道产生肉眼可见的瞬移；按规格请用 0.5~1.0",
        )
    if duration_s <= 0:
        raise MathError(f"总时长必须为正，收到 {duration_s!r}")

    n = int(math.floor(duration_s / dt + 1e-12))
    times = [k * dt for k in range(n + 1)]
    if duration_s - times[-1] > 1e-9:
        times.append(duration_s)
    else:
        times[-1] = duration_s
    return times


def sample_lap_arc(radius: float, total_distance: float, ds: float) -> Iterator[Fix]:
    """仅按弧长采样（调试/校验用，不带时间）。"""
    if ds <= 0:
        raise MathError(f"步长必须为正，收到 {ds!r}")
    p = 2.0 * math.pi * radius + 2.0 * STRAIGHT_M
    n = int(total_distance / ds)
    for k in range(n + 1):
        yield position(k * ds % p, radius)


def sample(
    *,
    radius: float,
    speed: float,
    dt: float,
    duration_s: float,
) -> list[Sample]:
    """生成整条轨迹的几何采样。

    参数
    ----
    radius : 丈量线半径（米）
    speed : 配速换算出的速度（m/s）
    dt : 采样间隔（秒），必须在 [0.5, 1.0]
    duration_s : 总时长（秒）
    """
    if speed <= 0:
        raise MathError(f"速度必须为正，收到 {speed!r}")

    p = 2.0 * math.pi * radius + 2.0 * STRAIGHT_M
    times = timeline(duration_s, dt)
    out: list[Sample] = []
    for k, t in enumerate(times):
        s = speed * t
        fix = position(s, radius)
        lap = int(s // p) + 1
        out.append(
            Sample(
                index=k,
                t=t,
                s=s,
                x=fix.x,
                y=fix.y,
                heading=fix.heading,
                segment=fix.segment,
                lap=lap,
                s_in_lap=fix.s_in_lap,
            )
        )
    return out


def max_angular_step(radius: float, ds: float) -> float:
    """弯道单步角位移（弧度），用于评估瞬移风险。"""
    return ds / radius

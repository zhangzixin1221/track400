"""标准 400m 田径场几何。

参数（业务已锁定，直接代入）
----------------------------
* 直段：``STRAIGHT_M = 84.39 m``，两段。
* 内半圆（内突沿）半径：``INNER_RADIUS_M = 36.5 m``。
* 道宽：``LANE_WIDTH_M = 1.22 m``。
* 丈量线外移：第 1 道 ``0.30 m``；第 N>1 道 ``0.20 m``。

公式
----
第 1 道丈量半径：``R1 = 36.5 + 0.30 = 36.80``
第 N 道（N>1）：``R(N) = 36.5 + 1.22*(N-1) + 0.20``
一圈：``P(N) = 2*84.39 + 2*pi*R(N)``

校验（保留 2 位）
-----------------
``P(1) = 400.00``、``P(2) = 407.04``、``P(8) = 453.03``（单测逐项断言）。

坐标系与朝向
------------
局部平面 ``x`` 向东、``y`` 向北。跑道**直道沿南北向**，逆时针跑进：

* 东直道：从南 ``(R, -L/2)`` 到北 ``(R, +L/2)``，朝向 0°（正北）。
* 北半圆：圆心 ``(0, +L/2)``，θ 从 0 到 π，朝向 ``-θ``。
* 西直道：从北 ``(-R, +L/2)`` 到南 ``(-R, -L/2)``，朝向 180°。
* 南半圆：圆心 ``(0, -L/2)``，θ 从 π 到 2π，朝向 ``-θ``。

``heading`` 一律为**度、自北顺时针**，值域 ``[0, 360)``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..errors import LaneError, MathError

STRAIGHT_M = 84.39
INNER_RADIUS_M = 36.5
LANE_WIDTH_M = 1.22
MEASURE_OFFSET_INNER_M = 0.30
MEASURE_OFFSET_OUTER_M = 0.20

# 场地容量：8 道
MAX_LANE = 8
# 参考值（单测断言用）
REFERENCE_LAP = {1: 400.00, 2: 407.04, 8: 453.03}


def lane_radius(lane: int) -> float:
    """第 ``lane`` 道丈量线半径（米）。"""
    if not isinstance(lane, int) or isinstance(lane, bool):
        raise LaneError(f"道次必须是整数，收到 {lane!r}")
    if lane < 1 or lane > MAX_LANE:
        raise LaneError(
            f"道次 {lane} 超出范围 1..{MAX_LANE}",
            hint="标准 8 道场地请用 --lane 1..8",
        )
    if lane == 1:
        return INNER_RADIUS_M + MEASURE_OFFSET_INNER_M
    return INNER_RADIUS_M + LANE_WIDTH_M * (lane - 1) + MEASURE_OFFSET_OUTER_M


def lap_length(lane: int) -> float:
    """第 ``lane`` 道一圈长度（米）。"""
    return 2.0 * STRAIGHT_M + 2.0 * math.pi * lane_radius(lane)


def perimeter_check() -> dict[int, float]:
    """返回 1/2/8 道的圈长，供 CLI 打印与自检。"""
    return {lane: lap_length(lane) for lane in (1, 2, 8)}


@dataclass(frozen=True, slots=True)
class Fix:
    """跑道上的一个几何位置（局部平面，米）。"""

    x: float
    y: float
    heading: float  # 度，自北顺时针 [0,360)
    segment: str  # straight_east / curve_north / straight_west / curve_south
    s_in_lap: float  # 圈内弧长 [0, P)


_SEG_EAST = "straight_east"
_SEG_NORTH = "curve_north"
_SEG_WEST = "straight_west"
_SEG_SOUTH = "curve_south"


def position(s: float, radius: float) -> Fix:
    """按圈内弧长 ``s``（米）求位置与朝向。

    ``s`` 会被对一圈长度取模，因此可传任意非负实数。
    """
    if radius <= 0:
        raise MathError(f"半径必须为正，收到 {radius!r}")

    p = 2.0 * STRAIGHT_M + 2.0 * math.pi * radius
    s_in_lap = s % p
    half = STRAIGHT_M / 2.0

    if s_in_lap < STRAIGHT_M:
        # 东直道，向南→北
        return Fix(
            x=radius,
            y=-half + s_in_lap,
            heading=0.0,
            segment=_SEG_EAST,
            s_in_lap=s_in_lap,
        )

    s_in_lap -= STRAIGHT_M
    arc = math.pi * radius
    if s_in_lap < arc:
        # 北半圆：θ 0→π（逆时针）
        theta = s_in_lap / radius
        return Fix(
            x=radius * math.cos(theta),
            y=half + radius * math.sin(theta),
            heading=(-math.degrees(theta)) % 360.0,
            segment=_SEG_NORTH,
            s_in_lap=s_in_lap + STRAIGHT_M,
        )

    s_in_lap -= arc
    if s_in_lap < STRAIGHT_M:
        # 西直道，向北→南
        return Fix(
            x=-radius,
            y=half - s_in_lap,
            heading=180.0,
            segment=_SEG_WEST,
            s_in_lap=s_in_lap + STRAIGHT_M + arc,
        )

    s_in_lap -= STRAIGHT_M
    # 南半圆：θ π→2π
    theta = math.pi + s_in_lap / radius
    return Fix(
        x=radius * math.cos(theta),
        y=-half + radius * math.sin(theta),
        heading=(-math.degrees(theta)) % 360.0,
        segment=_SEG_SOUTH,
        s_in_lap=s_in_lap + 2.0 * STRAIGHT_M + arc,
    )

"""400m 跑道几何：道次半径、周长校验、按弧长求位置与朝向。"""

from __future__ import annotations

from .geometry import (
    INNER_RADIUS_M,
    LANE_WIDTH_M,
    MEASURE_OFFSET_INNER_M,
    MEASURE_OFFSET_OUTER_M,
    STRAIGHT_M,
    lane_radius,
    lap_length,
    perimeter_check,
    position,
)

__all__ = [
    "INNER_RADIUS_M",
    "LANE_WIDTH_M",
    "MEASURE_OFFSET_INNER_M",
    "MEASURE_OFFSET_OUTER_M",
    "STRAIGHT_M",
    "lane_radius",
    "lap_length",
    "perimeter_check",
    "position",
]

"""配速与时间轴。"""

from __future__ import annotations

from .schedule import (
    DEFAULT_DISTANCE_M,
    DEFAULT_DT,
    DEFAULT_LANE,
    DEFAULT_PACE_SEC_PER_KM,
    Plan,
    TimedPoint,
    build_plan,
    format_pace,
    pace_to_speed,
    plan_at,
    speed_to_pace,
)

__all__ = [
    "DEFAULT_DISTANCE_M",
    "DEFAULT_DT",
    "DEFAULT_LANE",
    "DEFAULT_PACE_SEC_PER_KM",
    "Plan",
    "TimedPoint",
    "build_plan",
    "format_pace",
    "pace_to_speed",
    "plan_at",
    "speed_to_pace",
]

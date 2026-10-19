"""配速驱动：把几何采样变成带时间戳的轨迹计划。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..errors import ConfigError, PaceError
from ..geo.enu import LocalPlane
from ..track.geometry import Fix, lane_radius, lap_length, position
from ..track.sampling import Sample, sample

DEFAULT_DT = 1.0
DEFAULT_PACE_SEC_PER_KM = 190.0  # 3'10"/km
DEFAULT_DISTANCE_M = 5000.0  # 默认跑 5 km
DEFAULT_LANE = 2


def pace_to_speed(sec_per_km: float) -> float:
    """配速（秒/公里）→ 速度（m/s）。"""
    if sec_per_km <= 0:
        raise PaceError(f"配速必须为正，收到 {sec_per_km!r}")
    return 1000.0 / sec_per_km


def speed_to_pace(speed: float) -> float:
    """速度（m/s）→ 配速（秒/公里）。"""
    if speed <= 0:
        raise PaceError(f"速度必须为正，收到 {speed!r}")
    return 1000.0 / speed


def format_pace(sec_per_km: float) -> str:
    """把秒/公里格式化成 ``M'SS"/km``。"""
    total = int(round(sec_per_km))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}'{seconds:02d}\"/km"


def parse_pace(text: str) -> float:
    """解析配速文本，返回秒/公里。

    支持 ``4:00``、``4'00"``、``4'00``、``240``、``4.5``（分钟）。
    """
    s = text.strip().replace("＂", '"').replace("’", "'")
    if not s:
        raise PaceError("配速不能为空")
    try:
        if ":" in s:
            mm, ss = s.split(":", 1)
            return float(mm) * 60.0 + float(ss)
        if "'" in s:
            mm, rest = s.split("'", 1)
            return float(mm) * 60.0 + float(rest.strip('"') or 0)
        return float(s)
    except ValueError as exc:
        raise PaceError(
            f"无法解析配速 {text!r}",
            hint="用法：--pace 4:00（4 分/公里）或 --pace 240（秒/公里）",
        ) from exc


@dataclass(frozen=True, slots=True)
class TimedPoint:
    """轨迹上的一个点：几何 + 时间 + WGS-84。"""

    index: int
    t: float  # 相对起跑时刻的秒数
    s: float  # 累计弧长（米）
    lat: float
    lon: float
    x: float  # 东（米，相对操场中心）
    y: float  # 北（米，相对操场中心）
    heading: float
    segment: str  # straight_east / curve_north / straight_west / curve_south
    lap: int  # 1 起
    s_in_lap: float


@dataclass(frozen=True, slots=True)
class Plan:
    """一次完整的模拟计划。"""

    center_lat: float
    center_lon: float
    lane: int
    radius: float
    perimeter: float
    speed: float
    dt: float
    duration: float
    total_distance: float
    points: tuple[TimedPoint, ...]

    # —— 派生量 ——
    @property
    def laps_completed(self) -> float:
        return self.total_distance / self.perimeter

    @property
    def lap_time(self) -> float:
        return self.perimeter / self.speed

    @property
    def start(self) -> TimedPoint:
        return self.points[0]

    @property
    def end(self) -> TimedPoint:
        return self.points[-1]

    def mean_speed(self) -> float:
        """``(末点距离 - 首点距离) / (末点时刻 - 首点时刻)``。"""
        return (self.end.s - self.start.s) / (self.end.t - self.start.t)

    def summary_line(self) -> str:
        return (
            f"道次 {self.lane} | 圈长 {self.perimeter:.2f} m | "
            f"配速 {format_pace(speed_to_pace(self.speed))} | "
            f"时长 {self.duration:.1f} s | 距离 {self.total_distance:.1f} m | "
            f"圈数 {self.laps_completed:.3f}"
        )


def build_plan(
    *,
    lane: int = DEFAULT_LANE,
    speed: float,
    dt: float = DEFAULT_DT,
    duration: float | None = None,
    laps: float | None = None,
    distance: float | None = None,
    center_lat: float,
    center_lon: float,
    heading: float = 0.0,
) -> Plan:
    """构建完整计划。

    ``duration`` / ``laps`` / ``distance`` 必须且只能指定一个：

    * ``duration``：总时长（秒），距离 = 速度 × 时长；
    * ``laps``：圈数，时长 = 圈数 × 圈长 / 速度；
    * ``distance``：总距离（米），时长 = 距离 / 速度。

    ``heading``：起跑朝向（度，自北顺时针）。跑道整体绕中心顺时针旋转该角度，
    默认 0 = 直道沿南北向、起点在东直道南端向北跑。
    """
    specified = [v for v in (duration, laps, distance) if v is not None]
    if len(specified) != 1:
        raise ConfigError(
            "duration / laps / distance 必须且只能指定一个",
            hint="用 --distance 5km，或 --duration 950，或 --laps 12.28",
        )
    if duration is not None and duration <= 0:
        raise ConfigError(f"时长必须为正，收到 {duration!r}")
    if laps is not None and laps <= 0:
        raise ConfigError(f"圈数必须为正，收到 {laps!r}")
    if distance is not None and distance <= 0:
        raise ConfigError(f"距离必须为正，收到 {distance!r}")

    radius = lane_radius(lane)
    perimeter = lap_length(lane)

    if duration is not None:
        total_distance = speed * duration
        total_duration = duration
    elif laps is not None:
        total_distance = laps * perimeter
        total_duration = round(total_distance / speed, 9)
    else:
        assert distance is not None  # 由上面的互斥检查保证
        total_distance = distance
        total_duration = round(distance / speed, 9)

    samples = sample(radius=radius, speed=speed, dt=dt, duration_s=total_duration)
    plane = LocalPlane.from_latlon(center_lat, center_lon)

    theta = math.radians(heading % 360.0)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    points: list[TimedPoint] = []
    for smp in samples:
        # 把整条跑道绕中心顺时针旋转 heading 度（heading=0 时是恒等变换）
        x = smp.x * cos_t + smp.y * sin_t
        y = -smp.x * sin_t + smp.y * cos_t
        lat, lon = plane.to_latlon(x, y)
        points.append(
            TimedPoint(
                index=smp.index,
                t=smp.t,
                s=smp.s,
                lat=lat,
                lon=lon,
                x=x,
                y=y,
                heading=(smp.heading + heading) % 360.0,
                segment=smp.segment,
                lap=smp.lap,
                s_in_lap=smp.s_in_lap,
            )
        )

    return Plan(
        center_lat=center_lat,
        center_lon=center_lon,
        lane=lane,
        radius=radius,
        perimeter=perimeter,
        speed=speed,
        dt=dt,
        duration=total_duration,
        total_distance=total_distance,
        points=tuple(points),
    )


def plan_at(plan: Plan, s: float) -> Fix:
    """给定累计弧长，返回几何位置（不查表，直接解析）。"""
    return position(s, plan.radius)

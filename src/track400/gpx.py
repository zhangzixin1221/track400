"""GPX 1.1 生成与校验。

设计要点
--------
* ``<time>`` 用 UTC + ``Z``（GPX 规范要求 xsd:dateTime），
  与 ``pymobiledevice3`` 的 ``play`` 解析器兼容（它只读 ``lat``/``lon``/``time``）。
* 累计距离、圈号、道次、朝向、段落写入 ``<extensions>``（自定义命名空间），
  其他软件会忽略，但我们的校验脚本和排障依赖它。
* 浮点格式：经纬度 7 位（≈1 cm），距离 3 位（mm），朝向 2 位。

校验契约（见 ``validate_gpx``）
------------------------------
``points`` / ``duration`` / ``dt`` / ``distance`` / ``lane`` 五项可逐项断言，
任一项不符抛 ``GpxError``；``tools/verify_gpx.py`` 是它的命令行外壳。
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .errors import GpxError
from .pacing.schedule import Plan

GPX_NS = "http://www.topografix.com/GPX/1/1"
TRACK400_NS = "https://track400.local/gpx/1"

ET.register_namespace("", GPX_NS)
ET.register_namespace("track400", TRACK400_NS)

_TIME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})(?:\.(?P<frac>\d{1,6}))?Z$"
)


def _q(tag: str) -> str:
    return f"{{{GPX_NS}}}{tag}"


def _e(tag: str) -> str:
    return f"{{{TRACK400_NS}}}{tag}"


def format_time(dt: datetime) -> str:
    """``datetime`` → ``2026-10-19T09:00:00.000Z``。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_time(text: str) -> datetime:
    """GPX ``<time>`` → aware ``datetime``（UTC）。"""
    m = _TIME_RE.match(text.strip())
    if not m:
        raise GpxError(
            f"无法解析 GPX 时间: {text!r}",
            hint="时间必须是 UTC 且以 Z 结尾，例如 2026-10-19T09:00:00.000Z",
        )
    frac = (m.group("frac") or "0").ljust(6, "0")
    return datetime.fromisoformat(f"{m.group('date')}T{m.group('time')}.{frac}+00:00")


def write_gpx(
    plan: Plan,
    path: str | Path,
    *,
    start_time: datetime | None = None,
    name: str | None = None,
) -> Path:
    """把 ``Plan`` 写成 GPX 1.1 文件，返回路径。"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = start_time or datetime.now(timezone.utc)
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    t0 = t0.astimezone(timezone.utc)

    title = name or (
        f"track400 lane{plan.lane} {plan.speed * 3.6:.2f}km/h "
        f"{plan.total_distance:.0f}m {plan.duration:.0f}s"
    )

    root = ET.Element(_q("gpx"), {"version": "1.1", "creator": "track400"})

    meta = ET.SubElement(root, _q("metadata"))
    ET.SubElement(meta, _q("name")).text = title
    ET.SubElement(meta, _q("desc")).text = (
        f"lane={plan.lane} radius={plan.radius:.3f}m perimeter={plan.perimeter:.4f}m "
        f"speed={plan.speed:.6f}m/s dt={plan.dt}s "
        f"center={plan.center_lat:.7f},{plan.center_lon:.7f}"
    )
    ET.SubElement(meta, _q("time")).text = format_time(t0)

    trk = ET.SubElement(root, _q("trk"))
    ET.SubElement(trk, _q("name")).text = title
    ET.SubElement(trk, _q("type")).text = "running"
    seg = ET.SubElement(trk, _q("trkseg"))

    for p in plan.points:
        trkpt = ET.SubElement(
            seg,
            _q("trkpt"),
            {"lat": f"{p.lat:.7f}", "lon": f"{p.lon:.7f}"},
        )
        ET.SubElement(trkpt, _q("time")).text = format_time(
            t0 + timedelta(seconds=p.t)
        )
        ext = ET.SubElement(trkpt, _q("extensions"))
        ET.SubElement(ext, _e("distance")).text = f"{p.s:.3f}"
        ET.SubElement(ext, _e("lap")).text = str(p.lap)
        ET.SubElement(ext, _e("lane")).text = str(plan.lane)
        ET.SubElement(ext, _e("heading")).text = f"{p.heading:.2f}"
        ET.SubElement(ext, _e("segment")).text = p.segment

    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out


@dataclass(frozen=True, slots=True)
class GpxStats:
    """校验结果。"""

    points: int
    duration: float
    dt_min: float
    dt_max: float
    distance: float
    lane: int | None
    first_time: datetime
    last_time: datetime
    segments: dict[str, int] = field(default_factory=dict)


def validate_gpx(
    path: str | Path,
    *,
    expect_points: int | None = None,
    expect_duration: float | None = None,
    expect_dt: float | None = None,
    expect_distance: float | None = None,
    expect_lane: int | None = None,
    tol_duration: float = 1e-6,
    tol_distance: float = 1.0,
) -> GpxStats:
    """解析并校验 GPX，返回统计；不满足契约抛 :class:`GpxError`。"""
    p = Path(path)
    if not p.is_file():
        raise GpxError(f"文件不存在: {p}", hint="先运行 gpx 生成命令")

    try:
        root = ET.parse(p).getroot()
    except ET.ParseError as exc:  # pragma: no cover - 输入损坏时才触发
        raise GpxError(f"GPX 解析失败: {exc}") from exc

    trkpts = root.findall(f".//{_q('trkpt')}")
    if len(trkpts) < 2:
        raise GpxError(f"GPX 至少需要 2 个 trkpt，实际 {len(trkpts)}")

    lats: list[float] = []
    lons: list[float] = []
    times: list[datetime] = []
    dists: list[float] = []
    lanes: set[int] = set()
    segments: dict[str, int] = {}

    for i, pt in enumerate(trkpts):
        try:
            lats.append(float(pt.attrib["lat"]))
            lons.append(float(pt.attrib["lon"]))
        except (KeyError, ValueError) as exc:
            raise GpxError(f"第 {i} 个 trkpt 缺少合法 lat/lon: {pt.attrib}") from exc

        t_el = pt.find(_q("time"))
        if t_el is None or not t_el.text:
            raise GpxError(f"第 {i} 个 trkpt 缺少 <time>")
        times.append(parse_time(t_el.text))

        ext = pt.find(_q("extensions"))
        if ext is not None:
            d_el = ext.find(_e("distance"))
            if d_el is not None and d_el.text:
                dists.append(float(d_el.text))
            l_el = ext.find(_e("lane"))
            if l_el is not None and l_el.text:
                lanes.add(int(l_el.text))
            s_el = ext.find(_e("segment"))
            if s_el is not None and s_el.text:
                segments[s_el.text] = segments.get(s_el.text, 0) + 1

    for a, b in zip(times, times[1:]):
        if b <= a:
            raise GpxError(
                f"时间戳非严格递增: {format_time(a)} -> {format_time(b)}",
                hint="GPX 必须按时间正序，play 会按 <time> 差值 sleep",
            )

    dt_values = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    duration = (times[-1] - times[0]).total_seconds()

    if dists:
        for a, b in zip(dists, dists[1:]):
            if b < a:
                raise GpxError(f"累计距离回退: {a} -> {b}")
        distance = dists[-1] - dists[0]
    else:
        distance = sum(
            _haversine(lats[i], lons[i], lats[i + 1], lons[i + 1])
            for i in range(len(lats) - 1)
        )

    if expect_points is not None and len(trkpts) != expect_points:
        raise GpxError(f"点数不符: 期望 {expect_points}，实际 {len(trkpts)}")
    if expect_duration is not None and abs(duration - expect_duration) > tol_duration:
        raise GpxError(f"总时长不符: 期望 {expect_duration} s，实际 {duration} s")
    if expect_dt is not None:
        for i, d in enumerate(dt_values):
            if abs(d - expect_dt) > 1e-6:
                raise GpxError(
                    f"第 {i} 段 Δt 不符: 期望 {expect_dt} s，实际 {d} s",
                    hint="末段可能短于 Δt（总时长不是 Δt 整数倍时属正常，需显式放行）",
                )
    if expect_distance is not None and abs(distance - expect_distance) > tol_distance:
        raise GpxError(f"总距离不符: 期望 {expect_distance} m，实际 {distance} m")
    if expect_lane is not None and lanes and lanes != {expect_lane}:
        raise GpxError(f"道次不符: 期望 {expect_lane}，实际 {sorted(lanes)}")

    return GpxStats(
        points=len(trkpts),
        duration=duration,
        dt_min=min(dt_values),
        dt_max=max(dt_values),
        distance=distance,
        lane=(next(iter(lanes)) if len(lanes) == 1 else None),
        first_time=times[0],
        last_time=times[-1],
        segments=segments,
    )


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

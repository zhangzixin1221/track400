"""GPX 层单测：字段完整性、总时长/点数/Δt/距离契约、损坏检测、第三方兼容性。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from track400.errors import GpxError
from track400.gpx import (
    GPX_NS,
    TRACK400_NS,
    format_time,
    parse_time,
    validate_gpx,
    write_gpx,
)
from track400.pacing.schedule import build_plan, pace_to_speed

START = datetime(2026, 10, 19, 9, 0, 0, tzinfo=timezone.utc)
CENTER = (34.0382408, 108.7644990)
NS = {"g": GPX_NS, "t": TRACK400_NS}


@pytest.fixture(scope="module")
def plan():
    return build_plan(
        lane=2,
        speed=pace_to_speed(240.0),
        dt=1.0,
        duration=660.0,
        center_lat=CENTER[0],
        center_lon=CENTER[1],
    )


@pytest.fixture(scope="module")
def gpx_path(plan, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("gpx") / "route.gpx"
    write_gpx(plan, path, start_time=START)
    return path


def test_time_format_round_trip() -> None:
    assert format_time(START) == "2026-10-19T09:00:00.000Z"
    assert parse_time("2026-10-19T09:00:00.000Z") == START
    with pytest.raises(GpxError, match="无法解析"):
        parse_time("2026-10-19T17:00:00+08:00")


def test_validate_contract(gpx_path: Path) -> None:
    stats = validate_gpx(
        gpx_path,
        expect_points=661,
        expect_duration=660.0,
        expect_dt=1.0,
        expect_distance=2750.0,
        expect_lane=2,
    )
    assert stats.points == 661
    assert stats.duration == pytest.approx(660.0, abs=1e-6)
    assert stats.dt_min == pytest.approx(1.0, abs=1e-6)
    assert stats.dt_max == pytest.approx(1.0, abs=1e-6)
    assert stats.distance == pytest.approx(2750.0, abs=1e-3)
    assert stats.lane == 2
    assert stats.last_time == START + timedelta(seconds=660)


def test_all_four_segments_present(gpx_path: Path) -> None:
    stats = validate_gpx(gpx_path)
    assert set(stats.segments) == {
        "straight_east",
        "curve_north",
        "straight_west",
        "curve_south",
    }


def test_file_structure(gpx_path: Path) -> None:
    text = gpx_path.read_text(encoding="utf-8")
    assert text.startswith("<?xml version=")
    assert 'version="1.1"' in text
    assert "<trkpt lat=" in text
    assert "<time>2026-10-19T09:00:00.000Z</time>" in text

    root = ET.parse(gpx_path).getroot()
    pts = root.findall(".//g:trkpt", NS)
    assert len(pts) == 661
    assert pts[0].attrib["lat"] == "34.0378604"
    assert pts[0].attrib["lon"] == "108.7649096"
    dist = pts[-1].find("g:extensions/t:distance", NS)
    assert dist is not None and dist.text == "2750.000"


def test_custom_namespace_present(gpx_path: Path) -> None:
    text = gpx_path.read_text(encoding="utf-8")
    assert "https://track400.local/gpx/1" in text


def test_validate_detects_backwards_time(gpx_path: Path, tmp_path: Path) -> None:
    root = ET.parse(gpx_path).getroot()
    pts = root.findall(".//g:trkpt", NS)
    second = pts[1].find("g:time", NS)
    assert second is not None
    second.text = "2026-10-19T08:59:59.000Z"  # 早于首点
    broken = tmp_path / "broken_time.gpx"
    ET.ElementTree(root).write(broken, encoding="utf-8", xml_declaration=True)

    with pytest.raises(GpxError, match="严格递增"):
        validate_gpx(broken)


def test_validate_detects_wrong_point_count(gpx_path: Path) -> None:
    with pytest.raises(GpxError, match="点数不符"):
        validate_gpx(gpx_path, expect_points=660)


def test_validate_detects_wrong_dt(gpx_path: Path) -> None:
    with pytest.raises(GpxError, match="Δt 不符"):
        validate_gpx(gpx_path, expect_dt=0.5)


def test_validate_missing_file(tmp_path: Path) -> None:
    with pytest.raises(GpxError, match="文件不存在"):
        validate_gpx(tmp_path / "nope.gpx")


def test_pymobiledevice3_parser_compatibility(gpx_path: Path) -> None:
    """真机注入层最终由 pymobiledevice3 解析 GPX，这里直接用它自己的解析器交叉验证。"""
    mod = pytest.importorskip(
        "pymobiledevice3.services.dvt.instruments.location_simulation_base"
    )
    pts = list(mod.iter_gpx_track_points(str(gpx_path)))
    assert len(pts) == 661
    assert pts[0].latitude == pytest.approx(34.0378604)
    assert pts[0].longitude == pytest.approx(108.7649096)
    assert pts[0].time is not None
    assert pts[1].time - pts[0].time == timedelta(seconds=1)
    assert pts[-1].time - pts[0].time == timedelta(seconds=660)

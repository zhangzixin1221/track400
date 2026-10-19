"""CLI 单测：参数解析、中心点优先级、干跑端到端、GPX 旁路输出。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from track400 import cli
from track400.errors import ConfigError
from track400.pacing.schedule import build_plan, pace_to_speed

CENTER = (34.0382408, 108.7644990)


def _ns(extra: list[str] | None = None):
    return cli.build_parser().parse_args(extra or [])


def test_defaults() -> None:
    ns = _ns([])
    assert ns.lane == 2
    assert ns.pace == "3:10"
    assert ns.dt == 1.0
    assert ns.heading == 0.0
    assert ns.fake is False
    assert ns.duration is None and ns.laps is None and ns.distance is None


def test_default_target_is_5km() -> None:
    assert cli.resolve_target(_ns([])) == {"distance": 5000.0}


def test_resolve_target_distance() -> None:
    assert cli.resolve_target(_ns(["--distance", "5km"])) == {"distance": 5000.0}
    assert cli.resolve_target(_ns(["--distance", "500m"])) == {"distance": 500.0}
    assert cli.resolve_target(_ns(["--distance", "5000"])) == {"distance": 5000.0}
    assert cli.resolve_target(_ns(["--distance", "5.0"])) == {"distance": 5.0}


def test_resolve_target_laps_and_duration() -> None:
    assert cli.resolve_target(_ns(["--laps", "7"])) == {"laps": 7.0}
    assert cli.resolve_target(_ns(["--duration", "600"])) == {"duration": 600.0}


def test_parse_distance_bad() -> None:
    with pytest.raises(ConfigError, match="无法解析距离"):
        cli._parse_distance("abc")


def test_center_default() -> None:
    assert cli.resolve_center(_ns([])) == CENTER


def test_center_override_latlon() -> None:
    ns = _ns(["--lat", "34.1", "--lon", "108.9"])
    assert cli.resolve_center(ns) == (34.1, 108.9)


def test_center_from_bd09() -> None:
    ns = _ns(["--bd09", "34.04244774,108.77577825"])
    lat, lon = cli.resolve_center(ns)
    assert lat == pytest.approx(34.0382408, abs=2e-6)
    assert lon == pytest.approx(108.7644990, abs=2e-6)


def test_lat_without_lon_rejected() -> None:
    with pytest.raises(ConfigError, match="必须同时"):
        cli.resolve_center(_ns(["--lat", "34.0"]))


def test_bd09_conflicts_with_latlon() -> None:
    with pytest.raises(ConfigError, match="不能同时"):
        cli.resolve_center(_ns(["--bd09", "34.0,108.0", "--lat", "34.0"]))


def test_bad_bd09_rejected() -> None:
    with pytest.raises(ConfigError):
        cli.resolve_center(_ns(["--bd09", "34.0"]))


def test_duration_and_laps_conflict() -> None:
    with pytest.raises(SystemExit) as ei:
        _ns(["--duration", "60", "--laps", "2"])
    assert ei.value.code == 2


def test_speedup_requires_fake(tmp_path: Path) -> None:
    ns = _ns(["--speedup", "10", "--duration", "5", "--lat", "34.0", "--lon", "108.0"])
    with pytest.raises(ConfigError, match="只允许"):
        cli.run(ns)


def test_heading_rotation() -> None:
    plan = build_plan(
        lane=2,
        speed=pace_to_speed(240.0),
        dt=1.0,
        duration=5.0,
        center_lat=CENTER[0],
        center_lon=CENTER[1],
        heading=90.0,
    )
    # 起点 (37.92, -42.195) 绕中心顺时针转 90° → (-42.195, -37.92)
    assert plan.start.x == pytest.approx(-42.195, abs=1e-9)
    assert plan.start.y == pytest.approx(-37.92, abs=1e-9)
    assert plan.start.heading == pytest.approx(90.0, abs=1e-9)


def test_end_to_end_fake(tmp_path: Path) -> None:
    out = tmp_path / "run.jsonl"
    rc = cli.main(
        [
            "--fake",
            "--speedup",
            "200",
            "--duration",
            "5",
            "--pace",
            "6:00",
            "--out",
            str(out),
            "--lat",
            str(CENTER[0]),
            "--lon",
            str(CENTER[1]),
        ]
    )
    assert rc == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    sets = [r for r in rows if r.get("type") == "set"]
    assert len(sets) == 6
    assert any(r.get("type") == "clear" for r in rows)
    assert sets[-1]["t"] == pytest.approx(5.0)


def test_gpx_output(tmp_path: Path) -> None:
    gpx = tmp_path / "route.gpx"
    rc = cli.main(
        [
            "--fake",
            "--speedup",
            "200",
            "--duration",
            "3",
            "--gpx-out",
            str(gpx),
            "--out",
            str(tmp_path / "g.jsonl"),
        ]
    )
    assert rc == 0
    assert gpx.is_file()
    text = gpx.read_text(encoding="utf-8")
    assert "<trkpt lat=" in text
    assert text.count("<trkpt") == 4

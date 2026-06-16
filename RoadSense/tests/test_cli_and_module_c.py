"""Tests for CLI-style paths and imagery branches."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString

import src.module_c as module_c
from src.module_c import clip_score_image, fetch_mapillary_tags_for_segment, main as module_c_main, run as module_c_run
from src.scoring import load_config, run as scoring_run
from src.visualise import main as visualise_main
from src.utils import main as utils_main


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _write_scored_segments(tmp_path: Path) -> Path:
    gdf = gpd.GeoDataFrame(
        {
            "segment_id": ["SEG-001", "SEG-002"],
            "A_score": [0.8, 0.2],
            "B_score": [0.9, 0.4],
            "C_score": [0.7, 0.3],
            "posted_limit": [60, 30],
            "v85": [78, 28],
            "safe_system_ref": [50, 30],
            "near_attractor": [1, 0],
            "attractor_count": [3, 0],
            "infrastructure_gap": [0.7, 0.4],
            "rank": [1, 2],
            "risk_tier": ["Critical", "Low"],
            "popup_text": ["critical segment", "low segment"],
        },
        geometry=[
            LineString([(121.0, 14.5), (121.01, 14.5)]),
            LineString([(121.01, 14.5), (121.02, 14.5)]),
        ],
        crs="EPSG:4326",
    )
    scored_path = tmp_path / "segments.gpkg"
    gdf.to_file(scored_path, layer="segments", driver="GPKG")
    return scored_path


def test_fetch_mapillary_tags_and_score_dataframe_api(monkeypatch) -> None:
    monkeypatch.setattr(module_c, "API_TOKEN", "token")
    monkeypatch.setattr(module_c.requests, "get", lambda *args, **kwargs: _Response({"data": [{"detections": {"data": [{"value": "object--street-light"}, {"value": "object--sign--speed-limit-80"}]}}]}))

    tags = fetch_mapillary_tags_for_segment(14.5, 121.0)
    assert tags["object--street-light"] == 1
    assert tags["object--sign--speed-limit-80"] == 1

    gdf = gpd.GeoDataFrame(
        {"segment_id": ["SEG-001"], "A_score": [0.1], "B_score": [0.2], "C_score": [0.3]},
        geometry=[LineString([(121.0, 14.5), (121.01, 14.5)])],
        crs="EPSG:4326",
    )
    scored = module_c.score_dataframe(gdf, use_api=True)
    assert bool(scored["imagery_coverage"].iloc[0]) is True
    assert scored["C_score"].iloc[0] >= 0.3

    assert clip_score_image("/tmp/nonexistent_image.jpg") == 0.5


def test_module_c_run_and_main(tmp_path: Path, monkeypatch) -> None:
    input_path = _write_scored_segments(tmp_path)
    output_path = tmp_path / "out.gpkg"
    mapillary_json = tmp_path / "detections.json"
    mapillary_json.write_text(json.dumps({"SEG-001": {"object--street-light": 1}}), encoding="utf-8")

    scored = module_c_run(str(input_path), str(output_path), str(mapillary_json), use_api=False)
    assert output_path.exists()
    assert scored["C_score"].notna().all()

    monkeypatch.setattr(sys, "argv", ["module_c.py", "--input-path", str(input_path), "--output-path", str(output_path), "--mapillary-json", str(mapillary_json)])
    assert module_c_main() == 0


def test_load_config_and_scoring_run(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("sss:\n  module_a: 0.4\n  module_b: 0.4\n  module_c: 0.2\nrisk_tiers:\n  critical: 0.75\n  high: 0.5\n  medium: 0.25\n  low: 0.0\n", encoding="utf-8")
    config = load_config(config_path)
    assert config["sss"]["module_a"] == 0.4

    scored_path = _write_scored_segments(tmp_path)
    output_path = tmp_path / "scored_out.gpkg"
    geojson_path = tmp_path / "scored_out.geojson"
    top100_path = tmp_path / "top100.geojson"
    result = scoring_run(str(scored_path), str(config_path), str(output_path), str(geojson_path), str(top100_path))
    assert result["SSS"].notna().all()
    assert output_path.exists()
    assert geojson_path.exists()
    assert top100_path.exists()


def test_visualise_and_utils_cli(monkeypatch, tmp_path: Path) -> None:
    scored_path = _write_scored_segments(tmp_path)
    map_path = tmp_path / "map.html"
    monkeypatch.setattr(sys, "argv", ["visualise.py", "--input-path", str(scored_path), "--output-html", str(map_path)])
    assert visualise_main() == 0
    assert map_path.exists()

    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    monkeypatch.setattr(sys, "argv", ["utils.py", "--data-root", str(raw_root)])
    assert utils_main() == 0
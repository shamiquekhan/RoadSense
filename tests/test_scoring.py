"""Tests for the composite scoring engine."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.evaluation import run_evaluation
from src.scoring import build_popup_text, classify_tier, compute_sss, export_outputs, tier_colour

from src.utils import audit_datasets

from src.visualise import build_priority_map


def test_classify_tier_boundaries() -> None:
    assert classify_tier(0.85, {"critical": 0.75, "high": 0.5, "medium": 0.25, "low": 0.0}) == "Critical"
    assert classify_tier(0.50, {"critical": 0.75, "high": 0.5, "medium": 0.25, "low": 0.0}) == "High"
    assert classify_tier(0.25, {"critical": 0.75, "high": 0.5, "medium": 0.25, "low": 0.0}) == "Medium"
    assert classify_tier(0.10, {"critical": 0.75, "high": 0.5, "medium": 0.25, "low": 0.0}) == "Low"


def test_tier_colour_returns_hex() -> None:
    for tier in ["Critical", "High", "Medium", "Low"]:
        colour = tier_colour(tier)
        assert colour.startswith("#") and len(colour) == 7


def test_compute_sss_adds_outputs(sample_segments) -> None:
    scored = compute_sss(sample_segments, config={"sss": {"module_a": 0.4, "module_b": 0.4, "module_c": 0.2}, "risk_tiers": {"critical": 0.75, "high": 0.5, "medium": 0.25, "low": 0.0}})
    for column in ["SSS", "risk_tier", "risk_colour", "popup_text", "rank"]:
        assert column in scored.columns
    assert scored["SSS"].between(0, 1).all()


def test_popup_text_includes_tier(sample_segments) -> None:
    sample_segments["SSS"] = 0.82
    sample_segments["risk_tier"] = "Critical"
    row = sample_segments.iloc[0]
    text = build_popup_text(row)
    assert "Critical" in text


def test_export_and_visualise_outputs(tmp_path: Path, sample_segments) -> None:
    scored = compute_sss(sample_segments, config={"sss": {"module_a": 0.4, "module_b": 0.4, "module_c": 0.2}, "risk_tiers": {"critical": 0.75, "high": 0.5, "medium": 0.25, "low": 0.0}})
    gpkg_path = tmp_path / "scored.gpkg"
    geojson_path = tmp_path / "scored.geojson"
    top100_path = tmp_path / "top100.geojson"
    export_outputs(scored, gpkg_path, geojson_path, top100_path)
    assert gpkg_path.exists()
    assert geojson_path.exists()
    assert top100_path.exists()

    map_path = tmp_path / "map.html"
    build_priority_map(gpkg_path, map_path)
    assert map_path.exists()


def test_run_evaluation_returns_path(tmp_path: Path, sample_segments) -> None:
    scored = compute_sss(sample_segments, config={"sss": {"module_a": 0.4, "module_b": 0.4, "module_c": 0.2}, "risk_tiers": {"critical": 0.75, "high": 0.5, "medium": 0.25, "low": 0.0}})
    scored_path = tmp_path / "scored.gpkg"
    scored.to_file(scored_path, layer="segments", driver="GPKG")

    path = run_evaluation(tmp_path / "evaluation_results.md", input_path=scored_path)
    assert path == tmp_path / "evaluation_results.md"
    assert path.exists()


def test_audit_datasets_reads_raw_files(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "gps_probe").mkdir(parents=True)
    (raw_root / "road_network").mkdir(parents=True)

    pd.DataFrame({"segment_id": ["SEG-1"], "operating_speed": [50], "traffic_intensity": [100], "posted_speed_limit": [60]}).to_csv(raw_root / "gps_probe" / "probe.csv", index=False)
    gpd.GeoDataFrame(
        {"segment_id": ["SEG-1"]},
        geometry=gpd.points_from_xy([121.0], [14.5]),
        crs="EPSG:4326",
    ).to_file(raw_root / "road_network" / "network.gpkg", layer="segments", driver="GPKG")

    report = audit_datasets(raw_root)
    assert "gps_probe" in report
    assert "road_network" in report

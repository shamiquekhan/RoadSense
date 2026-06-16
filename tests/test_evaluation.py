"""Tests for the evaluation and validation workflow."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

from src.evaluation import benchmark_validation, correlation_matrix, morans_i, run, run_evaluation, sensitivity_analysis


def _make_scored_segments(tmp_path: Path) -> Path:
    gdf = gpd.GeoDataFrame(
        {
            "segment_id": ["SEG-001", "SEG-002", "SEG-003", "SEG-004"],
            "A_score": [0.9, 0.7, 0.2, 0.1],
            "B_score": [0.8, 0.6, 0.3, 0.2],
            "C_score": [0.7, 0.5, 0.4, 0.1],
            "SSS": [0.82, 0.64, 0.28, 0.12],
            "risk_tier": ["Critical", "High", "Medium", "Low"],
        },
        geometry=[
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
            Polygon([(0, 1), (1, 1), (1, 2), (0, 2)]),
            Polygon([(1, 1), (2, 1), (2, 2), (1, 2)]),
        ],
        crs="EPSG:4326",
    )
    scored_path = tmp_path / "all_segments_scored.gpkg"
    gdf.to_file(scored_path, layer="segments", driver="GPKG")
    return scored_path


def test_morans_i_and_correlation_matrix(tmp_path: Path) -> None:
    scored_path = _make_scored_segments(tmp_path)
    gdf = gpd.read_file(scored_path, layer="segments")

    mi = morans_i(gdf)
    assert "interpretation" in mi or "error" in mi

    corr = correlation_matrix(gdf)
    assert not corr.empty
    assert "SSS" in corr.columns


def test_sensitivity_and_benchmark_and_run(tmp_path: Path) -> None:
    scored_path = _make_scored_segments(tmp_path)
    gdf = gpd.read_file(scored_path, layer="segments")

    sensitivity = sensitivity_analysis(gdf, top_n=3)
    assert "mean_stability" in sensitivity
    assert 0.0 <= sensitivity["mean_stability"] <= 1.0

    benchmark_file = tmp_path / "benchmark_segments.json"
    benchmark_file.write_text(json.dumps([
        {"segment_id": "SEG-001", "known_risk": "critical"},
        {"segment_id": "SEG-004", "known_risk": "low"},
    ]), encoding="utf-8")
    benchmark = benchmark_validation(gdf, benchmark_file)
    assert "accuracy" in benchmark
    assert benchmark["n_segments"] == 2

    report_path = tmp_path / "evaluation_results.md"
    results = run(input_path=scored_path, output_path=report_path, benchmark_file=benchmark_file)
    assert "morans_i" in results
    assert report_path.exists()

    wrapper_path = run_evaluation(results_path=report_path, input_path=scored_path, benchmark_file=benchmark_file)
    assert wrapper_path == report_path
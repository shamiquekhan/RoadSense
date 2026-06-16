"""Evaluation and validation framework for RoadSense."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from loguru import logger

try:
    from esda.moran import Moran
    from libpysal.weights import Queen

    SPATIAL_STATS_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency path
    Moran = None  # type: ignore[assignment]
    Queen = None  # type: ignore[assignment]
    SPATIAL_STATS_AVAILABLE = False
    logger.warning("esda/libpysal not installed - Moran's I will be skipped")

DEFAULT_INPUT = Path("outputs/geojson/all_segments_scored.gpkg")
DEFAULT_REPORT = Path("docs/evaluation_results.md")
DEFAULT_CONFIG = Path("config/scoring_weights.yaml")
DEFAULT_BENCHMARK = Path("data/raw/benchmark_segments.json")


def _read_scored_segments(input_path: str | Path) -> gpd.GeoDataFrame:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Scored segment file not found: {path}")

    try:
        return gpd.read_file(path, layer="segments")
    except Exception:
        return gpd.read_file(path)


def _load_config(config_path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def morans_i(gdf: gpd.GeoDataFrame, col: str = "SSS") -> dict[str, Any]:
    """Compute Moran's I spatial autocorrelation statistic."""

    if not SPATIAL_STATS_AVAILABLE:
        return {"error": "esda/libpysal not installed"}
    if col not in gdf.columns or len(gdf) < 3:
        return {"error": f"insufficient data for Moran's I on {col}"}

    try:
        gdf_projected = gdf.to_crs(gdf.estimate_utm_crs())
        weights = Queen.from_dataframe(gdf_projected, use_index=False, silence_warnings=True)
        weights.transform = "r"
        stat = Moran(gdf_projected[col].fillna(0), weights)
        interpretation = (
            "Strong positive spatial clustering - high-risk segments cluster geographically."
            if stat.I > 0.1 and stat.p_sim < 0.05
            else "Weak or non-significant spatial clustering."
        )
        return {
            "I": round(float(stat.I), 4),
            "p_value": round(float(stat.p_sim), 4),
            "z_score": round(float(stat.z_sim), 4),
            "n_segments": int(len(gdf_projected)),
            "interpretation": interpretation,
        }
    except Exception as exc:  # pragma: no cover - geometry-dependent branch
        return {"error": str(exc)}


def correlation_matrix(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Spearman correlation between module scores."""

    cols = [column for column in ["A_score", "B_score", "C_score", "SSS"] if column in gdf.columns]
    if len(cols) < 2:
        return pd.DataFrame()
    return gdf[cols].corr(method="spearman").round(3)


def sensitivity_analysis(
    gdf: gpd.GeoDataFrame,
    perturbation: float = 0.20,
    top_n: int = 100,
    config_path: str | Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Measure how much the top-ranked segments shift under weight perturbation."""

    config = _load_config(config_path)
    base_weights = config.get("sss", config.get("weights", {"w_A": 0.4, "w_B": 0.4, "w_C": 0.2}))
    weights = {
        "module_a": float(base_weights.get("module_a", base_weights.get("w_A", 0.4))),
        "module_b": float(base_weights.get("module_b", base_weights.get("w_B", 0.4))),
        "module_c": float(base_weights.get("module_c", base_weights.get("w_C", 0.2))),
    }

    if "segment_id" not in gdf.columns or not {"A_score", "B_score", "C_score"}.issubset(gdf.columns):
        return {"error": "missing required columns for sensitivity analysis"}

    segment_total = min(top_n, len(gdf))
    if segment_total == 0:
        return {"error": "empty dataset"}

    base_scores = (
        weights["module_a"] * gdf["A_score"]
        + weights["module_b"] * gdf["B_score"]
        + weights["module_c"] * gdf["C_score"]
    )
    base_top = set(gdf.assign(_score=base_scores).nlargest(segment_total, "_score")["segment_id"])

    stability_rows: list[dict[str, Any]] = []
    for module_name in ["module_a", "module_b", "module_c"]:
        for direction in [1 + perturbation, 1 - perturbation]:
            perturbed = weights.copy()
            perturbed[module_name] *= direction
            total = sum(perturbed.values())
            perturbed = {name: value / total for name, value in perturbed.items()}
            perturbed_scores = (
                perturbed["module_a"] * gdf["A_score"]
                + perturbed["module_b"] * gdf["B_score"]
                + perturbed["module_c"] * gdf["C_score"]
            )
            top_segments = set(gdf.assign(_score=perturbed_scores).nlargest(segment_total, "_score")["segment_id"])
            overlap = len(base_top & top_segments) / segment_total
            stability_rows.append({"perturbation": f"{module_name} x{direction:.2f}", "top_n_stability": round(overlap, 3)})

    mean_stability = float(np.mean([row["top_n_stability"] for row in stability_rows]))
    return {"results": stability_rows, "mean_stability": round(mean_stability, 3)}


def benchmark_validation(
    gdf: gpd.GeoDataFrame,
    benchmark_file: str | Path = DEFAULT_BENCHMARK,
) -> dict[str, Any]:
    """Validate SSS against known high-risk segments from public sources."""

    path = Path(benchmark_file)
    if not path.exists():
        return {"error": "Benchmark file not found"}

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid benchmark JSON: {exc}"}

    benchmarks = loaded.get("segments", loaded) if isinstance(loaded, dict) else loaded
    if not isinstance(benchmarks, list):
        return {"error": "Benchmark file must contain a list of segment records"}

    results: list[dict[str, Any]] = []
    for benchmark in benchmarks:
        segment_id = benchmark.get("segment_id")
        if not segment_id or "segment_id" not in gdf.columns:
            continue
        match = gdf[gdf["segment_id"] == segment_id]
        if match.empty:
            continue
        row = match.iloc[0]
        known_risk = str(benchmark.get("known_risk", "")).lower()
        predicted_high = str(row.get("risk_tier", "")).lower() in {"high", "critical"}
        expected_high = known_risk in {"high", "critical"}
        results.append(
            {
                "segment_id": segment_id,
                "known_risk": known_risk,
                "SSS": round(float(row.get("SSS", 0.0)), 3),
                "predicted_tier": row.get("risk_tier", ""),
                "correct": expected_high == predicted_high,
            }
        )

    if not results:
        return {"error": "No matching benchmark segments found in dataset"}

    accuracy = sum(1 for result in results if result["correct"]) / len(results)
    return {"accuracy": round(float(accuracy), 3), "n_segments": len(results), "details": results}


def _write_evaluation_report(results: dict[str, Any], path: Path) -> None:
    mi = results.get("morans_i", {})
    corr = results.get("correlation_matrix", {})
    sens = results.get("sensitivity", {})
    bench = results.get("benchmark", {})

    lines = [
        "# RoadSense - Evaluation Results\n\n",
        "## 1. Spatial Autocorrelation (Moran's I)\n",
        f"- I = {mi.get('I', 'N/A')}, p = {mi.get('p_value', 'N/A')}\n",
        f"- {mi.get('interpretation', mi.get('error', 'Not run'))}\n\n",
        "## 2. Module Score Correlations (Spearman)\n",
    ]
    if corr:
        lines.append("```text\n")
        lines.append(pd.DataFrame(corr).to_string())
        lines.append("\n```\n\n")
    else:
        lines.append("- Not enough data to compute correlations.\n\n")

    lines.extend(
        [
            "## 3. Sensitivity Analysis\n",
            f"- Mean top-100 stability: {sens.get('mean_stability', 'N/A')}\n\n",
            "## 4. Benchmark Validation\n",
        ]
    )
    if "accuracy" in bench:
        lines.append(f"- Accuracy: {bench['accuracy']:.1%} (n={bench['n_segments']})\n")
    else:
        lines.append(f"- {bench.get('error', 'Not run')}\n")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


def run(
    input_path: str | Path = DEFAULT_INPUT,
    output_path: str | Path = DEFAULT_REPORT,
    benchmark_file: str | Path = DEFAULT_BENCHMARK,
) -> dict[str, Any]:
    """Run the full evaluation workflow and write a markdown report."""

    logger.info("Evaluation and Validation Framework")
    gdf = _read_scored_segments(input_path)
    results = {
        "morans_i": morans_i(gdf),
        "correlation_matrix": correlation_matrix(gdf).to_dict(),
        "sensitivity": sensitivity_analysis(gdf),
        "benchmark": benchmark_validation(gdf, benchmark_file),
    }
    _write_evaluation_report(results, Path(output_path))
    logger.success(f"Evaluation report saved to {output_path}")
    return results


def run_evaluation(
    results_path: str | Path = DEFAULT_REPORT,
    input_path: str | Path = DEFAULT_INPUT,
    benchmark_file: str | Path = DEFAULT_BENCHMARK,
) -> Path:
    """Backward-compatible wrapper used by the notebooks and CLI."""

    run(input_path=input_path, output_path=results_path, benchmark_file=benchmark_file)
    return Path(results_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RoadSense evaluation checks.")
    parser.add_argument("--input-path", default=str(DEFAULT_INPUT))
    parser.add_argument("--output-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--benchmark-file", default=str(DEFAULT_BENCHMARK))
    args = parser.parse_args()

    run(input_path=args.input_path, output_path=args.output_path, benchmark_file=args.benchmark_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

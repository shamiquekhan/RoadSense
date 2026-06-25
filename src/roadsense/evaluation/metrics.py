"""Evaluation metrics and validation framework for RoadSense scoring.

Includes:
  - Module score correlation analysis
  - Sensitivity analysis on score weights
  - Benchmark validation against known high-risk segments
  - Spatial autocorrelation (Moran's I) — optional
"""

from __future__ import annotations

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

    SPATIAL_AVAILABLE = True
except ImportError:
    Moran = None  # type: ignore[assignment]
    Queen = None  # type: ignore[assignment]
    SPATIAL_AVAILABLE = False
    logger.warning("esda/libpysal not installed — Moran's I will be skipped")


def correlation_matrix(gdf: pd.DataFrame) -> pd.DataFrame:
    """Spearman rank correlation between module scores (A, B, C, SSS)."""
    cols = [c for c in ["A_score", "B_score", "C_score", "SSS"] if c in gdf.columns]
    if len(cols) < 2:
        return pd.DataFrame()
    return gdf[cols].corr(method="spearman").round(3)


def sensitivity_analysis(
    gdf: pd.DataFrame,
    perturbation: float = 0.20,
    top_n: int = 100,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Measure top-N stability when module weights are perturbed."""
    if not {"A_score", "B_score", "C_score", "segment_id"}.issubset(gdf.columns):
        return {"error": "missing required columns"}
    n = min(top_n, len(gdf))
    if n == 0:
        return {"error": "empty dataset"}

    config: dict = {}
    if config_path and Path(config_path).exists():
        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    sss_weights = config.get(
        "sss", {"module_a": 0.35, "module_b": 0.35, "module_c": 0.30}
    )
    weights = {k: float(sss_weights[k]) for k in ["module_a", "module_b", "module_c"]}

    base = (
        weights["module_a"] * gdf["A_score"]
        + weights["module_b"] * gdf["B_score"]
        + weights["module_c"] * gdf["C_score"]
    )
    base_top = set(gdf.assign(_s=base).nlargest(n, "_s")["segment_id"])
    results = []
    for mod in ["module_a", "module_b", "module_c"]:
        for direction in [1 + perturbation, 1 - perturbation]:
            perturbed = dict(weights)
            perturbed[mod] *= direction
            total = sum(perturbed.values())
            perturbed = {k: v / total for k, v in perturbed.items()}
            scores = (
                perturbed["module_a"] * gdf["A_score"]
                + perturbed["module_b"] * gdf["B_score"]
                + perturbed["module_c"] * gdf["C_score"]
            )
            top = set(gdf.assign(_s=scores).nlargest(n, "_s")["segment_id"])
            overlap = len(base_top & top) / n
            results.append(
                {
                    "perturbation": f"{mod} x{direction:.2f}",
                    "top_n_stability": round(overlap, 3),
                }
            )

    mean_stab = float(np.mean([r["top_n_stability"] for r in results]))
    return {"results": results, "mean_stability": round(mean_stab, 3)}


def morans_i(gdf: gpd.GeoDataFrame, col: str = "SSS") -> dict[str, Any]:
    """Compute Moran's I for spatial autocorrelation."""
    if not SPATIAL_AVAILABLE:
        return {"error": "esda/libpysal not installed"}
    if col not in gdf.columns or len(gdf) < 3:
        return {"error": f"insufficient data for Moran's I on {col}"}
    try:
        proj = gdf.to_crs(gdf.estimate_utm_crs())
        w = Queen.from_dataframe(proj, use_index=False, silence_warnings=True)
        w.transform = "r"
        stat = Moran(proj[col].fillna(0), w)
        interpretation = (
            "Strong positive spatial clustering — high-risk segments cluster geographically."
            if stat.I > 0.1 and stat.p_sim < 0.05
            else "Weak or non-significant spatial clustering."
        )
        return {
            "I": round(float(stat.I), 4),
            "p_value": round(float(stat.p_sim), 4),
            "z_score": round(float(stat.z_sim), 4),
            "n_segments": int(len(proj)),
            "interpretation": interpretation,
        }
    except Exception as exc:
        return {"error": str(exc)}


def benchmark_validation(
    gdf: pd.DataFrame,
    benchmark_file: str | Path,
    segment_id_col: str = "segment_id",
    sss_col: str = "SSS",
    tier_col: str = "risk_tier",
) -> dict[str, Any]:
    """Validate SSS against known high-risk segments from public sources."""
    path = Path(benchmark_file)
    if not path.exists():
        return {"error": "Benchmark file not found"}

    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Invalid benchmark JSON: {exc}"}

    benchmarks = data.get("segments", data) if isinstance(data, dict) else data
    if not isinstance(benchmarks, list):
        return {"error": "Benchmark must be a list of segment records"}

    if segment_id_col not in gdf.columns:
        return {"error": f"Column '{segment_id_col}' not in scored data"}

    results = []
    for bm in benchmarks:
        sid = bm.get("segment_id")
        if not sid:
            continue
        match = gdf[gdf[segment_id_col] == sid]
        if match.empty:
            continue
        row = match.iloc[0]
        known = str(bm.get("known_risk", "")).lower() in {"high", "critical"}
        predicted = str(row.get(tier_col, "")).lower() in {
            "high",
            "critical",
            "high — priority review",
            "critical — immediate review",
        }
        results.append(
            {
                "segment_id": sid,
                "known_risk": bm.get("known_risk", ""),
                sss_col: round(float(row.get(sss_col, 0)), 3),
                "predicted_tier": row.get(tier_col, ""),
                "correct": known == predicted,
            }
        )

    if not results:
        return {"error": "No matching benchmark segments found"}
    accuracy = sum(1 for r in results if r["correct"]) / len(results)
    return {
        "accuracy": round(float(accuracy), 3),
        "n_segments": len(results),
        "details": results,
    }


def full_evaluation(
    gdf: gpd.GeoDataFrame,
    benchmark_file: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run all evaluation checks and return results dict."""
    results: dict[str, Any] = {
        "correlation_matrix": correlation_matrix(gdf).to_dict(),
        "sensitivity": sensitivity_analysis(gdf, config_path=config_path),
        "morans_i": morans_i(gdf),
    }
    if benchmark_file:
        results["benchmark"] = benchmark_validation(gdf, benchmark_file)
    return results

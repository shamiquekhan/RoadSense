"""Pipeline orchestration: load → score → export → map."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from loguru import logger

from roadsense.config import (
    SCORE_WEIGHTS,
    RAW_DATA_DIR,
    PROCESSED_DATA_DIR,
    OUTPUT_DIR,
)
from roadsense.data.loader import load_and_clean, map_to_roadsense_schema
from roadsense.scoring import (
    score_dataframe_4component,
    score_dataframe_roadsense,
    classify_priority,
    compute_reliability_tier,
)
from roadsense.visualisation.map import create_interactive_map


def add_centroids(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add centroid lat/lon in WGS84."""
    if isinstance(df, gpd.GeoDataFrame) and df.crs:
        geo = df.to_crs("EPSG:3857")
        centroid = geo.geometry.centroid
        df["centroid_lat"] = centroid.y
        df["centroid_lon"] = centroid.x
    return df


def add_log_features(df: pd.DataFrame) -> pd.DataFrame:
    """Log-transform skewed traffic features."""
    if "WeightedSample" in df.columns:
        df["log_weighted_sample"] = np.log1p(df["WeightedSample"])
    if "SampleSize_avg" in df.columns:
        df["log_sample_size"] = np.log1p(df["SampleSize_avg"])
    return df


def print_kpis_4component(df: pd.DataFrame) -> None:
    """Print network KPIs for 4-component scoring output."""
    total_km = df["Shape_Length"].sum() / 1000
    print("\n── Network KPIs (4-Component) ─────────────────────────")
    for label in ["Critical — Immediate Review", "High — Priority Review",
                   "Moderate — Scheduled Review", "Low — Monitor"]:
        mask = df["priority_class"] == label
        km = df.loc[mask, "Shape_Length"].sum() / 1000
        pct = km / total_km * 100 if total_km > 0 else 0
        print(f"  {label:35s}: {km:7.0f} km  ({pct:4.1f}%)")
    print(f"\n  Mean Score: {df['speed_safety_score'].mean():.3f}")
    print(f"  Above Safe System limit: {(df['limit_gap'] > 0).mean()*100:.1f}%")
    print(f"  Traffic exceeds Safe System: {(df['operating_gap'] > 0).mean()*100:.1f}%")


def print_kpis_roadsense(df: pd.DataFrame) -> None:
    """Print network KPIs for 3-module scoring output."""
    total_km = df["length_m"].sum() / 1000 if "length_m" in df.columns else 0
    print("\n── Network KPIs (RoadSense 3-Module) ─────────────────")
    for tier in ["Critical — Immediate Review", "High — Priority Review",
                  "Moderate — Scheduled Review", "Low — Monitor"]:
        mask = df["risk_tier"] == tier
        km = df.loc[mask, "length_m"].sum() / 1000 if "length_m" in df.columns else 0
        pct = km / total_km * 100 if total_km > 0 else 0
        print(f"  {tier:35s}: {km:7.0f} km  ({pct:4.1f}%)")
    print(f"\n  Mean SSS: {df['SSS'].mean():.3f}")


def run_pipeline_4component(
    data_dir: str | Path = RAW_DATA_DIR,
    out_dir: str | Path = OUTPUT_DIR,
) -> gpd.GeoDataFrame:
    """Single-shot 4-component pipeline."""
    logger.info("── 4-Component Pipeline ───────────────────────────")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_and_clean(data_dir)
    df = score_dataframe_4component(df)

    # Reliability tier (data quality signal — not a scoring input)
    ss_col = "SampleSize_avg"
    if ss_col in df.columns:
        tier_results = df[ss_col].apply(compute_reliability_tier).tolist()
        df["reliability_tier"] = [r[0] for r in tier_results]
        df["reliability_colour"] = [r[1] for r in tier_results]

    df = add_centroids(df)
    df = add_log_features(df)
    print_kpis_4component(df)

    _export(df, out_dir, prefix="speed_safety_scores")
    return df


def run_pipeline_roadsense(
    data_dir: str | Path = RAW_DATA_DIR,
    out_dir: str | Path = OUTPUT_DIR,
) -> gpd.GeoDataFrame:
    """Single-shot 3-module RoadSense pipeline."""
    logger.info("── RoadSense 3-Module Pipeline ────────────────────")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_and_clean(data_dir)
    df = map_to_roadsense_schema(df)
    df = score_dataframe_roadsense(df)
    df = add_centroids(df)
    print_kpis_roadsense(df)

    _export(df, out_dir, prefix="roadsense_scores")
    return df


def _export(df: gpd.GeoDataFrame, out_dir: Path, prefix: str) -> None:
    """Save outputs in multiple formats."""
    cols_for_csv = [c for c in df.columns if c != "geometry"]
    csv_path = out_dir / f"{prefix}.csv"
    df[cols_for_csv].to_csv(csv_path, index=False)
    logger.info(f"  CSV: {csv_path}")

    if isinstance(df, gpd.GeoDataFrame):
        gpkg_path = out_dir / f"{prefix}.gpkg"
        df.to_file(gpkg_path, driver="GPKG")
        logger.info(f"  GPKG: {gpkg_path}")

        # Lighter GeoJSON for web
        speed_col = "SpeedLimit" if "SpeedLimit" in df.columns else "posted_limit"
        f85_col = "F85thPercentileSpeed" if "F85thPercentileSpeed" in df.columns else "v85"
        safe_col = "safe_system_limit" if "safe_system_limit" in df.columns else "safe_system_ref"

        viz_cols = [
            "geometry", "road_name", "segment_id",
            speed_col, f85_col, "PercentOverLimit",
            safe_col, "limit_gap", "operating_gap",
            "speed_safety_score", "priority_class", "score_explanation",
            "region", "vru_risk_score", "centroid_lat", "centroid_lon",
            "functional_class", "urban_rural",
            "A_score", "B_score", "C_score", "SSS", "risk_tier",
            "reliability_tier", "reliability_colour",
        ]
        viz_avail = [c for c in viz_cols if c in df.columns]
        geojson_path = out_dir / f"{prefix}.geojson"
        df[viz_avail].to_file(geojson_path, driver="GeoJSON")
        logger.info(f"  GeoJSON: {geojson_path}")

    # Map
    try:
        geojson = out_dir / f"{prefix}.geojson"
        if geojson.exists():
            map_path = out_dir / f"{prefix}_map.html"
            create_interactive_map(str(geojson), str(map_path))
    except Exception as exc:
        logger.warning(f"Map generation skipped: {exc}")

    # Generate summary KPIs
    kpi_path = out_dir / f"{prefix}_kpis.csv"
    try:
        summary = df.groupby(["region", "RoadClass", "LandUse", "priority_class"]).agg(
            section_count=("speed_safety_score", "count") if "speed_safety_score" in df.columns else ("SSS", "count"),
            total_length_km=("Shape_Length", lambda x: x.sum() / 1000) if "Shape_Length" in df.columns else ("length_m", lambda x: x.sum() / 1000),
            mean_score=("speed_safety_score", "mean") if "speed_safety_score" in df.columns else ("SSS", "mean"),
        ).round(2).reset_index()
        summary.to_csv(kpi_path, index=False)
    except Exception:
        pass  # KPI export is best-effort

"""Speed Safety Score engine for RoadSense."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml
from loguru import logger

CONFIG_PATH = Path("config/scoring_weights.yaml")
DEFAULT_OUTPUT = Path("outputs/geojson/all_segments_scored.gpkg")
DEFAULT_GEOJSON = Path("outputs/geojson/all_segments_scored.geojson")
DEFAULT_TOP100 = Path("outputs/geojson/priority_segments_top100.geojson")


def load_config(config_path: str | Path = CONFIG_PATH) -> dict:
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")
    return yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}


def classify_tier(score: float, risk_tiers: dict) -> str:
    if score >= risk_tiers.get("critical", 0.75):
        return "Critical"
    if score >= risk_tiers.get("high", 0.50):
        return "High"
    if score >= risk_tiers.get("medium", 0.25):
        return "Medium"
    return "Low"


def tier_colour(tier: str) -> str:
    return {
        "Critical": "#D62728",
        "High": "#FF7F0E",
        "Medium": "#FFDD57",
        "Low": "#2CA02C",
    }.get(tier, "#999999")


def build_popup_text(row: pd.Series) -> str:
    return (
        f"Segment ID: {row.get('segment_id', 'N/A')}\n"
        f"Posted Limit: {row.get('posted_limit', 'N/A')} km/h\n"
        f"85th Pct Speed: {row.get('v85', 'N/A')} km/h\n"
        f"Safe System Reference: {row.get('safe_system_ref', 'N/A')} km/h\n"
        f"Speed Safety Score: {row.get('SSS', 0):.2f}  ← {row.get('risk_tier', 'N/A')}\n"
        f"VRU Exposure: {row.get('B_score', 0):.2f}\n"
        f"Road Environment: {row.get('C_score', 0):.2f}"
    )


def compute_sss(gdf: gpd.GeoDataFrame, config: dict | None = None) -> gpd.GeoDataFrame:
    config = config or load_config()
    weights = config.get("weights", {})
    sss_weights = config.get("sss", {})
    risk_tiers = config.get(
        "risk_tiers",
        config.get("thresholds", {"critical": 0.75, "high": 0.50, "medium": 0.25, "low": 0.00}),
    )

    module_a_weight = weights.get("w_A", sss_weights.get("module_a", 0.40))
    module_b_weight = weights.get("w_B", sss_weights.get("module_b", 0.40))
    module_c_weight = weights.get("w_C", sss_weights.get("module_c", 0.20))

    scored = gdf.copy()
    scored["SSS"] = (
        module_a_weight * scored.get("A_score", 0)
        + module_b_weight * scored.get("B_score", 0)
        + module_c_weight * scored.get("C_score", 0)
    ).round(4)
    scored["risk_tier"] = scored["SSS"].apply(lambda value: classify_tier(float(value), risk_tiers))
    scored["risk_colour"] = scored["risk_tier"].map(tier_colour)
    scored["popup_text"] = scored.apply(build_popup_text, axis=1)
    scored["rank"] = scored["SSS"].rank(method="dense", ascending=False).astype(int)
    return scored


def export_outputs(
    gdf: gpd.GeoDataFrame,
    gpkg_path: str | Path = DEFAULT_OUTPUT,
    geojson_path: str | Path = DEFAULT_GEOJSON,
    top100_path: str | Path = DEFAULT_TOP100,
) -> None:
    gpkg_file = Path(gpkg_path)
    geojson_file = Path(geojson_path)
    top100_file = Path(top100_path)
    gpkg_file.parent.mkdir(parents=True, exist_ok=True)
    geojson_file.parent.mkdir(parents=True, exist_ok=True)
    top100_file.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(gpkg_file, driver="GPKG", layer="segments")
    gdf.to_file(geojson_file, driver="GeoJSON")
    top_columns = [
        column
        for column in [
            "segment_id",
            "SSS",
            "risk_tier",
            "risk_colour",
            "rank",
            "posted_limit",
            "v85",
            "safe_system_ref",
            "A_score",
            "B_score",
            "C_score",
            "popup_text",
            "geometry",
        ]
        if column in gdf.columns
    ]
    gdf.nlargest(100, "SSS")[top_columns].to_file(top100_file, driver="GeoJSON")


def run(
    input_path: str = "data/processed/segments_master.gpkg",
    config_path: str = CONFIG_PATH,
    output_path: str = DEFAULT_OUTPUT,
    geojson_path: str = DEFAULT_GEOJSON,
    top100_path: str = DEFAULT_TOP100,
) -> gpd.GeoDataFrame:
    logger.info("Speed Safety Score Engine")
    config = load_config(config_path)
    gdf = gpd.read_file(input_path, layer="segments")
    scored = compute_sss(gdf, config=config)
    export_outputs(scored, output_path, geojson_path, top100_path)
    logger.success("Speed Safety Score exported")
    return scored


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the RoadSense composite scorer.")
    parser.add_argument("--input-path", default="data/processed/segments_master.gpkg")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--geojson-path", default=str(DEFAULT_GEOJSON))
    parser.add_argument("--top100-path", default=str(DEFAULT_TOP100))
    args = parser.parse_args()

    run(args.input_path, args.config, args.output_path, args.geojson_path, args.top100_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

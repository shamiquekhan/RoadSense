"""Module B: vulnerable road user exposure analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from loguru import logger

WEIGHTS_PATH = Path("config/scoring_weights.yaml")


def load_component_weights() -> dict:
    if WEIGHTS_PATH.exists():
        config = yaml.safe_load(WEIGHTS_PATH.read_text(encoding="utf-8")) or {}
        return config.get("module_b", {})
    return {"attractor": 0.35, "population": 0.25, "conflict": 0.20, "ptw": 0.20}


COMPONENT_WEIGHTS = load_component_weights()


def normalise(series: pd.Series) -> pd.Series:
    """Min-max normalize a series to [0, 1]."""

    cleaned = series.fillna(0)
    minimum = cleaned.min()
    maximum = cleaned.max()
    if pd.isna(minimum) or pd.isna(maximum) or maximum == minimum:
        return pd.Series(0.5, index=series.index)
    return (cleaned - minimum) / (maximum - minimum)


def score_dataframe(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    attractor_raw = (
        gdf.get("near_attractor", pd.Series(0, index=gdf.index)) * 0.6
        + normalise(gdf.get("attractor_count", pd.Series(0, index=gdf.index))) * 0.4
    )
    gdf["attractor_score"] = normalise(attractor_raw)
    gdf["pop_score"] = normalise(gdf.get("pop_density_norm", pd.Series(0, index=gdf.index)))
    gdf["conflict_score"] = normalise(
        normalise(gdf.get("intersection_density", pd.Series(0, index=gdf.index))) * gdf["attractor_score"]
    )
    gdf["ptw_score"] = normalise(gdf.get("ptw_index", pd.Series(0, index=gdf.index)))

    land_use_multiplier = gdf.get("land_use_class", pd.Series("unknown", index=gdf.index)).map(
        {
            "commercial": 1.20,
            "mixed_use": 1.15,
            "residential": 1.05,
            "industrial": 0.85,
            "rural": 0.70,
        }
    ).fillna(1.0)

    raw_score = (
        COMPONENT_WEIGHTS.get("attractor", 0.35) * gdf["attractor_score"]
        + COMPONENT_WEIGHTS.get("population", 0.25) * gdf["pop_score"]
        + COMPONENT_WEIGHTS.get("conflict", 0.20) * gdf["conflict_score"]
        + COMPONENT_WEIGHTS.get("ptw", 0.20) * gdf["ptw_score"]
    )
    gdf["B_score"] = (normalise(raw_score * land_use_multiplier)).round(4)
    return gdf


def run(input_path: str = "data/processed/segments_master.gpkg", output_path: str = "data/processed/segments_master.gpkg") -> gpd.GeoDataFrame:
    logger.info("Module B: VRU Exposure Analysis")
    gdf = gpd.read_file(input_path, layer="segments")
    scored = score_dataframe(gdf)
    scored.to_file(output_path, driver="GPKG", layer="segments")
    logger.success("Module B complete")
    return scored


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RoadSense Module B.")
    parser.add_argument("--input-path", default="data/processed/segments_master.gpkg")
    parser.add_argument("--output-path", default="data/processed/segments_master.gpkg")
    args = parser.parse_args()
    run(args.input_path, args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

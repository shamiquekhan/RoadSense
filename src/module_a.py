"""Module A: speed alignment analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from loguru import logger

SAFE_SYSTEM_PATH = Path("config/safe_system_speeds.yaml")


def load_safe_system_reference() -> dict:
    if SAFE_SYSTEM_PATH.exists():
        return yaml.safe_load(SAFE_SYSTEM_PATH.read_text(encoding="utf-8")) or {}
    return {"default": 50.0}


SAFE_SYSTEM_SPEEDS = load_safe_system_reference()


def get_safe_system_reference(functional_class: str, urban_rural: str, near_attractor: int = 0) -> float:
    """Return the Safe System reference speed for a road segment."""

    lookup_key = f"{functional_class}_{urban_rural}".lower().replace(" ", "_")
    reference = SAFE_SYSTEM_SPEEDS.get(lookup_key, SAFE_SYSTEM_SPEEDS.get("default", 50.0))
    if near_attractor:
        reference = max(float(reference) - 10.0, 20.0)
    return float(reference)


def compute_speed_gap(row: pd.Series) -> float:
    if pd.isna(row.get("v85")) or pd.isna(row.get("posted_limit")):
        return np.nan
    return float(row["v85"] - row["posted_limit"])


def compute_safe_system_gap(row: pd.Series) -> float:
    if pd.isna(row.get("posted_limit")):
        return np.nan
    reference = get_safe_system_reference(
        str(row.get("functional_class", "local")),
        str(row.get("urban_rural", "urban")),
        int(row.get("near_attractor", 0)),
    )
    return float(row["posted_limit"] - reference)


def normalise_to_unit(series: pd.Series, clip_pct: float = 0.99) -> pd.Series:
    """Normalise values to [0, 1] after clipping negative values to zero."""

    cleaned = series.fillna(0).clip(lower=0)
    upper = cleaned.quantile(clip_pct)
    clipped = cleaned.clip(upper=upper if pd.notna(upper) else cleaned.max())
    maximum = clipped.max()
    if pd.isna(maximum) or maximum == 0:
        return pd.Series(0.0, index=series.index)
    return clipped / maximum


def score_dataframe(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    gdf["speed_gap"] = gdf.apply(compute_speed_gap, axis=1)
    gdf["safe_system_ref"] = gdf.apply(
        lambda row: get_safe_system_reference(
            row.get("functional_class", "local"),
            row.get("urban_rural", "urban"),
            int(row.get("near_attractor", 0)),
        ),
        axis=1,
    )
    gdf["safe_system_gap"] = gdf.apply(compute_safe_system_gap, axis=1)
    gdf["speed_exceeds_limit"] = gdf["speed_gap"] > 5

    gap_norm = normalise_to_unit(gdf["speed_gap"])
    safe_gap_norm = normalise_to_unit(gdf["safe_system_gap"])
    gdf["A_score"] = (0.5 * gap_norm + 0.5 * safe_gap_norm).round(4)
    return gdf


def run(input_path: str = "data/processed/segments_master.gpkg", output_path: str = "data/processed/segments_master.gpkg") -> gpd.GeoDataFrame:
    logger.info("Module A: Speed Alignment Analysis")
    gdf = gpd.read_file(input_path, layer="segments")
    scored = score_dataframe(gdf)
    scored.to_file(output_path, driver="GPKG", layer="segments")
    logger.success("Module A complete")
    return scored


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RoadSense Module A.")
    parser.add_argument("--input-path", default="data/processed/segments_master.gpkg")
    parser.add_argument("--output-path", default="data/processed/segments_master.gpkg")
    args = parser.parse_args()
    run(args.input_path, args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

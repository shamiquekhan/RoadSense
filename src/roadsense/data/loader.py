"""ADB challenge data loader — handles GeoJSON loading, cleaning, and schema mapping."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from loguru import logger

from roadsense.config import (
    MIN_SAMPLE_SIZE,
    MIN_RELIABLE_SPEED,
    SPEED_LIMIT_DEFAULTS,
    DROP_COLS,
    RAW_DATA_DIR,
)

MASTER_CRS = "EPSG:4326"
ADB_FILES: dict[str, str] = {
    "Thailand": "ADB_Innovation_Thailand.geojson",
    "Maharashtra": "ADB_Innovation_Maharashtra.geojson",
}


def load_adb_datasets(data_dir: str | Path | None = None) -> gpd.GeoDataFrame:
    """Load and merge ADB GeoJSON datasets for both regions."""
    data_dir = Path(data_dir) if data_dir else RAW_DATA_DIR

    gdfs: list[gpd.GeoDataFrame] = []
    for region, filename in ADB_FILES.items():
        path = data_dir / filename
        if not path.exists():
            logger.warning(f"Missing ADB data file: {path}")
            continue
        gdf = gpd.read_file(path)
        gdf["region"] = region
        gdf = _normalise_road_name(gdf)
        gdf = _assign_segment_id(gdf)
        gdfs.append(gdf)
        logger.info(f"  {region}: {len(gdf)} sections loaded")

    if not gdfs:
        raise FileNotFoundError(f"No ADB data found in {data_dir}")

    return _merge_datasets(gdfs)


def _normalise_road_name(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Collate road name from whichever column is available."""
    if "english_ro" in gdf.columns and "names_primary" not in gdf.columns:
        gdf["road_name"] = gdf["english_ro"]
    elif "names_primary" in gdf.columns and "english_ro" not in gdf.columns:
        gdf["road_name"] = gdf["names_primary"]
    else:
        gdf["road_name"] = ""
    for c in ["english_ro", "names_primary"]:
        if c in gdf.columns:
            gdf.drop(columns=[c], inplace=True)
    return gdf


def _assign_segment_id(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if "OBJECTID" in gdf.columns:
        gdf["segment_id"] = gdf["OBJECTID"].astype(str)
    else:
        gdf["segment_id"] = [f"SEG-{i:06d}" for i in range(len(gdf))]
    return gdf


def _merge_datasets(gdfs: list[gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    common = list(set.intersection(*[set(g.columns) for g in gdfs]))
    merged = pd.concat([g[[c for c in common if c in g.columns]] for g in gdfs], ignore_index=True)
    if "geometry" in merged.columns:
        merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=MASTER_CRS)
    return merged


def clean_adb(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Filter invalid records, impute missing values, fix dtypes."""
    df = df.copy()

    before = len(df)
    if "AnalysisStatus" in df.columns:
        df = df[df["AnalysisStatus"] == "Valid"]
    logger.info(f"  AnalysisStatus==Valid: {len(df)} (dropped {before - len(df)})")

    drop = [c for c in DROP_COLS if c in df.columns]
    if drop:
        df.drop(columns=drop, inplace=True)

    before = len(df)
    if "SampleSize_avg" in df.columns:
        df = df[df["SampleSize_avg"] >= MIN_SAMPLE_SIZE]
    logger.info(f"  SampleSize >= {MIN_SAMPLE_SIZE}: {len(df)} (dropped {before - len(df)})")

    df = _fix_string_columns(df)
    df = _fix_speed_limit(df)
    df = _clip_bounded_fields(df)

    df.dropna(subset=["MedianSpeed", "F85thPercentileSpeed", "PercentOverLimit"], inplace=True)

    before = len(df)
    if "F85thPercentileSpeed" in df.columns:
        df = df[df["F85thPercentileSpeed"] >= MIN_RELIABLE_SPEED]
    if before - len(df):
        logger.info(f"  F85 < {MIN_RELIABLE_SPEED} km/h: dropped {before - len(df)}")

    return df.reset_index(drop=True)


def _fix_string_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "LandUse" in df.columns:
        df["LandUse"] = df["LandUse"].astype(str).str.upper().str.strip()
        df["LandUse"] = df["LandUse"].replace(["NAN", "NONE", "", "NULL"], np.nan)
        df["LandUse"] = df["LandUse"].fillna("RURAL")
    if "RoadClass" in df.columns:
        df["RoadClass"] = df["RoadClass"].astype(str).str.lower().str.strip()
    return df


def _fix_speed_limit(df: pd.DataFrame) -> pd.DataFrame:
    if "SpeedLimit" not in df.columns:
        return df
    if df["SpeedLimit"].dtype in ("object", "string"):
        df["SpeedLimit"] = pd.to_numeric(df["SpeedLimit"], errors="coerce")
    mask = df["SpeedLimit"].isna() | (df["SpeedLimit"] <= 0)
    df.loc[mask, "SpeedLimit"] = df.loc[mask, "RoadClass"].map(SPEED_LIMIT_DEFAULTS)
    logger.info(f"  SpeedLimit imputed for {mask.sum()} sections")
    return df


def _clip_bounded_fields(df: pd.DataFrame) -> pd.DataFrame:
    if "PercentOverLimit" in df.columns:
        df["PercentOverLimit"] = df["PercentOverLimit"].clip(0, 1)
    if "Percentile" in df.columns:
        df["Percentile"] = df["Percentile"].clip(0, 1)
    return df


def map_to_roadsense_schema(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rename ADB fields to RoadSense naming conventions."""
    rename = {
        "RoadClass": "functional_class",
        "LandUse": "urban_rural",
        "SpeedLimit": "posted_limit",
        "F85thPercentileSpeed": "v85",
        "SampleSize_avg": "obs_count",
        "WeightedSample": "traffic_count",
        "StreetImageLink": "imagery_url",
    }
    available = {k: v for k, v in rename.items() if k in df.columns}
    df = df.rename(columns=available)

    if "urban_rural" in df.columns:
        df["urban_rural"] = df["urban_rural"].str.lower().str.strip()

    if "Shape_Length" in df.columns:
        df["length_m"] = df["Shape_Length"]
    else:
        utm = df.estimate_utm_crs()
        df["length_m"] = df.to_crs(utm).geometry.length

    if "median_speed" not in df.columns and "MedianSpeed" in df.columns:
        df["median_speed"] = df["MedianSpeed"]

    return df


def load_and_clean(data_dir: str | Path | None = None) -> gpd.GeoDataFrame:
    """One-shot: load ADB data + clean."""
    df = load_adb_datasets(data_dir)
    df = clean_adb(df)
    return df

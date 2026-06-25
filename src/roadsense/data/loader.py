"""ADB challenge data loader — handles GeoJSON/GPKG loading, cleaning, and schema mapping."""

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
ADB_FILES: dict[str, dict[str, str | None]] = {
    "Thailand": {
        "path": "Road_Safety_Performance_Indicators__Thailand_(Feature).gpkg",
        "layer": "ADB_Results_D4",
    },
    "Maharashtra": {
        "path": "Road_Safety_Performance_Indicators__Maharashtra_(Feature).gpkg",
        "layer": "OvertureNetwork_wResults",
    },
}


def load_adb_datasets(
    data_dir: str | Path | None = None, use_sample: bool = False
) -> gpd.GeoDataFrame:
    """Load and merge ADB GeoPackage datasets for both regions.

    Tries data_dir first (primary), then the archive subdirectory (fallback).
    When use_sample=True, skips GPKG files and loads the sample GeoJSONs instead.
    """
    data_dir = Path(data_dir) if data_dir else RAW_DATA_DIR
    archive_dir = data_dir / ".." / "Archive-20260531T145050Z-3-001" / "Archive"
    legacy_dir = data_dir  # original GeoJSON files

    gdfs: list[gpd.GeoDataFrame] = []
    for region, info in ADB_FILES.items():
        path: Path | None = None
        layer: str | None = None

        if use_sample:
            # Sample GeoJSON directly (skip GPKG)
            legacy = (legacy_dir / f"ADB_Innovation_{region}.geojson").resolve()
            if legacy.exists():
                path = legacy
                logger.info(f"  {region}: using sample GeoJSON (--use-sample)")
            else:
                logger.warning(f"Missing sample GeoJSON for {region} at {legacy}")
                continue
        else:
            # 1. Primary: data_dir / GPKG
            primary = (data_dir / info["path"]).resolve()
            if primary.exists():
                path = primary
                layer = info["layer"]
            else:
                # 2. Fallback: archive directory
                ap = (archive_dir / info["path"]).resolve()
                if ap.exists():
                    path = ap
                    layer = info["layer"]
                else:
                    # 3. Last resort: original GeoJSON
                    legacy = (legacy_dir / f"ADB_Innovation_{region}.geojson").resolve()
                    if legacy.exists():
                        path = legacy
                        logger.info(f"  {region}: using sample GeoJSON")
                    else:
                        logger.warning(f"Missing ADB data file for {region}")
                        continue

        kwargs = {}
        if layer:
            kwargs["layer"] = layer
        gdf = gpd.read_file(str(path), **kwargs)

        # Reproject to WGS84 if needed
        if gdf.crs and gdf.crs.is_projected:
            gdf = gdf.to_crs(MASTER_CRS)

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
    merged = pd.concat(
        [g[[c for c in common if c in g.columns]] for g in gdfs], ignore_index=True
    )
    if "geometry" in merged.columns:
        merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=MASTER_CRS)
    return merged


def _ensure_shape_length(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Ensure Shape_Length column exists (may be RoadLength in some datasets)."""
    if "Shape_Length" in df.columns:
        return df
    if "RoadLength" in df.columns:
        df["Shape_Length"] = df["RoadLength"]
        return df
    # Compute from geometry in a projected CRS
    utm = df.estimate_utm_crs()
    df["Shape_Length"] = df.to_crs(utm).geometry.length
    return df


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
    logger.info(
        f"  SampleSize >= {MIN_SAMPLE_SIZE}: {len(df)} (dropped {before - len(df)})"
    )

    df = _fix_string_columns(df)
    df = _fix_speed_limit(df)
    df = _clip_bounded_fields(df)
    df = _ensure_shape_length(df)

    df.dropna(
        subset=["MedianSpeed", "F85thPercentileSpeed", "PercentOverLimit"], inplace=True
    )

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
    elif "RoadLength" in df.columns:
        df["length_m"] = df["RoadLength"]
    else:
        utm = df.estimate_utm_crs()
        df["length_m"] = df.to_crs(utm).geometry.length

    if "median_speed" not in df.columns and "MedianSpeed" in df.columns:
        df["median_speed"] = df["MedianSpeed"]

    return df


def load_and_clean(
    data_dir: str | Path | None = None, use_sample: bool = False
) -> gpd.GeoDataFrame:
    """One-shot: load ADB data + clean."""
    df = load_adb_datasets(data_dir, use_sample=use_sample)
    df = clean_adb(df)
    return df

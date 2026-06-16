"""ADB preprocessing pipeline adapted into RoadSense.

Usage:
    python scripts/preprocess_adb.py \
        --thailand path/to/thailand_road_safety.gpkg \
        --maharashtra path/to/maharashtra_road_safety.gpkg \
        --output outputs/processed_road_safety.gpkg
"""

from pathlib import Path
import argparse
import geopandas as gpd
import pandas as pd
import numpy as np
import joblib
from shapely import wkt
from sklearn.preprocessing import StandardScaler, MinMaxScaler


def load_dataset(path: Path, region: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    gdf["region"] = region
    print(f"Loaded {region}: {len(gdf)} rows from {path}")
    return gdf


def clean(df: pd.DataFrame, min_sample: int = 500) -> pd.DataFrame:
    if "AnalysisStatus" in df.columns:
        df = df[df["AnalysisStatus"] == "Valid"].copy()

    drop_cols = [
        "RoadLength", "Percent_", "ForAnalysis", "SpeedLimitFloor",
        "NO_OF_Result_Segments", "ProvinceID", "PercentileBand"
    ]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")

    if "SampleSize_avg" in df.columns:
        df = df[df["SampleSize_avg"] >= min_sample].copy()

    # normalise text fields
    if "LandUse" in df.columns:
        df["LandUse"] = df["LandUse"].astype(str).str.upper().str.strip().fillna("RURAL")
    if "RoadClass" in df.columns:
        df["RoadClass"] = df["RoadClass"].astype(str).str.lower().str.strip()

    # impute speed limits from road class
    defaults = {"motorway": 110, "trunk": 90, "primary": 80, "secondary": 60}
    if "SpeedLimit" in df.columns and "RoadClass" in df.columns:
        mask = df["SpeedLimit"].isnull() | (df["SpeedLimit"] == 0)
        df.loc[mask, "SpeedLimit"] = df.loc[mask, "RoadClass"].map(defaults)

    # drop rows without core speed metrics
    required = [c for c in ["MedianSpeed", "F85thPercentileSpeed", "PercentOverLimit"] if c in df.columns]
    if required:
        df = df.dropna(subset=required)

    if "PercentOverLimit" in df.columns:
        df["PercentOverLimit"] = df["PercentOverLimit"].clip(0, 1)

    return df.reset_index(drop=True)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    # ensure numeric speed columns
    num_cols = ["F85thPercentileSpeed", "MedianSpeed", "SpeedLimit", "PercentOverLimit", "WeightedSample", "SampleSize_avg"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')

    # re-impute SpeedLimit from RoadClass if coercion produced NaNs
    defaults = {"motorway": 110, "trunk": 90, "primary": 80, "secondary": 60}
    if "SpeedLimit" in df.columns and "RoadClass" in df.columns:
        mask = df["SpeedLimit"].isnull() | (df["SpeedLimit"] == 0)
        df.loc[mask, "SpeedLimit"] = df.loc[mask, "RoadClass"].map(defaults)

    if "F85thPercentileSpeed" in df.columns and "SpeedLimit" in df.columns:
        df["speed_excess_85"] = df["F85thPercentileSpeed"] - df["SpeedLimit"]
    if "MedianSpeed" in df.columns and "SpeedLimit" in df.columns:
        df["speed_excess_median"] = df["MedianSpeed"] - df["SpeedLimit"]

    if "WeightedSample" in df.columns:
        df["log_weighted_sample"] = np.log1p(df["WeightedSample"]).astype(float)
    if "SampleSize_avg" in df.columns:
        df["log_sample_size"] = np.log1p(df["SampleSize_avg"]).astype(float)

    # risk indices
    if all(c in df.columns for c in ["PercentOverLimit", "speed_excess_85", "SpeedLimit"]):
        df["speed_risk_index"] = (
            df["PercentOverLimit"] * np.maximum(df["speed_excess_85"], 0) / df["SpeedLimit"].replace(0, np.nan)
        )
    if "RankedPercentile" in df.columns and "speed_risk_index" in df.columns:
        df["exposure_risk"] = df["RankedPercentile"] / 100 * df["speed_risk_index"]
    if "LandUse" in df.columns:
        df["urban_flag"] = (df["LandUse"] == "URBAN").astype(int)
        if "exposure_risk" in df.columns:
            df["urban_weighted_risk"] = df["exposure_risk"] * (1 + 0.5 * df["urban_flag"])        

    df["is_speed_problem"] = 0
    if all(c in df.columns for c in ["PercentOverLimit", "speed_excess_85"]):
        df["is_speed_problem"] = (
            (df["PercentOverLimit"] > 0.5) | (df["speed_excess_85"] > 20)
        ).astype(int)

    return df


def encode_and_normalise(df: pd.DataFrame, fit: bool = True):
    # one-hot encode simple categoricals
    for c in ["RoadClass", "LandUse"]:
        if c in df.columns:
            dummies = pd.get_dummies(df[c], prefix=c, dummy_na=False)
            df = pd.concat([df.drop(columns=[c]), dummies], axis=1)

    # scalers
    standard_cols = [c for c in ["MedianSpeed", "F85thPercentileSpeed", "speed_excess_85", "speed_excess_median", "log_weighted_sample", "log_sample_size"] if c in df.columns]
    minmax_cols = [c for c in ["SpeedLimit", "Shape_Length"] if c in df.columns]

    scalers = {}
    if standard_cols:
        ss = StandardScaler()
        df[standard_cols] = ss.fit_transform(df[standard_cols]) if fit else ss.transform(df[standard_cols])
        scalers['standard'] = ss
    if minmax_cols:
        mm = MinMaxScaler()
        df[minmax_cols] = mm.fit_transform(df[minmax_cols]) if fit else mm.transform(df[minmax_cols])
        scalers['minmax'] = mm

    return df, scalers


def run_pipeline(thailand_path: Path, maharashtra_path: Path, output: Path, min_sample: int = 500):
    gdfs = []
    if thailand_path and thailand_path.exists():
        gdfs.append(load_dataset(thailand_path, "Thailand"))
    if maharashtra_path and maharashtra_path.exists():
        gdfs.append(load_dataset(maharashtra_path, "Maharashtra"))

    if not gdfs:
        raise FileNotFoundError("No input datasets found. Provide valid file paths.")

    common = set(gdfs[0].columns)
    for g in gdfs[1:]:
        common = common.intersection(set(g.columns))
    common_cols = list(common)
    gdf = pd.concat([g[common_cols] for g in gdfs], ignore_index=True)
    print(f"Combined rows: {len(gdf)}")

    gdf = clean(gdf, min_sample=min_sample)
    print(f"After cleaning: {len(gdf)}")

    gdf = engineer_features(gdf)
    gdf, scalers = encode_and_normalise(gdf, fit=True)

    # save scalers
    out_dir = output.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, s in scalers.items():
        joblib.dump(s, out_dir / f"{k}_scaler.pkl")

    # diagnostics for geometry and CRS
    print("-- Export diagnostics --")
    print("gdf type:", type(gdf))
    print("gdf.crs:", getattr(gdf, "crs", None))
    if 'geometry' in gdf.columns:
        try:
            print("geometry sample:")
            print(gdf.geometry.head(5))
        except Exception as e:
            print("Failed to show geometry sample:", e)

    # try to build a valid GeoDataFrame when geometry exists
    if 'geometry' in gdf.columns and not isinstance(gdf, gpd.GeoDataFrame):
        if len(gdf) > 0 and gdf['geometry'].dtype == object and isinstance(gdf['geometry'].iloc[0], str):
            gdf = gdf.copy()
            gdf['geometry'] = gdf['geometry'].apply(lambda x: wkt.loads(x) if pd.notna(x) else None)

        crs = getattr(gdf, "crs", None) or "EPSG:4326"
        gdf = gpd.GeoDataFrame(gdf, geometry='geometry', crs=crs)

    # save as gpkg if we have real geometries
    if isinstance(gdf, gpd.GeoDataFrame) and gdf.geometry.notnull().any():
        try:
            gdf.to_file(output, driver="GPKG", layer=output.stem)
            print(f"Saved geopackage to {output}")
        except Exception as e:
            print("Geopackage save failed:", e)
            gdf.to_csv(str(output).replace('.gpkg', '.csv'), index=False)
            print("Saved CSV fallback")
    else:
        gdf.to_csv(str(output).replace('.gpkg', '.csv'), index=False)
        print("Saved CSV output")

    return gdf


if __name__ == '__main__':
    p = argparse.ArgumentParser(description="ADB preprocessing pipeline")
    p.add_argument('--thailand', type=Path, default=Path('data/ADB_Innovation_Thailand/thailand_road_safety.gpkg'))
    p.add_argument('--maharashtra', type=Path, default=Path('data/ADB_Innovation_Maharashtra/maharashtra_road_safety.gpkg'))
    p.add_argument('--output', type=Path, default=Path('outputs/processed_road_safety.gpkg'))
    p.add_argument('--min-sample', type=int, default=500)
    args = p.parse_args()

    run_pipeline(args.thailand, args.maharashtra, args.output, min_sample=args.min_sample)

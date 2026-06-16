# ADB AI for Safer Roads 2026 — Complete Data Guide
> Data interpretation · Preprocessing · Normalisation · Pipeline Integration  
> Based on: *AI for Safer Roads Innovation Challenge 2026 — Data User Guide v1.0* (Agilysis / ADB, May 2026)

---

## Table of Contents
1. [Dataset Overview](#1-dataset-overview)
2. [Data Sources & Provenance](#2-data-sources--provenance)
3. [Schema Reference — Field-by-Field](#3-schema-reference--field-by-field)
4. [Loading the Data](#4-loading-the-data)
5. [Exploratory Data Analysis (EDA) Checklist](#5-exploratory-data-analysis-eda-checklist)
6. [Preprocessing](#6-preprocessing)
7. [Feature Engineering](#7-feature-engineering)
8. [Normalisation Strategy](#8-normalisation-strategy)
9. [Full Preprocessing Pipeline (Code)](#9-full-preprocessing-pipeline-code)
10. [Modelling Considerations](#10-modelling-considerations)
11. [Common Pitfalls & Gotchas](#11-common-pitfalls--gotchas)
12. [Attribution & Licensing](#12-attribution--licensing)

---

## 1. Dataset Overview

Two separate geospatial road safety datasets are provided:

| Dataset | Region | Network Accessed | Road Length Split |
|---|---|---|---|
| `ADB_Innovation_Thailand` | Thailand | December 2024 | ~75% Rural / ~25% Urban |
| `ADB_Innovation_Maharashtra` | Maharashtra, India | May 2025 | TBD from file |

Both datasets share the **same schema** (minor field-level differences may exist due to collection time). Each row represents one **road section** — a simplified stretch of road between major junctions derived from the Overture Maps network.

### What the data is trying to answer
- Which roads carry the most travel volume (top 75% of all travel)?
- On those high-volume roads, what fraction of vehicles exceed the posted speed limit?
- What are the median and 85th-percentile speeds on each section?
- Is the section urban or rural?

The combination of **traffic volume × speed compliance** allows ranking of road sections by risk exposure — the core task of the challenge.

---

## 2. Data Sources & Provenance

### 2.1 Overture Maps (Road Network)
- **What it is**: Open road network data; superset of OpenStreetMap with additional commercial enrichment.
- **Licence**: Open Database Commons (ODbL)
- **Attribution required**: `© OpenStreetMap contributors, Overture Maps Foundation`
- **Key caveat**: Network was frozen at a point in time (Dec 2024 for Thailand, May 2025 for Maharashtra). Road geometry and classifications may have changed since.
- **Road classes included**: `motorway`, `trunk`, `primary`, `secondary` only. Local/residential roads are **excluded**.

### 2.2 TomTom Move API (Traffic & Speed Data)
- **What it is**: Commercial probe/GPS-based traffic dataset; speeds derived from actual vehicle trajectories.
- **Sampling method**: One sample per 10 km along each road section.  
  - A 20 km section → 2 samples; a 5 km section → 1 sample.
- **Weighting**: Samples are weighted by road length (longer sections get proportionally higher weight in percentile calculations).
- **Speed limit source**: Provided by TomTom, **not validated** against official records — treat as approximate.
- **SpeedLimit reliability**: Can change along a section; only one value is stored. Treat with caution on long sections.

### 2.3 NASA GRUMP (Land Use)
- **What it is**: Global Rural–Urban Mapping Project — a geodatabase classifying land as rural or urban.
- **Usage**: Each road section is labelled `RURAL` or `URBAN` based on spatial overlay.
- **Limitation**: GRUMP is a coarse dataset; peri-urban or transitional zones may be misclassified.

---

## 3. Schema Reference — Field-by-Field

### 3.1 Fields to USE in Analysis

| Field | Type | Description | Notes |
|---|---|---|---|
| `SampleSize_avg` | Float | Average annual probe count for the section | Primary reliability indicator — low values = unreliable speeds |
| `SampleSizeTotal` | Float | Total probe count (same as avg if only one TomTom dataset used) | Cross-check with `SampleSize_avg` |
| `WeightedSample` | Float | `SampleSize_avg × road_length` — traffic volume proxy | **Core feature**: use for percentile ranking |
| `Percentile` | Float [0–1] | Which travel percentile the section sits in (0 = lowest traffic, 1 = highest) | 0.042 means bottom 5% |
| `RankedPercentile` | Float [0–100] | Same as above, rescaled to 0–100 | Easier for filtering and display |
| `InvPercentile` | Float [0–1] | `1 - Percentile` | Used in dashboard filters; invert back when needed |
| `SpeedLimit` | Int | Posted speed limit (km/h) from TomTom | Not validated — treat as approximate |
| `MedianSpeed` | Float | 50th percentile observed speed (km/h) | Core safety metric |
| `F85thPercentileSpeed` | Float | 85th percentile observed speed (km/h) | **Key engineering design metric**; standard in road safety analysis |
| `NumberOverLimit` | Float | Estimated count of vehicles/year exceeding limit (probe-based, not AADF) | Relative comparison only; not absolute counts |
| `PercentOverLimit` | Float [0–1] | Fraction of vehicles exceeding the speed limit | **Primary compliance metric** |
| `RoadClass` | String | Overture road classification | Categorical: `motorway`, `trunk`, `primary`, `secondary` |
| `LandUse` | String | GRUMP land use classification | Categorical: `RURAL`, `URBAN` |
| `english_ro` | String | English street name from Overture | Use for display/reporting; not for modelling |
| `Shape_Length` | Float | Geometric road section length (metres) | Use this, **not** `RoadLength` |

### 3.2 Fields to IGNORE

| Field | Reason |
|---|---|
| `RoadLength` | Superseded by `Shape_Length` — explicitly stated in guide |
| `Percent_` | Internal calculation artifact — not meaningful |
| `ForAnalysis` | Internal flag — ignore |
| `ProvinceID` | Thailand-specific; not useful for cross-dataset analysis |
| `SpeedLimitFloor` | Internal duplicate — ignore |
| `NO_OF_Result_Segments` | Internal aggregation counter |
| `OBJECTID` / `OvertureID` | GIS auto-generated IDs; use as row keys only if joining to GIS |
| `PercentileBand` | String bucketing of `Percentile` — derive yourself for full control |
| `AnalysisStatus` | Internal QA flag — keep only rows where `AnalysisStatus == "Valid"` |

### 3.3 Context Fields (use for display/filtering, not core modelling)

| Field | Use |
|---|---|
| `StreetImageLink` | Lat/lon bounding box → Google Street View link |
| `english_ro` | Road name for labelling outputs |

---

## 4. Loading the Data

The backend data is likely a **GeoJSON**, **GeoPackage (.gpkg)**, **Shapefile (.shp)**, or **CSV with WKT geometry**. Load accordingly:

```python
import pandas as pd
import geopandas as gpd
import numpy as np

# --- Option A: GeoPackage / Shapefile (most likely) ---
gdf_thailand = gpd.read_file("ADB_Innovation_Thailand/thailand_road_safety.gpkg")
gdf_maharashtra = gpd.read_file("ADB_Innovation_Maharashtra/maharashtra_road_safety.gpkg")

# --- Option B: CSV (if geometry is WKT) ---
# from shapely import wkt
# df = pd.read_csv("data.csv")
# gdf = gpd.GeoDataFrame(df, geometry=df["geometry"].apply(wkt.loads), crs="EPSG:4326")

# --- Inspect immediately ---
print(gdf_thailand.shape)
print(gdf_thailand.dtypes)
print(gdf_thailand.head(3))
print(gdf_thailand.crs)  # Should be EPSG:4326 (WGS84)
```

### 4.1 Merge Both Regions

```python
gdf_thailand["region"] = "Thailand"
gdf_maharashtra["region"] = "Maharashtra"

# Align columns (minor schema differences may exist)
common_cols = list(set(gdf_thailand.columns) & set(gdf_maharashtra.columns))
gdf_all = pd.concat([
    gdf_thailand[common_cols],
    gdf_maharashtra[common_cols]
], ignore_index=True)

print(f"Combined dataset: {len(gdf_all)} road sections")
```

---

## 5. Exploratory Data Analysis (EDA) Checklist

Run this before any modelling:

```python
# ── 1. Filter to valid records only ──────────────────────────────────
gdf = gdf_all[gdf_all["AnalysisStatus"] == "Valid"].copy()
print(f"Valid sections: {len(gdf)}")

# ── 2. Missing values ─────────────────────────────────────────────────
print(gdf[["SampleSize_avg", "MedianSpeed", "F85thPercentileSpeed",
           "PercentOverLimit", "SpeedLimit", "WeightedSample"]].isnull().sum())

# ── 3. Distribution of key metrics ───────────────────────────────────
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 3, figsize=(15, 8))
metrics = ["MedianSpeed", "F85thPercentileSpeed", "PercentOverLimit",
           "SpeedLimit", "WeightedSample", "Shape_Length"]
for ax, col in zip(axes.flatten(), metrics):
    gdf[col].dropna().hist(ax=ax, bins=50)
    ax.set_title(col)
plt.tight_layout()
plt.savefig("eda_distributions.png")

# ── 4. Breakdown by categorical fields ───────────────────────────────
print(gdf.groupby(["LandUse", "RoadClass"])["PercentOverLimit"].agg(["mean", "median", "count"]))

# ── 5. Sample size reliability check ─────────────────────────────────
# Sections with very low sample size have unreliable speed estimates
print(gdf["SampleSize_avg"].describe())
LOW_SAMPLE_THRESHOLD = 1000  # Tune based on distribution
n_low = (gdf["SampleSize_avg"] < LOW_SAMPLE_THRESHOLD).sum()
print(f"Low-sample sections (<{LOW_SAMPLE_THRESHOLD}): {n_low} ({n_low/len(gdf)*100:.1f}%)")

# ── 6. Speed limit sanity check ───────────────────────────────────────
# Flag unrealistic speed limits
print(gdf["SpeedLimit"].value_counts().sort_index())
# Common values should be 30, 40, 50, 60, 80, 90, 100, 110, 120 km/h
```

### Key EDA Observations to Look For

| Check | What to look for |
|---|---|
| `PercentOverLimit` distribution | Should be 0–1; flag any > 1.0 as data error |
| `MedianSpeed > SpeedLimit` | Sections where majority of vehicles speed |
| `F85thPercentileSpeed ≫ SpeedLimit` | High-risk corridors |
| `SampleSize_avg < 500` | Flag as low-confidence |
| `SpeedLimit = 0 or NaN` | Missing data; impute from road class |
| Rural vs Urban `PercentOverLimit` | Rural typically higher — expect this |

---

## 6. Preprocessing

### 6.1 Filter Invalid / Low-Quality Records

```python
df = gdf.copy()

# Step 1: Keep only validated records
df = df[df["AnalysisStatus"] == "Valid"]

# Step 2: Drop columns explicitly flagged as useless
DROP_COLS = ["RoadLength", "Percent_", "ForAnalysis", "SpeedLimitFloor",
             "NO_OF_Result_Segments", "ProvinceID", "PercentileBand"]
df.drop(columns=[c for c in DROP_COLS if c in df.columns], inplace=True)

# Step 3: Reliability filter (optional — tune threshold)
MIN_SAMPLE = 500
df = df[df["SampleSize_avg"] >= MIN_SAMPLE].copy()
print(f"After quality filter: {len(df)} sections")
```

### 6.2 Handle Missing Values

```python
# Check missingness pattern
miss_pct = df.isnull().mean().sort_values(ascending=False)
print(miss_pct[miss_pct > 0])

# Speed limit: impute from road class if missing
SPEED_LIMIT_DEFAULTS = {
    "motorway": 110,
    "trunk": 90,
    "primary": 80,
    "secondary": 60
}
mask = df["SpeedLimit"].isnull() | (df["SpeedLimit"] == 0)
df.loc[mask, "SpeedLimit"] = df.loc[mask, "RoadClass"].map(SPEED_LIMIT_DEFAULTS)

# Speed metrics: sections without speed data cannot be scored
df.dropna(subset=["MedianSpeed", "F85thPercentileSpeed", "PercentOverLimit"], inplace=True)

# Land use: if missing, default to RURAL (conservative assumption)
df["LandUse"] = df["LandUse"].fillna("RURAL")
```

### 6.3 Fix Data Types

```python
# Categorical encoding
df["LandUse"] = df["LandUse"].str.upper().str.strip()
df["RoadClass"] = df["RoadClass"].str.lower().str.strip()

# Validate ranges
assert df["PercentOverLimit"].between(0, 1).all(), "PercentOverLimit out of range"
assert df["Percentile"].between(0, 1).all(), "Percentile out of range"

# Convert geometry CRS to projected for length calculations
# (EPSG:3857 for metric distances globally, or region-specific UTM)
df_geo = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
df_geo_proj = df_geo.to_crs("EPSG:3857")
df["shape_length_m"] = df_geo_proj.geometry.length  # Recalculate in metres
```

### 6.4 Derive Speed Excess Metrics

```python
# Speed excess: how far above speed limit is the 85th percentile?
df["speed_excess_85"] = df["F85thPercentileSpeed"] - df["SpeedLimit"]
df["speed_excess_median"] = df["MedianSpeed"] - df["SpeedLimit"]

# Compliance ratio (>1 means majority are speeding)
df["median_compliance_ratio"] = df["MedianSpeed"] / df["SpeedLimit"]
df["p85_compliance_ratio"] = df["F85thPercentileSpeed"] / df["SpeedLimit"]

# Binary flag: is this section a "speed problem" section?
df["is_speed_problem"] = (
    (df["PercentOverLimit"] > 0.5) |       # majority speeding
    (df["speed_excess_85"] > 20)            # 85th percentile >20 km/h over limit
).astype(int)
```

---

## 7. Feature Engineering

### 7.1 Core Risk Score Components

The challenge asks you to identify high-risk corridors. Build composite features:

```python
# ── Traffic Exposure ──────────────────────────────────────────────────
# Log-transform WeightedSample (highly skewed)
df["log_weighted_sample"] = np.log1p(df["WeightedSample"])

# ── Speed Risk Index ─────────────────────────────────────────────────
# Combines: what fraction speed × how far they exceed limit
# Higher = worse
df["speed_risk_index"] = (
    df["PercentOverLimit"] *
    np.maximum(df["speed_excess_85"], 0) / df["SpeedLimit"]
)

# ── Exposure-Weighted Risk ────────────────────────────────────────────
# Roads with high traffic AND high speeding are the priority
df["exposure_risk"] = df["RankedPercentile"] / 100 * df["speed_risk_index"]

# ── Urban Penalty ─────────────────────────────────────────────────────
# Urban speeding is more dangerous (pedestrians, cyclists, junctions)
df["urban_flag"] = (df["LandUse"] == "URBAN").astype(int)
df["urban_weighted_risk"] = df["exposure_risk"] * (1 + 0.5 * df["urban_flag"])
```

### 7.2 Road Class Encoding

```python
from sklearn.preprocessing import OrdinalEncoder

# Ordinal encoding: motorway > trunk > primary > secondary (hierarchy)
road_class_order = [["secondary", "primary", "trunk", "motorway"]]
enc = OrdinalEncoder(categories=road_class_order)
df["road_class_ord"] = enc.fit_transform(df[["RoadClass"]])

# Or one-hot for tree models
df = pd.get_dummies(df, columns=["RoadClass", "LandUse"], drop_first=False)
```

### 7.3 Length-Weighted Metrics

```python
# Network-level KPIs (aggregate)
total_km = df["Shape_Length"].sum() / 1000
high_risk_km = df[df["is_speed_problem"] == 1]["Shape_Length"].sum() / 1000
print(f"Total network: {total_km:.0f} km")
print(f"High-risk sections: {high_risk_km:.0f} km ({high_risk_km/total_km*100:.1f}%)")

# Length-weighted average speed compliance
df["length_weighted_PercentOverLimit"] = (
    df["PercentOverLimit"] * df["Shape_Length"]
)
lw_compliance = df["length_weighted_PercentOverLimit"].sum() / df["Shape_Length"].sum()
print(f"Network-avg PercentOverLimit (length-weighted): {lw_compliance:.3f}")
```

### 7.4 Spatial Features (Optional / Advanced)

```python
# Road section centroid lat/lon (for spatial ML)
df["centroid_lat"] = df_geo.geometry.centroid.y
df["centroid_lon"] = df_geo.geometry.centroid.x

# Distance to nearest urban centre (requires urban boundary shapefile)
# spatial join / nearest geometry operations with geopandas

# Sinuosity: how curved is the road? (proxy for geometry risk)
# sinuosity = arc_length / straight_line_distance
from shapely.geometry import LineString
def sinuosity(geom):
    if geom is None or geom.is_empty:
        return np.nan
    coords = list(geom.coords)
    if len(coords) < 2:
        return 1.0
    straight = LineString([coords[0], coords[-1]]).length
    return geom.length / straight if straight > 0 else 1.0

df["sinuosity"] = df_geo.geometry.apply(sinuosity)
```

---

## 8. Normalisation Strategy

Different features require different scaling strategies based on their distributions:

### 8.1 Choosing the Right Scaler

| Feature | Distribution | Recommended Scaler | Reason |
|---|---|---|---|
| `WeightedSample` | Highly right-skewed | Log → MinMaxScaler | Traffic follows power law |
| `Shape_Length` | Right-skewed | Log → StandardScaler | Long-tail road lengths |
| `MedianSpeed` | ~Normal (bounded) | StandardScaler | Relatively bell-shaped |
| `F85thPercentileSpeed` | ~Normal (bounded) | StandardScaler | — |
| `PercentOverLimit` | Bounded [0,1] | None or MinMaxScaler | Already normalised |
| `speed_excess_85` | Can be negative | StandardScaler | Signed, zero-centred |
| `RankedPercentile` | Uniform [0,100] | `/100` (manual) | Already rank-based |
| `SpeedLimit` | Discrete, bounded | MinMaxScaler | Ordinal-like |

```python
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.pipeline import Pipeline

STANDARD_SCALE_COLS = [
    "MedianSpeed", "F85thPercentileSpeed",
    "speed_excess_85", "speed_excess_median"
]
MINMAX_SCALE_COLS = ["SpeedLimit", "Shape_Length"]
LOG_THEN_STANDARD = ["WeightedSample", "SampleSize_avg"]
ALREADY_NORMALISED = ["PercentOverLimit", "Percentile", "RankedPercentile"]

# Log-transform before scaling
for col in LOG_THEN_STANDARD:
    df[f"log_{col}"] = np.log1p(df[col])

# Build feature matrix
feature_cols = (
    STANDARD_SCALE_COLS +
    MINMAX_SCALE_COLS +
    [f"log_{c}" for c in LOG_THEN_STANDARD] +
    ALREADY_NORMALISED +
    [c for c in df.columns if c.startswith("RoadClass_") or c.startswith("LandUse_")]
)

X = df[feature_cols].copy()

# Fit scalers
ss = StandardScaler()
mm = MinMaxScaler()

X[STANDARD_SCALE_COLS + [f"log_{c}" for c in LOG_THEN_STANDARD]] = ss.fit_transform(
    X[STANDARD_SCALE_COLS + [f"log_{c}" for c in LOG_THEN_STANDARD]]
)
X[MINMAX_SCALE_COLS] = mm.fit_transform(X[MINMAX_SCALE_COLS])

# Save scalers for inference
import joblib
joblib.dump(ss, "standard_scaler.pkl")
joblib.dump(mm, "minmax_scaler.pkl")
```

---

## 9. Full Preprocessing Pipeline (Code)

A single reproducible pipeline from raw file → model-ready features:

```python
# ══════════════════════════════════════════════════════════════════════
#  ADB AI4SaferRoads — Full Preprocessing Pipeline
#  Works for both Thailand and Maharashtra datasets
# ══════════════════════════════════════════════════════════════════════
import geopandas as gpd
import pandas as pd
import numpy as np
import joblib
from sklearn.preprocessing import StandardScaler, MinMaxScaler

# ── CONFIG ─────────────────────────────────────────────────────────────
CONFIG = {
    "MIN_SAMPLE_SIZE": 500,
    "SPEED_LIMIT_DEFAULTS": {
        "motorway": 110, "trunk": 90, "primary": 80, "secondary": 60
    },
    "DROP_COLS": [
        "RoadLength", "Percent_", "ForAnalysis", "SpeedLimitFloor",
        "NO_OF_Result_Segments", "ProvinceID", "PercentileBand"
    ],
    "OUTPUT_CRS": "EPSG:4326"
}

def load_dataset(filepath: str, region: str) -> gpd.GeoDataFrame:
    """Load and tag a regional dataset."""
    gdf = gpd.read_file(filepath)
    gdf["region"] = region
    print(f"  Loaded {region}: {len(gdf)} sections")
    return gdf

def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Filter, deduplicate, fix dtypes."""
    # Valid records only
    if "AnalysisStatus" in df.columns:
        df = df[df["AnalysisStatus"] == "Valid"].copy()

    # Drop useless columns
    drop = [c for c in CONFIG["DROP_COLS"] if c in df.columns]
    df.drop(columns=drop, inplace=True)

    # Sample size filter
    df = df[df["SampleSize_avg"] >= CONFIG["MIN_SAMPLE_SIZE"]].copy()

    # Fix string columns
    df["LandUse"] = df["LandUse"].str.upper().str.strip().fillna("RURAL")
    df["RoadClass"] = df["RoadClass"].str.lower().str.strip()

    # Fix speed limit
    mask = df["SpeedLimit"].isnull() | (df["SpeedLimit"] == 0)
    df.loc[mask, "SpeedLimit"] = df.loc[mask, "RoadClass"].map(
        CONFIG["SPEED_LIMIT_DEFAULTS"]
    )

    # Drop rows with no speed data
    df.dropna(subset=["MedianSpeed", "F85thPercentileSpeed", "PercentOverLimit"],
              inplace=True)

    # Clip PercentOverLimit to [0, 1]
    df["PercentOverLimit"] = df["PercentOverLimit"].clip(0, 1)

    return df.reset_index(drop=True)

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create derived risk metrics."""
    df["speed_excess_85"]     = df["F85thPercentileSpeed"] - df["SpeedLimit"]
    df["speed_excess_median"] = df["MedianSpeed"] - df["SpeedLimit"]
    df["p85_compliance_ratio"] = df["F85thPercentileSpeed"] / df["SpeedLimit"]
    df["median_compliance_ratio"] = df["MedianSpeed"] / df["SpeedLimit"]

    df["log_weighted_sample"] = np.log1p(df["WeightedSample"])
    df["log_sample_size"]     = np.log1p(df["SampleSize_avg"])

    df["speed_risk_index"]  = (
        df["PercentOverLimit"] *
        np.maximum(df["speed_excess_85"], 0) / df["SpeedLimit"].replace(0, np.nan)
    )
    df["exposure_risk"]     = df["RankedPercentile"] / 100 * df["speed_risk_index"]
    df["urban_flag"]        = (df["LandUse"] == "URBAN").astype(int)
    df["urban_weighted_risk"] = df["exposure_risk"] * (1 + 0.5 * df["urban_flag"])

    df["is_speed_problem"]  = (
        (df["PercentOverLimit"] > 0.5) |
        (df["speed_excess_85"] > 20)
    ).astype(int)

    return df

def encode_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    """One-hot encode road class and land use."""
    df = pd.get_dummies(df, columns=["RoadClass", "LandUse"], drop_first=False)
    return df

def normalise(df: pd.DataFrame, fit: bool = True) -> tuple:
    """Scale numerical features. Returns (df_scaled, scalers_dict)."""
    STANDARD = ["MedianSpeed", "F85thPercentileSpeed",
                "speed_excess_85", "speed_excess_median",
                "log_weighted_sample", "log_sample_size"]
    MINMAX   = ["SpeedLimit", "Shape_Length"]

    scalers = {}
    for cols, ScalerClass, key in [
        (STANDARD, StandardScaler, "standard"),
        (MINMAX,   MinMaxScaler,   "minmax")
    ]:
        available = [c for c in cols if c in df.columns]
        scaler = ScalerClass()
        df[available] = scaler.fit_transform(df[available]) if fit else scaler.transform(df[available])
        scalers[key] = scaler
        if fit:
            joblib.dump(scaler, f"{key}_scaler.pkl")

    return df, scalers

def run_pipeline(filepaths: dict, output_path: str = "processed_data.gpkg"):
    """End-to-end pipeline."""
    print("── Loading datasets ──────────────────────────────────")
    gdfs = [load_dataset(path, region) for region, path in filepaths.items()]
    
    print("── Merging ───────────────────────────────────────────")
    common_cols = list(set.intersection(*[set(g.columns) for g in gdfs]))
    gdf = pd.concat([g[common_cols] for g in gdfs], ignore_index=True)
    print(f"  Combined: {len(gdf)} sections")

    print("── Cleaning ──────────────────────────────────────────")
    gdf = clean(gdf)
    print(f"  After cleaning: {len(gdf)} sections")

    print("── Feature engineering ───────────────────────────────")
    gdf = engineer_features(gdf)

    print("── Encoding categoricals ─────────────────────────────")
    gdf = encode_categoricals(gdf)

    print("── Normalising ───────────────────────────────────────")
    gdf, scalers = normalise(gdf, fit=True)

    print(f"── Saving to {output_path} ───────────────────────────")
    if isinstance(gdf, gpd.GeoDataFrame):
        gdf.to_file(output_path, driver="GPKG")
    else:
        gdf.to_csv(output_path.replace(".gpkg", ".csv"), index=False)

    print(f"✓ Done. Final shape: {gdf.shape}")
    return gdf, scalers

# ── Run it ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    FILEPATHS = {
        "Thailand":    "ADB_Innovation_Thailand/thailand_road_safety.gpkg",
        "Maharashtra": "ADB_Innovation_Maharashtra/maharashtra_road_safety.gpkg",
    }
    df_final, scalers = run_pipeline(FILEPATHS, "processed_road_safety.gpkg")
```

---

## 10. Modelling Considerations

### 10.1 Task Framing

The challenge has multiple valid task framings:

| Framing | Target Variable | Model Type |
|---|---|---|
| **Risk Ranking** | `exposure_risk` (continuous) | Regression / Ranking |
| **Speed Non-Compliance** | `PercentOverLimit` (continuous) | Regression |
| **High-Risk Detection** | `is_speed_problem` (binary) | Classification |
| **Priority Corridor ID** | Top-K by `exposure_risk` | Ranking / Optimisation |
| **Speed Limit Appropriateness** | `speed_excess_85` > threshold | Classification |

### 10.2 Key Feature Groups for Modelling

```
Group A — Traffic Exposure
  log_weighted_sample, RankedPercentile

Group B — Speed Behaviour
  PercentOverLimit, speed_excess_85, p85_compliance_ratio

Group C — Road Characteristics
  RoadClass_*, Shape_Length, SpeedLimit

Group D — Context
  LandUse_*, urban_flag, region (if cross-dataset model)

Group E — Derived Risk
  speed_risk_index, exposure_risk (if not target)
```

### 10.3 Spatial Cross-Validation

**Do not use random train/test split** — adjacent road sections are spatially autocorrelated (nearby roads have similar traffic and speed profiles). Use:

```python
from sklearn.model_selection import GroupKFold

# Create spatial folds using grid cells or admin regions
# Rough grid-based grouping
df["lat_bin"] = pd.cut(df["centroid_lat"], bins=10, labels=False)
df["lon_bin"] = pd.cut(df["centroid_lon"], bins=10, labels=False)
df["spatial_fold"] = df["lat_bin"].astype(str) + "_" + df["lon_bin"].astype(str)

gkf = GroupKFold(n_splits=5)
for train_idx, val_idx in gkf.split(X, y, groups=df["spatial_fold"]):
    X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
    # ... fit model
```

### 10.4 Recommended Models

| Model | Strengths for This Data | Notes |
|---|---|---|
| **XGBoost / LightGBM** | Handles mixed types, robust to skew, fast | Good first baseline |
| **Random Forest** | Interpretable feature importance | Good for explainability |
| **Spatial Regression (GWR)** | Captures spatial non-stationarity | Geographically Weighted Regression |
| **Neural Network (MLP)** | Can learn complex risk patterns | Needs more data to shine |
| **KDE / DBSCAN clustering** | Identify spatial hotspot clusters | Unsupervised risk zones |

### 10.5 Evaluation Metrics

```python
# For regression (PercentOverLimit prediction)
from sklearn.metrics import mean_absolute_error, r2_score
mae = mean_absolute_error(y_true, y_pred)
r2  = r2_score(y_true, y_pred)

# For ranking (are the high-risk roads ranked highest?)
from scipy.stats import spearmanr
rho, p = spearmanr(y_true, y_pred)

# For classification (is_speed_problem)
from sklearn.metrics import classification_report, roc_auc_score
print(classification_report(y_true, y_pred_binary))
auc = roc_auc_score(y_true, y_pred_proba)

# Length-weighted MAE (prioritise accuracy on long, high-traffic roads)
weights = df["Shape_Length"] * df["RankedPercentile"] / 100
lw_mae = np.average(np.abs(y_true - y_pred), weights=weights)
```

---

## 11. Common Pitfalls & Gotchas

| Pitfall | Impact | Fix |
|---|---|---|
| Using `RoadLength` instead of `Shape_Length` | Wrong distance calculations | Always use `Shape_Length` |
| Treating `NumberOverLimit` as absolute traffic counts | Overstates risk on high-traffic roads | Use `PercentOverLimit` for compliance; use `WeightedSample` for volume |
| Not filtering `AnalysisStatus != "Valid"` | Includes QA-failed sections in analysis | Filter first, always |
| Random train/test split | Spatial data leakage | Use spatial cross-validation |
| Ignoring low `SampleSize_avg` sections | High noise in speed estimates | Reliability-weight your results |
| Treating `SpeedLimit` as ground truth | TomTom values are unvalidated; may be wrong | Flag outliers; consider imputing from road class |
| Comparing absolute `NumberOverLimit` across sections | Section lengths differ | Normalise by `Shape_Length` or use `PercentOverLimit` |
| Not log-transforming `WeightedSample` | Skewed feature distribution kills linear models | Always log-transform this field |
| Assuming `InvPercentile` = 1 - risk | It's `1 - Percentile` (traffic rank, not risk) | Don't confuse traffic rank with risk rank |
| Ignoring `urban_flag` when scoring | Urban speeding is more dangerous | Include urban context in risk scoring |

---

## 12. Attribution & Licensing

Any output using this data must include:

```
Data sources:
© OpenStreetMap contributors, Overture Maps Foundation (road network)
Traffic and speed data: TomTom Move API
Land use: NASA GRUMP (Global Rural-Urban Mapping Project)
Challenge data: Asian Development Bank (ADB) / Agilysis
```

The network data is licensed under ODbL. Any derivative works should comply with ODbL share-alike requirements when publishing outputs that embed the network geometry.

---

*Guide compiled by Shamique Khan — ADB AI for Safer Roads 2026 Challenge*  
*Data User Guide: Richard Owen – Agilysis, May 2026*

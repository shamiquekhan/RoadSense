#!/usr/bin/env python3
"""Compare random-split and spatial-split baselines for road safety risk.

This script is intentionally leakage-aware:
- Full feature set: includes speed-derived features used by the current baseline.
- Safe feature set: only transferable features that are less likely to encode the target.

It reports:
- random train/test split metrics
- Thailand -> Maharashtra metrics
- Maharashtra -> Thailand metrics

Outputs:
  - reports/baseline_comparison.csv
  - reports/baseline_comparison.html

Default target: PercentOverLimit (regression).
"""

from __future__ import annotations

from pathlib import Path
import argparse
import html
import warnings

import joblib
import numpy as np
import pandas as pd
import geopandas as gpd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


FULL_FEATURES = [
    "SpeedLimit",
    "MedianSpeed",
    "F85thPercentileSpeed",
    "WeightedSample",
    "SampleSize_avg",
    "Shape_Length",
    "RankedPercentile",
    "region",
]

SAFE_FEATURES = [
    "SpeedLimit",
    "WeightedSample",
    "SampleSize_avg",
    "Shape_Length",
    "region",
]


def ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_gdf(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return gpd.read_file(path)


def restore_original_units(df: pd.DataFrame, input_path: Path) -> pd.DataFrame:
    """Inverse-transform scaled columns using scalers saved beside the input gpkg, if available."""
    out = df.copy()
    parent = input_path.parent
    std_path = parent / "standard_scaler.pkl"
    mm_path = parent / "minmax_scaler.pkl"

    standard_cols = [
        c
        for c in [
            "MedianSpeed",
            "F85thPercentileSpeed",
            "speed_excess_85",
            "speed_excess_median",
            "log_weighted_sample",
            "log_sample_size",
        ]
        if c in out.columns
    ]
    minmax_cols = [c for c in ["SpeedLimit", "Shape_Length"] if c in out.columns]

    try:
        if std_path.exists() and standard_cols:
            ss = joblib.load(std_path)
            out[standard_cols] = ss.inverse_transform(out[standard_cols])
    except Exception as exc:
        warnings.warn(f"Could not inverse-transform standard-scaled columns: {exc}")

    try:
        if mm_path.exists() and minmax_cols:
            mm = joblib.load(mm_path)
            out[minmax_cols] = mm.inverse_transform(out[minmax_cols])
    except Exception as exc:
        warnings.warn(f"Could not inverse-transform min-max-scaled columns: {exc}")

    return out


def make_preprocessor(features: list[str]) -> ColumnTransformer:
    numeric_features = [c for c in features if c != "region"]
    transformers = [
        (
            "num",
            Pipeline(
                steps=[
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                ]
            ),
            numeric_features,
        )
    ]
    if "region" in features:
        transformers.append(
            (
                "cat",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                ["region"],
            )
        )

    return ColumnTransformer(transformers=transformers, remainder="drop")


def evaluate(y_true, y_pred) -> dict:
    return {
        "MAE": mean_absolute_error(y_true, y_pred),
        "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "R2": r2_score(y_true, y_pred),
    }


def fit_score(train_df: pd.DataFrame, test_df: pd.DataFrame, features: list[str], model_name: str) -> dict:
    X_train = train_df[features].copy()
    y_train = train_df["PercentOverLimit"].copy()
    X_test = test_df[features].copy()
    y_test = test_df["PercentOverLimit"].copy()

    if model_name == "LinearRegression":
        estimator = LinearRegression()
    elif model_name == "RandomForestRegressor":
        estimator = RandomForestRegressor(n_estimators=300, random_state=42, n_jobs=-1)
    else:
        raise ValueError(model_name)

    pipeline = Pipeline(steps=[("preprocess", make_preprocessor(features)), ("model", estimator)])
    pipeline.fit(X_train, y_train)
    preds = pipeline.predict(X_test)
    return evaluate(y_test, preds)


def compare_random_split(df: pd.DataFrame, features: list[str], model_name: str, random_state: int, test_size: float) -> dict:
    work = df.dropna(subset=["PercentOverLimit"] + features).copy()
    train_df, test_df = train_test_split(work, test_size=test_size, random_state=random_state)
    metrics = fit_score(train_df, test_df, features, model_name)
    return {
        "split": "random",
        "train_region": "mixed",
        "test_region": "mixed",
        "feature_set": "full" if features == FULL_FEATURES else "safe",
        "model": model_name,
        "n_train": len(train_df),
        "n_test": len(test_df),
        **metrics,
    }


def compare_spatial_split(df: pd.DataFrame, features: list[str], model_name: str, train_region: str, test_region: str) -> dict | None:
    train_df = df[df["region"].astype(str) == train_region].dropna(subset=["PercentOverLimit"] + features).copy()
    test_df = df[df["region"].astype(str) == test_region].dropna(subset=["PercentOverLimit"] + features).copy()
    if train_df.empty or test_df.empty:
        return None
    metrics = fit_score(train_df, test_df, features, model_name)
    return {
        "split": f"{train_region}_to_{test_region}",
        "train_region": train_region,
        "test_region": test_region,
        "feature_set": "full" if features == FULL_FEATURES else "safe",
        "model": model_name,
        "n_train": len(train_df),
        "n_test": len(test_df),
        **metrics,
    }


def build_report(report_path: Path, metrics_df: pd.DataFrame) -> None:
    ensure_dir(report_path)
    pieces = ["<html><head><meta charset='utf-8'><title>Baseline Comparison</title>"]
    pieces.append(
        "<style>body{font-family:Arial,sans-serif;max-width:1200px;margin:24px auto;line-height:1.45}"
        "table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #ccc;padding:6px 8px;text-align:left}"
        "th{background:#f3f4f6}</style></head><body>"
    )
    pieces.append("<h1>RoadSense Baseline Comparison</h1>")
    pieces.append("<p>Comparison of random-split and spatial-split performance for full vs safe feature sets.</p>")
    pieces.append(metrics_df.to_html(index=False, float_format=lambda x: f"{x:.4f}" if pd.notna(x) else ""))
    pieces.append("</body></html>")
    report_path.write_text("\n".join(pieces), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Compare baseline models under random and spatial splits")
    parser.add_argument("--input", type=Path, default=Path("RoadSense/outputs/processed_road_safety.gpkg"))
    parser.add_argument("--output", type=Path, default=Path("reports/baseline_comparison.csv"))
    parser.add_argument("--report", type=Path, default=Path("reports/baseline_comparison.html"))
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    gdf = load_gdf(args.input)
    df = restore_original_units(pd.DataFrame(gdf), args.input)

    if "region" not in df.columns:
        raise KeyError("Expected region column in processed dataset.")

    rows = []
    for feature_set in [FULL_FEATURES, SAFE_FEATURES]:
        for model_name in ["LinearRegression", "RandomForestRegressor"]:
            rows.append(compare_random_split(df, feature_set, model_name, args.random_state, args.test_size))
            for train_region, test_region in [("Thailand", "Maharashtra"), ("Maharashtra", "Thailand")]:
                result = compare_spatial_split(df, feature_set, model_name, train_region, test_region)
                if result is not None:
                    rows.append(result)

    metrics_df = pd.DataFrame(rows)
    ensure_dir(args.output)
    metrics_df.to_csv(args.output, index=False)
    build_report(args.report, metrics_df)

    print(f"Wrote comparison metrics to {args.output}")
    print(f"Wrote comparison report to {args.report}")


if __name__ == "__main__":
    main()

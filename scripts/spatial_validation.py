#!/usr/bin/env python3
"""Leakage audit and spatial validation for RoadSense baselines.

This script does two things:
1. Audits likely leakage/proxy features against `PercentOverLimit`.
2. Trains a regression baseline across geographic holdouts:
   - Train Thailand -> Test Maharashtra
   - Train Maharashtra -> Test Thailand

Outputs:
  - reports/leakage_audit.csv
  - reports/spatial_validation_metrics.csv
  - reports/spatial_validation_report.html

Usage:
  python scripts/spatial_validation.py \
    --input RoadSense/outputs/processed_road_safety.gpkg
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
]

SAFE_FEATURES = [
    "SpeedLimit",
    "WeightedSample",
    "SampleSize_avg",
    "Shape_Length",
]

LEAKAGE_CANDIDATES = [
    "RankedPercentile",
    "Percentile",
    "NumberOverLimit",
    "speed_excess_85",
    "speed_excess_median",
    "MedianSpeed",
    "F85thPercentileSpeed",
    "SpeedLimit",
    "WeightedSample",
    "SampleSize_avg",
    "Shape_Length",
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


def leakage_audit(df: pd.DataFrame, target_col: str = "PercentOverLimit") -> pd.DataFrame:
    if target_col not in df.columns:
        raise KeyError(f"Target column missing: {target_col}")

    rows = []
    target = df[target_col]
    for col in LEAKAGE_CANDIDATES:
        if col not in df.columns or col == target_col:
            continue
        series = df[col]
        numeric = pd.to_numeric(series, errors="coerce")
        corr = np.nan
        spearman = np.nan
        if numeric.notna().sum() > 2 and target.notna().sum() > 2:
            try:
                corr = float(target.corr(numeric))
            except Exception:
                corr = np.nan
            try:
                spearman = float(target.corr(numeric, method="spearman"))
            except Exception:
                spearman = np.nan

        name_suspect = any(
            token in col.lower()
            for token in ["percentile", "numberoverlimit", "speed_excess", "median", "f85th"]
        )
        corr_flag = bool(pd.notna(corr) and abs(corr) >= 0.5)
        rows.append(
            {
                "feature": col,
                "pearson_corr": corr,
                "spearman_corr": spearman,
                "name_suspect": name_suspect,
                "high_corr_flag": corr_flag,
                "audit_flag": name_suspect or corr_flag,
            }
        )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["audit_flag", "high_corr_flag", "pearson_corr"], ascending=[False, False, False])
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


def fit_and_score(train_df: pd.DataFrame, test_df: pd.DataFrame, features: list[str], model_name: str = "RandomForest") -> dict:
    X_train = train_df[features].copy()
    y_train = train_df["PercentOverLimit"].copy()
    X_test = test_df[features].copy()
    y_test = test_df["PercentOverLimit"].copy()

    if model_name == "LinearRegression":
        estimator = LinearRegression()
    else:
        estimator = RandomForestRegressor(n_estimators=300, random_state=42, n_jobs=-1)

    pipeline = Pipeline(steps=[("preprocess", make_preprocessor(features)), ("model", estimator)])
    pipeline.fit(X_train, y_train)
    preds = pipeline.predict(X_test)

    return evaluate(y_test, preds)


def build_report(report_path: Path, audit_df: pd.DataFrame, metrics_df: pd.DataFrame) -> None:
    ensure_dir(report_path)
    pieces = ["<html><head><meta charset='utf-8'><title>Spatial Validation Report</title>"]
    pieces.append(
        "<style>body{font-family:Arial,sans-serif;max-width:1200px;margin:24px auto;line-height:1.45}"
        "table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #ccc;padding:6px 8px;text-align:left}"
        "th{background:#f3f4f6}</style></head><body>"
    )
    pieces.append("<h1>Leakage Audit and Spatial Validation</h1>")
    pieces.append("<h2>Leakage audit</h2>")
    pieces.append(audit_df.to_html(index=False, float_format=lambda x: f"{x:.4f}" if pd.notna(x) else ""))
    pieces.append("<h2>Spatial validation metrics</h2>")
    pieces.append(metrics_df.to_html(index=False, float_format=lambda x: f"{x:.4f}" if pd.notna(x) else ""))
    pieces.append("</body></html>")
    report_path.write_text("\n".join(pieces), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Leakage audit and spatial validation for RoadSense")
    parser.add_argument("--input", type=Path, default=Path("RoadSense/outputs/processed_road_safety.gpkg"))
    parser.add_argument("--audit-path", type=Path, default=Path("reports/leakage_audit.csv"))
    parser.add_argument("--metrics-path", type=Path, default=Path("reports/spatial_validation_metrics.csv"))
    parser.add_argument("--report-path", type=Path, default=Path("reports/spatial_validation_report.html"))
    args = parser.parse_args()

    gdf = load_gdf(args.input)
    df = pd.DataFrame(gdf)
    df = restore_original_units(df, args.input)

    if "region" not in df.columns:
        raise KeyError("Expected a region column in the processed dataset.")

    audit_df = leakage_audit(df)
    ensure_dir(args.audit_path)
    audit_df.to_csv(args.audit_path, index=False)

    region_values = [r for r in df["region"].dropna().astype(str).unique().tolist()]
    if len(region_values) < 2:
        raise ValueError(f"Need at least two regions for spatial validation; found {region_values}")

    rows = []
    for train_region, test_region in [("Thailand", "Maharashtra"), ("Maharashtra", "Thailand")]:
        train_df = df[df["region"].astype(str) == train_region].copy()
        test_df = df[df["region"].astype(str) == test_region].copy()

        if train_df.empty or test_df.empty:
            continue

        for feature_set_name, features in [("full", FULL_FEATURES), ("safe", SAFE_FEATURES)]:
            # drop rows missing any of the chosen features for this evaluation
            train_eval = train_df.dropna(subset=["PercentOverLimit"] + features)
            test_eval = test_df.dropna(subset=["PercentOverLimit"] + features)
            if train_eval.empty or test_eval.empty:
                continue

            for model_name in ["LinearRegression", "RandomForestRegressor"]:
                metrics = fit_and_score(train_eval, test_eval, features, model_name=model_name)
                rows.append(
                    {
                        "train_region": train_region,
                        "test_region": test_region,
                        "feature_set": feature_set_name,
                        "model": model_name,
                        "n_train": len(train_eval),
                        "n_test": len(test_eval),
                        **metrics,
                    }
                )

    metrics_df = pd.DataFrame(rows)
    ensure_dir(args.metrics_path)
    metrics_df.to_csv(args.metrics_path, index=False)
    build_report(args.report_path, audit_df, metrics_df)

    print(f"Wrote leakage audit to {args.audit_path}")
    print(f"Wrote spatial metrics to {args.metrics_path}")
    print(f"Wrote spatial report to {args.report_path}")


if __name__ == "__main__":
    main()

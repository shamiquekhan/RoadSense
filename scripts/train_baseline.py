#!/usr/bin/env python3
"""Train a simple baseline model for road-safety risk.

Default task:
  regression target = PercentOverLimit

Optional task:
  classification target = (PercentOverLimit > threshold).astype(int)

Outputs:
  - models/baseline_model.pkl
  - reports/baseline_metrics.csv
  - reports/baseline_feature_importance.csv
  - reports/baseline_report.html

Examples:
  python scripts/train_baseline.py --input RoadSense/outputs/processed_road_safety.gpkg
  python scripts/train_baseline.py --task classification --threshold 0.2
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
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

FEATURES = [
    "SpeedLimit",
    "MedianSpeed",
    "F85thPercentileSpeed",
    "WeightedSample",
    "SampleSize_avg",
    "Shape_Length",
    "RankedPercentile",
    "region",
]

NUMERIC_FEATURES = [
    "SpeedLimit",
    "MedianSpeed",
    "F85thPercentileSpeed",
    "WeightedSample",
    "SampleSize_avg",
    "Shape_Length",
    "RankedPercentile",
]

CATEGORICAL_FEATURES = ["region"]


def ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_processed_data(path: Path) -> pd.DataFrame:
    gdf = gpd.read_file(path)
    df = pd.DataFrame(gdf)
    return df


def restore_original_units(df: pd.DataFrame, input_path: Path) -> pd.DataFrame:
    """Attempt to inverse-transform scaled numeric columns using saved scalers."""
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


def make_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                NUMERIC_FEATURES,
            ),
            (
                "cat",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                CATEGORICAL_FEATURES,
            ),
        ],
        remainder="drop",
    )


def build_models(task: str):
    models = []
    if task == "regression":
        models = [
            ("LinearRegression", LinearRegression()),
            (
                "RandomForestRegressor",
                RandomForestRegressor(n_estimators=300, random_state=42, n_jobs=-1),
            ),
            ("DummyRegressor", DummyRegressor(strategy="median")),
        ]
        try:
            from xgboost import XGBRegressor  # type: ignore

            models.insert(
                2,
                (
                    "XGBRegressor",
                    XGBRegressor(
                        n_estimators=300,
                        max_depth=5,
                        learning_rate=0.05,
                        subsample=0.8,
                        colsample_bytree=0.8,
                        reg_lambda=1.0,
                        random_state=42,
                        n_jobs=-1,
                    ),
                ),
            )
        except Exception:
            pass
    elif task == "classification":
        models = [
            ("LogisticRegression", LogisticRegression(max_iter=1000, n_jobs=-1)),
            (
                "RandomForestClassifier",
                RandomForestClassifier(n_estimators=300, random_state=42, n_jobs=-1),
            ),
            ("DummyClassifier", DummyClassifier(strategy="most_frequent")),
        ]
        try:
            from xgboost import XGBClassifier  # type: ignore

            models.insert(
                2,
                (
                    "XGBClassifier",
                    XGBClassifier(
                        n_estimators=300,
                        max_depth=5,
                        learning_rate=0.05,
                        subsample=0.8,
                        colsample_bytree=0.8,
                        reg_lambda=1.0,
                        random_state=42,
                        n_jobs=-1,
                        eval_metric="logloss",
                    ),
                ),
            )
        except Exception:
            pass
    else:
        raise ValueError(f"Unsupported task: {task}")

    return models


def evaluate_regression(y_true, y_pred) -> dict:
    return {
        "MAE": mean_absolute_error(y_true, y_pred),
        "RMSE": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "R2": r2_score(y_true, y_pred),
    }


def evaluate_classification(y_true, y_pred, y_score=None) -> dict:
    metrics = {
        "Accuracy": accuracy_score(y_true, y_pred),
        "Precision": precision_score(y_true, y_pred, zero_division=0),
        "Recall": recall_score(y_true, y_pred, zero_division=0),
        "F1": f1_score(y_true, y_pred, zero_division=0),
    }
    if y_score is not None:
        try:
            metrics["ROC_AUC"] = roc_auc_score(y_true, y_score)
        except Exception:
            metrics["ROC_AUC"] = np.nan
    else:
        metrics["ROC_AUC"] = np.nan
    return metrics


def choose_best_model(task: str, metrics_df: pd.DataFrame) -> str:
    if task == "regression":
        ranked = metrics_df.sort_values(
            ["RMSE", "MAE", "R2"], ascending=[True, True, False]
        )
    else:
        ranked = metrics_df.sort_values(
            ["F1", "ROC_AUC", "Accuracy"], ascending=[False, False, False]
        )
    return ranked.iloc[0]["model"]


def extract_positive_scores(model, X):
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X)
        if proba.ndim == 2 and proba.shape[1] > 1:
            return proba[:, 1]
    if hasattr(model, "decision_function"):
        scores = model.decision_function(X)
        return scores
    return None


def build_report(
    report_path: Path,
    task: str,
    metrics_df: pd.DataFrame,
    best_model_name: str,
    best_metrics: dict,
    feat_imp: pd.DataFrame,
):
    report_path.parent.mkdir(parents=True, exist_ok=True)
    sections = []
    sections.append(
        "<html><head><meta charset='utf-8'><title>RoadSense Baseline Report</title>"
    )
    sections.append(
        "<style>body{font-family:Arial,sans-serif;max-width:1100px;margin:24px auto;line-height:1.45}"
        "table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #ccc;padding:6px 8px;text-align:left}"
        "th{background:#f3f4f6}</style></head><body>"
    )
    sections.append(
        f"<h1>RoadSense Baseline Model Report</h1><p>Task: <strong>{html.escape(task)}</strong></p>"
    )
    sections.append(f"<h2>Best model</h2><p>{html.escape(best_model_name)}</p>")
    sections.append("<h2>Model comparison</h2>")
    sections.append(
        metrics_df.to_html(
            index=False, float_format=lambda x: f"{x:.4f}" if pd.notna(x) else ""
        )
    )
    sections.append("<h2>Best model metrics</h2>")
    sections.append(
        pd.DataFrame([best_metrics]).to_html(
            index=False, float_format=lambda x: f"{x:.4f}" if pd.notna(x) else ""
        )
    )
    sections.append("<h2>Permutation importance</h2>")
    sections.append(
        feat_imp.to_html(
            index=False, float_format=lambda x: f"{x:.6f}" if pd.notna(x) else ""
        )
    )
    sections.append("</body></html>")
    report_path.write_text("\n".join(sections), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Train a baseline model for road safety risk"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("RoadSense/outputs/processed_road_safety.gpkg"),
    )
    parser.add_argument(
        "--task", choices=["regression", "classification"], default="regression"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.20,
        help="Threshold for binary classification task",
    )
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument(
        "--model-path", type=Path, default=Path("models/baseline_model.pkl")
    )
    parser.add_argument(
        "--metrics-path", type=Path, default=Path("reports/baseline_metrics.csv")
    )
    parser.add_argument(
        "--importance-path",
        type=Path,
        default=Path("reports/baseline_feature_importance.csv"),
    )
    parser.add_argument(
        "--report-path", type=Path, default=Path("reports/baseline_report.html")
    )
    args = parser.parse_args()

    df = load_processed_data(args.input)
    df = restore_original_units(df, args.input)

    required = FEATURES + ["PercentOverLimit"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Missing required columns: {missing}")

    work = df[FEATURES + ["PercentOverLimit"]].copy()
    work = work.dropna(subset=["PercentOverLimit"])
    work = work.dropna(subset=FEATURES, how="all")

    # For classification, derive binary target.
    if args.task == "classification":
        work["target"] = (work["PercentOverLimit"] > args.threshold).astype(int)
    else:
        work["target"] = work["PercentOverLimit"].astype(float)

    X = work[FEATURES].copy()
    y = work["target"].copy()

    # Clean string columns for modeling.
    if "region" in X.columns:
        X["region"] = X["region"].astype(str).str.strip()

    if args.task == "classification":
        split_target = y
    else:
        split_target = df.loc[work.index, "region"] if "region" in df.columns else None

    if split_target is not None:
        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=args.test_size,
            random_state=args.random_state,
            stratify=split_target,
        )
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=args.test_size,
            random_state=args.random_state,
        )

    models = build_models(args.task)
    preprocessor = make_preprocessor()

    rows = []
    fitted = {}

    for name, estimator in models:
        pipeline = Pipeline(steps=[("preprocess", preprocessor), ("model", estimator)])
        pipeline.fit(X_train, y_train)
        preds = pipeline.predict(X_test)

        if args.task == "regression":
            metrics = evaluate_regression(y_test, preds)
            rows.append({"model": name, **metrics})
        else:
            scores = extract_positive_scores(pipeline, X_test)
            metrics = evaluate_classification(y_test, preds, scores)
            rows.append({"model": name, **metrics})

        fitted[name] = pipeline

    metrics_df = pd.DataFrame(rows)
    best_model_name = choose_best_model(args.task, metrics_df)
    best_model = fitted[best_model_name]

    # Permutation importance on the holdout set.
    imp = permutation_importance(
        best_model,
        X_test,
        y_test,
        n_repeats=10,
        random_state=args.random_state,
        scoring="r2" if args.task == "regression" else "f1",
        n_jobs=-1,
    )
    feat_imp = pd.DataFrame(
        {
            "feature": X_test.columns,
            "importance_mean": imp.importances_mean,
            "importance_std": imp.importances_std,
        }
    ).sort_values("importance_mean", ascending=False)

    # Save outputs.
    ensure_dir(args.model_path)
    ensure_dir(args.metrics_path)
    ensure_dir(args.importance_path)
    ensure_dir(args.report_path)

    joblib.dump(best_model, args.model_path)
    metrics_df.to_csv(args.metrics_path, index=False)
    feat_imp.to_csv(args.importance_path, index=False)

    best_row = metrics_df.loc[metrics_df["model"] == best_model_name].iloc[0].to_dict()
    build_report(
        args.report_path,
        args.task,
        metrics_df,
        best_model_name,
        best_row,
        feat_imp.head(20),
    )

    print(f"Best model: {best_model_name}")
    print(f"Saved model to: {args.model_path}")
    print(f"Saved metrics to: {args.metrics_path}")
    print(f"Saved feature importance to: {args.importance_path}")
    print(f"Saved report to: {args.report_path}")


if __name__ == "__main__":
    main()

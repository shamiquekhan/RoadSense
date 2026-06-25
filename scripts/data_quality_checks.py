#!/usr/bin/env python3
"""Data quality checks for processed road safety dataset.

Produces:
 - reports/qa_summary.html  : HTML summary of checks
 - reports/flagged_rows.csv : rows flagged with one or more failing checks

Usage:
  python scripts/data_quality_checks.py --input RoadSense/outputs/processed_road_safety.gpkg \
      --report reports/qa_summary.html --flags reports/flagged_rows.csv
"""

from pathlib import Path
import argparse
import geopandas as gpd
import pandas as pd
import numpy as np
import html


def ensure_outdir(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    return p.parent


def load_gdf(path: Path):
    if not path.exists():
        raise FileNotFoundError(path)
    return gpd.read_file(path)


def run_checks(gdf: gpd.GeoDataFrame, df_vals: pd.DataFrame = None) -> pd.DataFrame:
    """Run checks using `df_vals` for numeric values. If `df_vals` is None, use gdf copy."""
    df = gdf.copy()
    if df_vals is None:
        df_vals = df.copy()

    # Attempt to inverse-transform scaled columns if scalers are present
    try:
        import joblib

        scalers_path = (
            Path(gdf.source) if hasattr(gdf, "source") and gdf.source else None
        )
    except Exception:
        scalers_path = None

    # Fallback: look for scalers in the same folder as input file (parent of gdf if available)
    if scalers_path is None:
        scalers_path = None

    # Try parent directory of file if available via _metadata
    try:
        parent_dir = Path(gdf.__geo_interface__.get("id", ""))
    except Exception:
        parent_dir = None

    # We will look at common locations: 'outputs' directory next to gpkg
    # But we don't have the input path here; the caller can pass it if needed. Skip if not found.

    checks = {}

    # SpeedLimit: >0 and <200
    if "SpeedLimit" in df_vals.columns:
        checks["speedlimit_valid"] = df_vals["SpeedLimit"].apply(
            lambda v: pd.notna(v) and (v > 0) and (v < 200)
        )
    else:
        checks["speedlimit_valid"] = pd.Series([False] * len(df))

    # MedianSpeed > 0
    if "MedianSpeed" in df_vals.columns:
        checks["median_positive"] = df_vals["MedianSpeed"].apply(
            lambda v: pd.notna(v) and (v > 0)
        )
    else:
        checks["median_positive"] = pd.Series([False] * len(df))

    # F85thPercentileSpeed >= MedianSpeed
    if "F85thPercentileSpeed" in df_vals.columns and "MedianSpeed" in df_vals.columns:
        checks["p85_ge_median"] = df_vals["F85thPercentileSpeed"].fillna(
            -np.inf
        ) >= df_vals["MedianSpeed"].fillna(np.inf)
    else:
        checks["p85_ge_median"] = pd.Series([False] * len(df))

    # PercentOverLimit in [0,1]
    if "PercentOverLimit" in df_vals.columns:
        checks["percent_overlimit_ok"] = df_vals["PercentOverLimit"].apply(
            lambda v: pd.notna(v) and (v >= 0) and (v <= 1)
        )
    else:
        checks["percent_overlimit_ok"] = pd.Series([False] * len(df))

    # WeightedSample > 0
    if "WeightedSample" in df_vals.columns:
        checks["weighted_sample_positive"] = df_vals["WeightedSample"].apply(
            lambda v: pd.notna(v) and (v > 0)
        )
    else:
        checks["weighted_sample_positive"] = pd.Series([False] * len(df))

    # geometry not null
    checks["geometry_not_null"] = df.geometry.notnull()

    # duplicate rows (full row duplicates) -> pass if NOT duplicated
    checks["is_duplicate_row"] = ~df.duplicated(keep=False)

    # duplicate geometry (same WKT or equal geometry) -> pass if NOT duplicated
    try:
        geom_wkt = df.geometry.apply(lambda g: g.wkt if g is not None else None)
        checks["duplicate_geometry"] = ~geom_wkt.duplicated(keep=False)
    except Exception:
        checks["duplicate_geometry"] = pd.Series([False] * len(df))

    # invalid geometries or non-LineString types
    def geom_valid_line(g):
        try:
            if g is None:
                return False
            if not g.is_valid:
                return False
            if g.geom_type not in ("LineString", "MultiLineString"):
                return False
            return True
        except Exception:
            return False

    checks["geom_valid_linestring"] = df.geometry.apply(geom_valid_line)

    checks_df = pd.DataFrame(checks, index=df.index)
    return checks_df


def summarize_checks(checks_df: pd.DataFrame) -> pd.DataFrame:
    # For boolean checks, compute counts and fractions
    summary = []
    total = len(checks_df)
    for col in checks_df.columns:
        n_ok = int(checks_df[col].sum())
        summary.append(
            {
                "check": col,
                "ok_count": n_ok,
                "ok_frac": n_ok / total if total else 0,
                "total": total,
            }
        )
    return pd.DataFrame(summary)


def write_report(
    report_path: Path,
    summary_df: pd.DataFrame,
    checks_df: pd.DataFrame,
    gdf: gpd.GeoDataFrame,
    flagged_csv: Path,
):
    ensure_outdir(report_path)
    # flagged rows
    flagged_idx = checks_df.index[~checks_df.all(axis=1)]
    flagged = gdf.loc[flagged_idx].copy()
    # attach failing checks as a column
    fail_reasons = []
    for i in flagged_idx:
        falses = checks_df.loc[i][~checks_df.loc[i]].index.tolist()
        fail_reasons.append(";".join(falses))
    if not flagged.empty:
        flagged = flagged.assign(fail_reasons=fail_reasons)
        # save flagged rows as CSV (geometry as WKT for portability)
        flagged_copy = flagged.copy()
        flagged_copy["geometry"] = flagged_copy.geometry.apply(
            lambda g: g.wkt if g is not None else ""
        )
        flagged_copy.to_csv(flagged_csv, index=False)
    else:
        # empty CSV with columns
        pd.DataFrame().to_csv(flagged_csv, index=False)

    # build HTML report
    pieces = [
        "<html><head><meta charset='utf-8'><title>QA Summary</title></head><body>"
    ]
    pieces.append("<h1>Data Quality Checks — Summary</h1>")
    pieces.append("<h2>Overall</h2>")
    pieces.append(f"<p>Total rows: {len(gdf)}</p>")
    pieces.append("<h2>Checks summary</h2>")
    pieces.append(summary_df.to_html(index=False))
    pieces.append("<h2>Flagged rows sample (first 20)</h2>")
    if not flagged.empty:
        sample_html = flagged.head(20).copy()
        sample_html["geometry"] = sample_html.geometry.apply(
            lambda g: g.wkt if g is not None else ""
        )
        pieces.append(sample_html.to_html(index=False))
    else:
        pieces.append("<p>No flagged rows — all checks passed.</p>")

    pieces.append(f"<p>Flagged rows CSV: {html.escape(str(flagged_csv))}</p>")
    pieces.append("</body></html>")

    report_path.write_text("\n".join(pieces), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(
        description="Run data quality checks on processed road safety data"
    )
    p.add_argument(
        "--input",
        type=Path,
        default=Path("RoadSense/outputs/processed_road_safety.gpkg"),
    )
    p.add_argument("--report", type=Path, default=Path("reports/qa_summary.html"))
    p.add_argument("--flags", type=Path, default=Path("reports/flagged_rows.csv"))
    args = p.parse_args()

    gdf = load_gdf(args.input)

    # Try to load saved scalers (standard/minmax) from the same parent folder as the input
    parent = args.input.parent
    df_vals = gdf.copy()
    try:
        import joblib

        std_path = parent / "standard_scaler.pkl"
        mm_path = parent / "minmax_scaler.pkl"
        # Apply inverse transforms if scalers exist
        if std_path.exists() or mm_path.exists():
            # make a copy for inverse-transform
            df_vals = gdf.copy()
            # standard cols
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
                if c in df_vals.columns
            ]
            minmax_cols = [
                c for c in ["SpeedLimit", "Shape_Length"] if c in df_vals.columns
            ]
            if std_path.exists() and standard_cols:
                ss = joblib.load(std_path)
                try:
                    df_vals[standard_cols] = ss.inverse_transform(
                        df_vals[standard_cols]
                    )
                except Exception:
                    pass
            if mm_path.exists() and minmax_cols:
                mm = joblib.load(mm_path)
                try:
                    df_vals[minmax_cols] = mm.inverse_transform(df_vals[minmax_cols])
                except Exception:
                    pass
    except Exception:
        df_vals = gdf.copy()

    checks_df = run_checks(gdf, df_vals=df_vals)
    summary_df = summarize_checks(checks_df)
    write_report(args.report, summary_df, checks_df, gdf, args.flags)
    print("QA report written to", args.report)
    print("Flagged rows CSV written to", args.flags)


if __name__ == "__main__":
    main()

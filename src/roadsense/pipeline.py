"""Pipeline orchestration: load → score → export → map."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from loguru import logger
from scipy.spatial import cKDTree

from roadsense.config import (
    RAW_DATA_DIR,
    OUTPUT_DIR,
)
from roadsense.data.loader import load_and_clean, map_to_roadsense_schema
from roadsense.evaluation.metrics import (
    correlation_matrix,
    sensitivity_analysis,
    morans_i,
)
from roadsense.scoring import (
    score_dataframe_4component,
    score_dataframe_roadsense,
    compute_reliability_tier,
)
from roadsense.visualisation.map import create_interactive_map


def add_centroids(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add centroid lat/lon in WGS84."""
    if isinstance(df, gpd.GeoDataFrame) and df.crs:
        geo = df.to_crs("EPSG:3857")
        centroid = geo.geometry.centroid
        df["centroid_lat"] = centroid.y
        df["centroid_lon"] = centroid.x
    return df


def add_log_features(df: pd.DataFrame) -> pd.DataFrame:
    """Log-transform skewed traffic features."""
    if "WeightedSample" in df.columns:
        df["log_weighted_sample"] = np.log1p(df["WeightedSample"])
    if "SampleSize_avg" in df.columns:
        df["log_sample_size"] = np.log1p(df["SampleSize_avg"])
    return df


def impute_low_sample_scores(
    df: gpd.GeoDataFrame,
    score_cols: list[str] | None = None,
    sample_col: str | None = None,
    threshold: int = 1000,
    n_neighbors: int = 8,
) -> gpd.GeoDataFrame:
    """Impute scores for low-sample segments via spatial interpolation.

    For segments with sample size < threshold, replaces scores with a
    distance-weighted average of the nearest high-sample neighbors sharing
    the same RoadClass and LandUse. Neighbor weights combine:
      - inverse squared distance (spatial proximity)
      - sample size (data quality)

    Creates shadow columns prefixed with ``imputed_`` so original values
    are preserved. Returns a copy to avoid mutating the caller's frame.
    """
    df = df.copy()

    if sample_col is None:
        for candidate in ["SampleSize_avg", "obs_count", "sample_size"]:
            if candidate in df.columns:
                sample_col = candidate
                break
    if sample_col is None or sample_col not in df.columns:
        logger.info("  Imputation: no sample-size column found — skipping")
        return df
    mask = df[sample_col] < threshold
    low_n = mask.sum()
    if low_n == 0:
        logger.info(f"  Imputation: 0 low-sample segments (threshold={threshold})")
        return df

    if score_cols is None:
        score_cols = [
            c
            for c in [
                "speed_safety_score",
                "vru_risk_score",
                "limit_gap",
                "operating_gap",
                "SSS",
                "A_score",
                "B_score",
                "C_score",
            ]
            if c in df.columns
        ]

    # Reproject to Web Mercator for distance-based neighbour search
    if df.crs is None or df.crs.is_geographic:
        geo = df.to_crs("EPSG:3857")
    else:
        geo = df

    coords = np.column_stack(
        [
            geo.geometry.centroid.x.values,
            geo.geometry.centroid.y.values,
        ]
    )
    high_mask = ~mask
    low_idx = np.where(mask)[0]

    high_sample = df[sample_col].values.astype(float)

    # Map column names — handle both ADB and RoadSense schemas
    rc_col = "RoadClass" if "RoadClass" in df.columns else "functional_class"
    lu_col = "LandUse" if "LandUse" in df.columns else "urban_rural"

    imputed_count = 0
    for i in low_idx:
        # Restrict to neighbours with same road class + land use
        same_class = (df[rc_col].values == df[rc_col].values[i]) & (
            df[lu_col].values == df[lu_col].values[i]
        )
        candidates = high_mask & same_class
        cand_idx = np.where(candidates)[0]
        if len(cand_idx) == 0:
            continue

        # Query KDTree for closest neighbours among candidates
        k = min(n_neighbors, len(cand_idx))
        # Build a sub-tree from candidate indices
        sub_coords = coords[cand_idx]
        sub_tree = cKDTree(sub_coords)
        dists, nn_local = sub_tree.query(coords[i].reshape(1, -1), k=k)
        dists = dists.flatten()
        nn_local = nn_local.flatten()
        nn_global = cand_idx[nn_local]

        # Avoid zero-division: any zero-distance neighbours get full weight
        eps = 1e-6
        inv_dist2 = 1.0 / (dists**2 + eps)
        weights = inv_dist2 * high_sample[nn_global]
        weight_sum = weights.sum()
        if weight_sum == 0:
            continue

        for col in score_cols:
            if col not in df.columns:
                continue
            vals = df[col].values[nn_global]
            # Skip NaN neighbours
            valid = ~np.isnan(vals)
            if not valid.any():
                continue
            w = weights[valid]
            w = w / w.sum()
            imputed_val = np.average(vals[valid], weights=w)
            df.at[df.index[i], f"imputed_{col}"] = imputed_val
        imputed_count += 1

    logger.info(
        f"  Imputation: {imputed_count}/{low_n} low-sample segments imputed (threshold={threshold})"
    )
    return df


def print_kpis_4component(df: pd.DataFrame) -> None:
    """Print network KPIs for 4-component scoring output."""
    total_km = df["Shape_Length"].sum() / 1000
    print("\n── Network KPIs (4-Component) ─────────────────────────")
    for label in [
        "Critical — Immediate Review",
        "High — Priority Review",
        "Moderate — Scheduled Review",
        "Low — Monitor",
    ]:
        mask = df["priority_class"] == label
        km = df.loc[mask, "Shape_Length"].sum() / 1000
        pct = km / total_km * 100 if total_km > 0 else 0
        print(f"  {label:35s}: {km:7.0f} km  ({pct:4.1f}%)")
    print(f"\n  Mean Score: {df['speed_safety_score'].mean():.3f}")
    print(f"  Above Safe System limit: {(df['limit_gap'] > 0).mean()*100:.1f}%")
    print(f"  Traffic exceeds Safe System: {(df['operating_gap'] > 0).mean()*100:.1f}%")


def print_kpis_roadsense(df: pd.DataFrame) -> None:
    """Print network KPIs for 3-module scoring output."""
    total_km = df["length_m"].sum() / 1000 if "length_m" in df.columns else 0
    print("\n── Network KPIs (RoadSense 3-Module) ─────────────────")
    for tier in [
        "Critical — Immediate Review",
        "High — Priority Review",
        "Moderate — Scheduled Review",
        "Low — Monitor",
    ]:
        mask = df["risk_tier"] == tier
        km = df.loc[mask, "length_m"].sum() / 1000 if "length_m" in df.columns else 0
        pct = km / total_km * 100 if total_km > 0 else 0
        print(f"  {tier:35s}: {km:7.0f} km  ({pct:4.1f}%)")
    print(f"\n  Mean SSS: {df['SSS'].mean():.3f}")


def run_pipeline_4component(
    data_dir: str | Path = RAW_DATA_DIR,
    out_dir: str | Path = OUTPUT_DIR,
    weights: dict[str, float] | None = None,
    impute_low_sample: bool = False,
    use_sample: bool = False,
) -> gpd.GeoDataFrame:
    """Single-shot 4-component pipeline."""
    logger.info("── 4-Component Pipeline ───────────────────────────")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_and_clean(data_dir, use_sample=use_sample)
    df = score_dataframe_4component(df, weights=weights)

    # Reliability tier (data quality signal — not a scoring input)
    ss_col = "SampleSize_avg"
    if ss_col in df.columns:
        tier_results = df[ss_col].apply(compute_reliability_tier).tolist()
        df["reliability_tier"] = [r[0] for r in tier_results]
        df["reliability_colour"] = [r[1] for r in tier_results]

    if impute_low_sample:
        score_cols = [
            c
            for c in [
                "speed_safety_score",
                "vru_risk_score",
                "limit_gap",
                "operating_gap",
            ]
            if c in df.columns
        ]
        df = impute_low_sample_scores(df, score_cols=score_cols)
        imputed_col = f"imputed_{score_cols[0]}" if score_cols else None
        if imputed_col and imputed_col in df.columns:
            df["reliability_tier"] = df["reliability_tier"].where(
                df[imputed_col].isna(), df["reliability_tier"] + " (imputed)"
            )

    df = add_centroids(df)
    df = add_log_features(df)
    print_kpis_4component(df)

    _export(df, out_dir, prefix="speed_safety_scores")
    _save_evaluation(df, out_dir, prefix="speed_safety_scores")
    return df


def run_pipeline_roadsense(
    data_dir: str | Path = RAW_DATA_DIR,
    out_dir: str | Path = OUTPUT_DIR,
    module_weights: dict[str, float] | None = None,
    impute_low_sample: bool = False,
    use_sample: bool = False,
) -> gpd.GeoDataFrame:
    """Single-shot 3-module RoadSense pipeline."""
    logger.info("── RoadSense 3-Module Pipeline ────────────────────")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_and_clean(data_dir, use_sample=use_sample)
    df = map_to_roadsense_schema(df)
    df = score_dataframe_roadsense(df, module_weights=module_weights)

    # Reliability tier (data quality signal — not a scoring input)
    ss_col = "SampleSize_avg" if "SampleSize_avg" in df.columns else "obs_count"
    if ss_col in df.columns:
        tier_results = df[ss_col].apply(compute_reliability_tier).tolist()
        df["reliability_tier"] = [r[0] for r in tier_results]
        df["reliability_colour"] = [r[1] for r in tier_results]

    if impute_low_sample:
        score_cols = [
            c for c in ["SSS", "A_score", "B_score", "C_score"] if c in df.columns
        ]
        df = impute_low_sample_scores(df, score_cols=score_cols)
        imputed_col = f"imputed_{score_cols[0]}" if score_cols else None
        if imputed_col and imputed_col in df.columns:
            df["reliability_tier"] = df["reliability_tier"].where(
                df[imputed_col].isna(), df["reliability_tier"] + " (imputed)"
            )

    df = add_centroids(df)
    print_kpis_roadsense(df)

    _export(df, out_dir, prefix="roadsense_scores")
    _save_evaluation(df, out_dir, prefix="roadsense_scores")
    return df


def _export(df: gpd.GeoDataFrame, out_dir: Path, prefix: str) -> None:
    """Save outputs in multiple formats."""
    cols_for_csv = [c for c in df.columns if c != "geometry"]
    csv_path = out_dir / f"{prefix}.csv"
    df[cols_for_csv].to_csv(csv_path, index=False)
    logger.info(f"  CSV: {csv_path}")

    if isinstance(df, gpd.GeoDataFrame):
        gpkg_path = out_dir / f"{prefix}.gpkg"
        df.to_file(gpkg_path, driver="GPKG")
        logger.info(f"  GPKG: {gpkg_path}")

        # Lighter GeoJSON for web
        speed_col = "SpeedLimit" if "SpeedLimit" in df.columns else "posted_limit"
        f85_col = (
            "F85thPercentileSpeed" if "F85thPercentileSpeed" in df.columns else "v85"
        )
        safe_col = (
            "safe_system_limit"
            if "safe_system_limit" in df.columns
            else "safe_system_ref"
        )

        viz_cols = [
            "geometry",
            "road_name",
            "segment_id",
            speed_col,
            f85_col,
            "PercentOverLimit",
            safe_col,
            "limit_gap",
            "operating_gap",
            "speed_safety_score",
            "priority_class",
            "score_explanation",
            "region",
            "vru_risk_score",
            "centroid_lat",
            "centroid_lon",
            "functional_class",
            "urban_rural",
            "A_score",
            "B_score",
            "C_score",
            "SSS",
            "risk_tier",
            "reliability_tier",
            "reliability_colour",
            "Shape_Length",
            "length_m",
        ]
        viz_avail = [c for c in viz_cols if c in df.columns]
        geojson_path = out_dir / f"{prefix}.geojson"
        df[viz_avail].to_file(geojson_path, driver="GeoJSON")
        logger.info(f"  GeoJSON: {geojson_path}")

    # Map
    try:
        geojson = out_dir / f"{prefix}.geojson"
        if geojson.exists():
            map_path = out_dir / f"{prefix}_map.html"
            create_interactive_map(str(geojson), str(map_path))
    except Exception as exc:
        logger.warning(f"Map generation skipped: {exc}")

    # Generate summary KPIs
    kpi_path = out_dir / f"{prefix}_kpis.csv"
    try:
        summary = (
            df.groupby(["region", "RoadClass", "LandUse", "priority_class"])
            .agg(
                section_count=(
                    ("speed_safety_score", "count")
                    if "speed_safety_score" in df.columns
                    else ("SSS", "count")
                ),
                total_length_km=(
                    ("Shape_Length", lambda x: x.sum() / 1000)
                    if "Shape_Length" in df.columns
                    else ("length_m", lambda x: x.sum() / 1000)
                ),
                mean_score=(
                    ("speed_safety_score", "mean")
                    if "speed_safety_score" in df.columns
                    else ("SSS", "mean")
                ),
            )
            .round(2)
            .reset_index()
        )
        summary.to_csv(kpi_path, index=False)
    except Exception:
        pass  # KPI export is best-effort


def _save_evaluation(df: gpd.GeoDataFrame, out_dir: Path, prefix: str) -> None:
    """Compute and save evaluation diagnostics to JSON."""
    import json

    eval_path = out_dir / f"{prefix}_evaluation.json"

    ev = df.copy()
    if not {"A_score", "B_score", "C_score", "SSS"}.issubset(ev.columns):
        if "speed_safety_score" in ev.columns:
            ev["SSS"] = ev["speed_safety_score"]
        if "vru_risk_score" in ev.columns:
            ev["B_score"] = ev["vru_risk_score"]
        if "priority_class" in ev.columns:
            ev["risk_tier"] = ev["priority_class"]
        if "segment_id" not in ev.columns:
            ev["segment_id"] = ev.get("OBJECTID", ev.index)

    try:
        results: dict[str, object] = {
            "correlation_matrix": correlation_matrix(ev).to_dict(),
            "morans_i": morans_i(ev),
            "sensitivity": {},
        }
        sens = sensitivity_analysis(ev)
        if "error" not in sens:
            results["sensitivity"] = sens
        else:
            results["sensitivity_note"] = sens["error"]

        if "segment_id" in ev.columns:
            score_col = "SSS" if "SSS" in ev.columns else "speed_safety_score"
            tier_col = "risk_tier" if "risk_tier" in ev.columns else "priority_class"
            if score_col in ev.columns and tier_col in ev.columns:
                total = len(ev)
                for tier in ["Critical", "High", "Moderate", "Low"]:
                    n = (ev[tier_col].str.contains(tier, na=False)).sum()
                    pct = n / total * 100 if total else 0
                    length_col = (
                        "Shape_Length" if "Shape_Length" in ev.columns else "length_m"
                    )
                    km = (
                        ev.loc[
                            ev[tier_col].str.contains(tier, na=False), length_col
                        ].sum()
                        / 1000
                        if length_col in ev.columns
                        else 0
                    )
                    results.setdefault("tier_summary", {})[tier] = {
                        "count": int(n),
                        "pct": round(pct, 1),
                        "km": round(float(km), 1),
                    }

        eval_path.write_text(
            json.dumps(results, indent=2, default=str), encoding="utf-8"
        )
        logger.info(f"  Evaluation: {eval_path}")
    except Exception as exc:
        logger.warning(f"Evaluation skipped: {exc}")

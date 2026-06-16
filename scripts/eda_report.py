#!/usr/bin/env python3
"""Generate a reproducible EDA report for the processed road safety dataset.

Creates `reports/eda_summary.html` and supporting images in `reports/`.

Usage:
    python scripts/eda_report.py --input RoadSense/outputs/processed_road_safety.gpkg --output reports/eda_summary.html
"""
from pathlib import Path
import argparse
import geopandas as gpd
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import html
import sys


def ensure_outdir(out_path: Path):
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def load_data(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    gdf = gpd.read_file(path)
    return gdf


def missing_value_table(df: pd.DataFrame) -> pd.DataFrame:
    miss = df.isnull().sum()
    pct = df.isnull().mean()
    out = pd.DataFrame({"missing_count": miss, "missing_frac": pct})
    out = out.sort_values("missing_frac", ascending=False)
    return out


def summary_stats(df: pd.DataFrame, cols) -> pd.DataFrame:
    return df[cols].describe().transpose()


def save_histograms(df: pd.DataFrame, cols, out_dir: Path):
    images = []
    for c in cols:
        if c not in df.columns:
            continue
        fig, ax = plt.subplots(figsize=(6, 4))
        try:
            sns.histplot(df[c].dropna(), bins=50, kde=False, ax=ax)
        except Exception:
            ax.text(0.5, 0.5, f"Unable to plot {c}", ha='center')
        ax.set_title(c)
        fname = out_dir / f"hist_{c}.png"
        fig.tight_layout()
        fig.savefig(fname, dpi=150)
        plt.close(fig)
        images.append(fname.name)
    return images


def save_boxplots(df: pd.DataFrame, cols, out_dir: Path):
    images = []
    for c in cols:
        if c not in df.columns:
            continue
        fig, ax = plt.subplots(figsize=(6, 2.5))
        try:
            sns.boxplot(x=df[c].dropna(), ax=ax)
        except Exception:
            ax.text(0.5, 0.5, f"Unable to plot {c}", ha='center')
        ax.set_title(c)
        fname = out_dir / f"box_{c}.png"
        fig.tight_layout()
        fig.savefig(fname, dpi=150)
        plt.close(fig)
        images.append(fname.name)
    return images


def correlation_heatmap(df: pd.DataFrame, out_dir: Path, prefix: str = "corr"):
    numeric = df.select_dtypes(include=[np.number])
    if numeric.shape[1] < 2:
        return None
    corr = numeric.corr()
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(corr, ax=ax, cmap='RdBu_r', center=0)
    ax.set_title('Correlation matrix')
    fname = out_dir / f"{prefix}_heatmap.png"
    fig.tight_layout()
    fig.savefig(fname, dpi=150)
    plt.close(fig)
    return fname.name, corr


def region_comparison(df: pd.DataFrame, group_col: str, cols) -> pd.DataFrame:
    if group_col not in df.columns:
        return pd.DataFrame()
    agg = df.groupby(group_col)[cols].agg(['count', 'mean', 'std', 'min', 'max'])
    return agg


def geometry_report(gdf: gpd.GeoDataFrame) -> dict:
    info = {}
    info['crs'] = getattr(gdf, 'crs', None)
    info['total_features'] = len(gdf)
    info['null_geometry'] = int(gdf.geometry.isnull().sum())
    try:
        info['bounds'] = gdf.total_bounds.tolist()
    except Exception:
        info['bounds'] = None
    try:
        info['geom_types'] = gdf.geometry.geom_type.value_counts().to_dict()
    except Exception:
        info['geom_types'] = {}
    return info


def build_html(title: str, sections: dict, out_path: Path):
    pieces = [f"<html><head><meta charset=\"utf-8\"><title>{html.escape(title)}</title></head><body>"]
    pieces.append(f"<h1>{html.escape(title)}</h1>")
    for heading, content in sections.items():
        pieces.append(f"<h2>{html.escape(heading)}</h2>")
        pieces.append(content)
    pieces.append("</body></html>")
    out_path.write_text('\n'.join(pieces), encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description="EDA report for processed road safety data")
    p.add_argument('--input', type=Path, default=Path('RoadSense/outputs/processed_road_safety.gpkg'))
    p.add_argument('--output', type=Path, default=Path('reports/eda_summary.html'))
    p.add_argument('--sample', type=int, default=100)
    args = p.parse_args()

    out_dir = ensure_outdir(args.output)

    print('Loading data from', args.input)
    gdf = load_data(args.input)
    df = gdf.copy()

    # Columns of interest
    key_cols = [
        'SpeedLimit', 'MedianSpeed', 'F85thPercentileSpeed',
        'PercentOverLimit', 'WeightedSample', 'SampleSize_avg', 'RankedPercentile', 'Shape_Length'
    ]

    # Missing values
    miss_tbl = missing_value_table(df)
    miss_html = miss_tbl.to_html(classes='table table-striped')

    # Summary stats for key cols
    present = [c for c in key_cols if c in df.columns]
    stats = summary_stats(df, present)
    stats_html = stats.to_html(classes='table table-sm')

    # Save histograms and boxplots
    images = []
    hist_imgs = save_histograms(df, present, out_dir)
    box_imgs = save_boxplots(df, present, out_dir)
    images.extend(hist_imgs)
    images.extend(box_imgs)

    # Correlation heatmap
    corr_res = correlation_heatmap(df, out_dir)
    corr_img = corr_res[0] if corr_res else None
    corr_df = corr_res[1] if corr_res else None

    # Region comparison
    region_cmp = region_comparison(df, 'region', present)
    region_html = region_cmp.to_html(classes='table table-sm') if not region_cmp.empty else '<p>No region column found.</p>'

    # Duplicates
    dup_count = df.duplicated().sum()

    # Geometry report
    geom_info = geometry_report(gdf)
    geom_html = f"<pre>{html.escape(str(geom_info))}</pre>"

    # Build sections
    sections = {
        'Data snapshot': f"<p>Rows: {len(df)}</p><p>Columns: {len(df.columns)}</p>",
        'Geometry report': geom_html,
        'Missing values': miss_html,
        'Summary statistics (selected columns)': stats_html,
        'Region comparison (selected columns)': region_html,
        'Duplicate rows': f"<p>Duplicate row count: {dup_count}</p>",
    }

    # add images to report
    imgs_html = ''
    for im in images:
        imgs_html += f"<div style='display:inline-block;margin:6px'><img src=\"{im}\" style=\"max-width:360px;\"><div style='text-align:center'>{html.escape(im)}</div></div>"
    if imgs_html:
        sections['Histograms and boxplots'] = imgs_html

    if corr_img is not None:
        sections['Correlation matrix'] = f"<img src=\"{corr_img}\" style=\"max-width:800px\">"

    build_html('RoadSense EDA report', sections, args.output)
    print('Report written to', args.output)


if __name__ == '__main__':
    main()

"""Shared helpers for RoadSense."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from loguru import logger


def audit_datasets(data_root: str = "data/raw") -> dict[str, Any]:
    """Audit raw datasets and report basic coverage and schema checks."""

    root = Path(data_root)
    report: dict[str, Any] = {}

    gps_files = list((root / "gps_probe").glob("*.csv"))
    if gps_files:
        gps = pd.concat([pd.read_csv(file_path) for file_path in gps_files], ignore_index=True)
        report["gps_probe"] = {
            "rows": len(gps),
            "columns": list(gps.columns),
            "null_pct": (gps.isnull().sum() / len(gps) * 100).to_dict(),
        }
        if "segment_id" in gps.columns and not gps.empty:
            logger.info(f"GPS probe: {len(gps):,} rows, {gps['segment_id'].nunique():,} unique segments")
    else:
        logger.warning("No GPS probe files found in data/raw/gps_probe/")

    network_files = list((root / "road_network").glob("*.gpkg"))
    if network_files:
        network = gpd.read_file(network_files[0])
        report["road_network"] = {
            "segments": len(network),
            "crs": str(network.crs),
            "columns": list(network.columns),
            "geometry_types": network.geom_type.value_counts().to_dict(),
        }
        logger.info(f"Road network: {len(network):,} segments, CRS: {network.crs}")
    else:
        logger.warning("No road network files found in data/raw/road_network/")

    return report


def main() -> int:
    """Command-line entrypoint for dataset auditing."""

    import argparse

    parser = argparse.ArgumentParser(description="Audit RoadSense input datasets.")
    parser.add_argument("action", nargs="?", default="audit", choices=["audit"])
    parser.add_argument("--data-root", default="data/raw", help="Path to raw data folder.")
    args = parser.parse_args()

    if args.action == "audit":
        report = audit_datasets(args.data_root)
        print(json.dumps(report, indent=2, default=str))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

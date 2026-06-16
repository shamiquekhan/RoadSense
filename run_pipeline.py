#!/usr/bin/env python3
"""
ADB AI for Safer Roads 2026 — Speed Safety Score Pipeline
==========================================================
Primary entry point. Loads Thailand and Maharashtra road safety data,
computes Safe System gaps, VRU risk, and a composite Speed Safety
Score for each road segment.

Usage:
    python run_pipeline.py                                          # default: both approaches
    python run_pipeline.py --approach 4component                     # 4-component only
    python run_pipeline.py --approach roadsense                      # 3-module only
    python run_pipeline.py --pbf <path>.osm.pbf                      # OSM enrichment via pyrosm
    python run_pipeline.py --osm                                     # OSM via Overpass (fallback)
    python run_pipeline.py --serve                                   # host map via http
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure the src package is on the path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "src"))

import geopandas as gpd

from roadsense.pipeline import run_pipeline_4component, run_pipeline_roadsense
from roadsense.data.osm_enrich import enrich_with_osm_pois
from roadsense.config import RAW_DATA_DIR, OUTPUT_DIR


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADB AI for Safer Roads — Speed Safety Score Pipeline"
    )
    parser.add_argument(
        "--approach", choices=["4component", "roadsense", "both"],
        default="both", help="Scoring approach (default: both)"
    )
    parser.add_argument(
        "--outdir", default=str(OUTPUT_DIR),
        help="Output directory (default: ./outputs)"
    )
    parser.add_argument(
        "--osm", action="store_true",
        help="Enrich VRU scores with OSM points of interest (schools, markets)"
    )
    parser.add_argument(
        "--pbf", nargs="*", default=None,
        help="GeoFabrik PBF file(s) for pyrosm enrichment (replaces Overpass API)"
    )
    parser.add_argument(
        "--improve-urban", nargs="*", default=None,
        help="PBF file(s) for OSM-based urban/rural classification improvement"
    )
    parser.add_argument(
        "--serve", action="store_true",
        help="Start a local HTTP server to view the map"
    )
    parser.add_argument(
        "--data-dir", default=str(RAW_DATA_DIR),
        help="Directory containing raw ADB GeoJSON files"
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.approach in ("4component", "both"):
        print("\n═══ 4-Component Pipeline ═══════════════════════════\n")
        df = run_pipeline_4component(data_dir, out_dir)

    if args.approach in ("roadsense", "both"):
        print("\n═══ RoadSense 3-Module Pipeline ════════════════════\n")
        df = run_pipeline_roadsense(data_dir, out_dir)

    if args.pbf:
        print("\n═══ OSM Enrichment (pyrosm) ════════════════════════\n")
        from roadsense.data.osm_enrich import enrich_with_pyrosm
        from roadsense.data.loader import load_and_clean
        df_osm = load_and_clean(data_dir)
        df_osm = enrich_with_pyrosm(df_osm, [Path(p) for p in args.pbf])

        # Add enrichment columns as VRU context before scoring
        for col in ["near_school", "near_market"]:
            if col not in df_osm.columns:
                df_osm[col] = False
        df_osm["high_ptw_area"] = df_osm.get("high_ptw_area", False)

        enriched_out = out_dir / "enriched_scores.gpkg"
        enriched_csv = out_dir / "enriched_scores.csv"

        # Re-score with enrichment context
        if args.approach in ("4component", "both"):
            from roadsense.scoring import score_dataframe_4component
            df_scored = score_dataframe_4component(df_osm)
            df_scored = gpd.GeoDataFrame(df_scored, geometry="geometry", crs=df_osm.crs)
            df_scored.to_file(enriched_out, driver="GPKG")
            df_scored[[c for c in df_scored.columns if c != "geometry"]].to_csv(enriched_csv, index=False)
            from roadsense.pipeline import print_kpis_4component
            print_kpis_4component(df_scored)
            print(f"  Enriched 4-component scores saved to {enriched_out}")

    if args.improve_urban:
        print("\n═══ Improved Urban/Rural Classification ═══════════════\n")
        from roadsense.data.loader import load_and_clean
        from roadsense.data.osm_enrich import improve_urban_classification
        df = load_and_clean(data_dir)
        df = improve_urban_classification(df, [Path(p) for p in args.improve_urban])
        urban_changed = (df["urban_source"] == "OSM").sum()
        print(f"  Reclassified {urban_changed}/{len(df)} segments from OSM land use")
        changed_pct = (df["urban_source"] == "OSM").mean() * 100
        conf_mean = df["urban_classification_confidence"].mean()
        print(f"  Urban classification confidence: mean {conf_mean:.2f}")
        urban_out = out_dir / "improved_urban_classification.gpkg"
        df.to_file(urban_out, driver="GPKG")
        print(f"  Saved: {urban_out}")

    if args.osm:
        print("\n═══ OSM Enrichment (Overpass API) ═══════════════════\n")
        from roadsense.data.loader import load_and_clean
        df = load_and_clean(data_dir)
        df = enrich_with_osm_pois(df)
        enriched_out = out_dir / "enriched_scores_overpass.gpkg"
        df.to_file(enriched_out, driver="GPKG")
        print(f"  Enriched data saved to {enriched_out}")

    print(f"\n✓ Complete. Outputs in: {out_dir}")

    if args.serve:
        import http.server
        import socketserver
        port = 8080
        print(f"\n  Serving map at http://localhost:{port}/")
        os.chdir(out_dir)
        with socketserver.TCPServer(("", port), http.server.SimpleHTTPRequestHandler) as httpd:
            httpd.serve_forever()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

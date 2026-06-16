"""Visualisation helpers for RoadSense outputs."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import folium

from src.scoring import tier_colour


def build_priority_map(scored_segments_path: str | Path, output_html: str | Path) -> Path:
    """Create a lightweight interactive map from scored segments."""

    gdf = gpd.read_file(scored_segments_path)
    geometry_series = gdf.to_crs(4326).geometry
    union_geometry = geometry_series.union_all() if hasattr(geometry_series, "union_all") else geometry_series.unary_union
    center = union_geometry.centroid
    output_file = Path(output_html)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    road_map = folium.Map(location=[center.y, center.x], zoom_start=12, tiles="CartoDB positron")

    for _, row in gdf.to_crs(4326).iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue
        colour = tier_colour(row.get("risk_tier", "Low"))
        weight = 4 if row.get("rank", 9999) <= 100 else 2

        def style_function(_feature, color=colour, line_weight=weight):
            return {
                "color": color,
                "weight": line_weight,
                "opacity": 0.85,
            }

        feature = folium.GeoJson(
            geometry.__geo_interface__,
            style_function=style_function,
            tooltip=folium.Tooltip(row.get("popup_text", str(row.get("segment_id", "N/A")))),
        )
        feature.add_to(road_map)

    road_map.save(output_file)
    return output_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Build RoadSense priority map.")
    parser.add_argument("--input-path", default="outputs/geojson/all_segments_scored.gpkg")
    parser.add_argument("--output-html", default="outputs/maps/roadsense_priority_map.html")
    args = parser.parse_args()
    build_priority_map(args.input_path, args.output_html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

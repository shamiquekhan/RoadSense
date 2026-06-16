"""Spatial preprocessing pipeline for RoadSense."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from loguru import logger
from shapely.geometry import Point

MASTER_CRS = "EPSG:4326"
SNAP_TOLERANCE_M = 15
BUFFER_CONFIG_PATH = Path("config/buffer_params.yaml")
OUTPUT_PATH = Path("data/processed/segments_master.gpkg")


def load_buffer_config() -> dict:
    if BUFFER_CONFIG_PATH.exists():
        return yaml.safe_load(BUFFER_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return {"attractors_m": 150, "population_buffer_m": 300, "imagery_buffer_m": 50}


def load_road_network(path: str | Path) -> gpd.GeoDataFrame:
    """Load the road network and standardise basic fields."""

    network = gpd.read_file(path)
    if network.crs is None:
        raise ValueError("Road network has no CRS defined.")

    network = network.to_crs(MASTER_CRS)
    if "segment_id" not in network.columns:
        network["segment_id"] = [f"SEG-{index:06d}" for index in range(len(network))]
    if "posted_speed_limit" in network.columns and "posted_limit" not in network.columns:
        network["posted_limit"] = network["posted_speed_limit"]

    utm_crs = network.estimate_utm_crs()
    network["length_m"] = network.to_crs(utm_crs).geometry.length
    network["sinuosity"] = np.nan
    return network


def _aggregate_gps_by_segment(gps: pd.DataFrame) -> pd.DataFrame:
    return gps.groupby("segment_id").agg(
        mean_speed=("operating_speed", "mean"),
        v85=("operating_speed", lambda values: values.quantile(0.85)),
        speed_std=("operating_speed", "std"),
        traffic_count=("traffic_intensity", "mean"),
        posted_limit=("posted_speed_limit", "first"),
        obs_count=("operating_speed", "count"),
    ).reset_index()


def load_and_join_gps(network: gpd.GeoDataFrame, gps_dir: str | Path) -> gpd.GeoDataFrame:
    """Aggregate GPS probe data and join it to the road network."""

    gps_files = list(Path(gps_dir).glob("*.csv"))
    if not gps_files:
        logger.warning(f"No GPS probe files found in {gps_dir}")
        return network

    gps = pd.concat([pd.read_csv(file_path) for file_path in gps_files], ignore_index=True)

    if "segment_id" in gps.columns:
        network = network.merge(_aggregate_gps_by_segment(gps), on="segment_id", how="left")
        return network

    if {"latitude", "longitude"}.issubset(gps.columns):
        gps_gdf = gpd.GeoDataFrame(
            gps,
            geometry=gpd.points_from_xy(gps["longitude"], gps["latitude"]),
            crs=MASTER_CRS,
        )
        utm_crs = network.estimate_utm_crs()
        gps_utm = gps_gdf.to_crs(utm_crs)
        network_utm = network.to_crs(utm_crs)

        joined = gpd.sjoin_nearest(
            gps_utm,
            network_utm[["segment_id", "geometry"]],
            how="left",
            max_distance=SNAP_TOLERANCE_M,
            distance_col="snap_dist",
        )
        logger.info(f"GPS snap coverage: {joined['segment_id'].notna().mean():.1%}")
        network = network.merge(_aggregate_gps_by_segment(joined), on="segment_id", how="left")
        return network

    raise ValueError("GPS data must contain either segment_id or latitude/longitude fields.")


def join_context_layers(network: gpd.GeoDataFrame, context_dir: str | Path) -> gpd.GeoDataFrame:
    """Join schools, markets, population density, land use, and PTW layers."""

    cfg = load_buffer_config()
    context_path = Path(context_dir)
    utm_crs = network.estimate_utm_crs()
    network_utm = network.to_crs(utm_crs)

    attractor_radius = cfg.get("attractors_m", 150)
    attractor_sources = ["schools", "markets", "bus_stops"]
    attractor_counts = []

    for layer_name in attractor_sources:
        candidates = list(context_path.glob(f"*{layer_name}*"))
        if not candidates:
            continue

        points = gpd.read_file(candidates[0]).to_crs(utm_crs)
        buffered = network_utm[["segment_id", "geometry"]].copy()
        buffered["geometry"] = buffered.geometry.buffer(attractor_radius)
        joined = gpd.sjoin(buffered, points, how="left", predicate="contains")
        counts = joined.groupby("segment_id").size().rename(f"{layer_name}_count").reset_index()
        network = network.merge(counts, on="segment_id", how="left")
        network[f"{layer_name}_count"] = network[f"{layer_name}_count"].fillna(0)
        attractor_counts.append(f"{layer_name}_count")

    if attractor_counts:
        network["attractor_count"] = network[attractor_counts].sum(axis=1)
        network["near_attractor"] = (network["attractor_count"] > 0).astype(int)
    else:
        network["attractor_count"] = 0
        network["near_attractor"] = 0

    population_candidates = list(context_path.glob("*population*"))
    if population_candidates:
        population = gpd.read_file(population_candidates[0]).to_crs(utm_crs)
        centroids = network_utm.copy()
        centroids["geometry"] = network_utm.geometry.centroid
        pop_join = gpd.sjoin(centroids[["segment_id", "geometry"]], population, how="left", predicate="within")
        if "population_density" in pop_join.columns:
            population_agg = pop_join.groupby("segment_id")["population_density"].mean().reset_index()
            network = network.merge(population_agg, on="segment_id", how="left")
            max_population = network["population_density"].quantile(0.99)
            if pd.notna(max_population) and max_population > 0:
                network["pop_density_norm"] = (network["population_density"].clip(upper=max_population) / max_population).fillna(0)
            else:
                network["pop_density_norm"] = 0
    else:
        network["pop_density_norm"] = 0

    land_use_candidates = list(context_path.glob("*land_use*"))
    if land_use_candidates:
        land_use = gpd.read_file(land_use_candidates[0]).to_crs(utm_crs)
        centroids = network_utm.copy()
        centroids["geometry"] = network_utm.geometry.centroid
        land_join = gpd.sjoin(centroids[["segment_id", "geometry"]], land_use, how="left", predicate="within")
        if "land_use_class" in land_join.columns:
            land_use_agg = land_join.groupby("segment_id")["land_use_class"].first().reset_index()
            network = network.merge(land_use_agg, on="segment_id", how="left")

    ptw_candidates = list(context_path.glob("*ptw*")) or list(context_path.glob("*motorcycle*"))
    if ptw_candidates:
        ptw = gpd.read_file(ptw_candidates[0]).to_crs(utm_crs)
        ptw_join = gpd.sjoin(network_utm[["segment_id", "geometry"]], ptw, how="left", predicate="intersects")
        if "ptw_index" in ptw_join.columns:
            ptw_agg = ptw_join.groupby("segment_id")["ptw_index"].mean().reset_index()
            network = network.merge(ptw_agg, on="segment_id", how="left")
    if "ptw_index" not in network.columns:
        network["ptw_index"] = 0
    network["ptw_index"] = network["ptw_index"].fillna(0)

    return network


def compute_network_attributes(network: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Derive intersection density and sinuosity-related fields."""

    utm_crs = network.estimate_utm_crs()
    network_utm = network.to_crs(utm_crs)
    if "intersection_density" not in network.columns:
        endpoints: list[Point] = []
        for geometry in network_utm.geometry:
            if geometry is None or geometry.is_empty:
                continue
            coords = list(geometry.coords)
            endpoints.extend([Point(coords[0]), Point(coords[-1])])

        endpoint_gdf = gpd.GeoDataFrame(geometry=endpoints, crs=utm_crs)
        buffered = network_utm[["segment_id", "geometry"]].copy()
        buffered["geometry"] = buffered.geometry.buffer(50)
        joined = gpd.sjoin(buffered, endpoint_gdf, how="left", predicate="contains")
        density = joined.groupby("segment_id").size().rename("intersection_density").reset_index()
        lengths_km = network_utm.set_index("segment_id")["length_m"] / 1000
        density["intersection_density"] = density["intersection_density"] / lengths_km.reindex(density["segment_id"]).to_numpy()
        network = network.merge(density, on="segment_id", how="left")

    network["intersection_density"] = network["intersection_density"].fillna(0)
    return network


def run(
    network_path: str = "data/raw/road_network",
    gps_dir: str = "data/raw/gps_probe",
    context_dir: str = "data/raw/context_layers",
    output_path: str | Path = OUTPUT_PATH,
) -> gpd.GeoDataFrame:
    """Execute the full preprocessing pipeline and save the master dataset."""

    network_dir = Path(network_path)
    network_files = list(network_dir.glob("*.gpkg")) + list(network_dir.glob("*.shp"))
    if not network_files:
        raise FileNotFoundError(f"No road network file found in {network_path}")

    logger.info("RoadSense preprocessing started")
    network = load_road_network(network_files[0])
    network = load_and_join_gps(network, gps_dir)
    network = join_context_layers(network, context_dir)
    network = compute_network_attributes(network)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    network.to_file(output_file, driver="GPKG", layer="segments")
    logger.success(f"Master GeoPackage saved to {output_file}")
    return network


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RoadSense preprocessing.")
    parser.add_argument("--network-path", default="data/raw/road_network")
    parser.add_argument("--gps-dir", default="data/raw/gps_probe")
    parser.add_argument("--context-dir", default="data/raw/context_layers")
    parser.add_argument("--output-path", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    run(args.network_path, args.gps_dir, args.context_dir, args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for preprocessing helpers."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, Polygon

from src.preprocessing import compute_network_attributes, join_context_layers, load_and_join_gps, load_road_network, run
from src.preprocessing import load_buffer_config


def test_load_buffer_config_returns_defaults() -> None:
    config = load_buffer_config()
    assert "attractors_m" in config
    assert "imagery_m" in config


def _write_network(tmp_path: Path) -> Path:
    network = gpd.GeoDataFrame(
        {
            "segment_id": ["SEG-001", "SEG-002"],
            "posted_speed_limit": [60, 30],
            "functional_class": ["primary", "residential"],
            "urban_rural": ["urban", "urban"],
        },
        geometry=[
            LineString([(121.0, 14.5), (121.01, 14.5)]),
            LineString([(121.01, 14.5), (121.02, 14.5)]),
        ],
        crs="EPSG:4326",
    )
    network_path = tmp_path / "road_network.gpkg"
    network.to_file(network_path, layer="segments", driver="GPKG")
    return network_path


def test_load_road_network_and_gps_join(tmp_path: Path) -> None:
    network_path = _write_network(tmp_path)
    network = load_road_network(network_path)
    assert "length_m" in network.columns

    gps_dir = tmp_path / "gps"
    gps_dir.mkdir()
    pd.DataFrame(
        {
            "segment_id": ["SEG-001", "SEG-001", "SEG-002"],
            "operating_speed": [58, 62, 31],
            "traffic_intensity": [100, 120, 80],
            "posted_speed_limit": [60, 60, 30],
        }
    ).to_csv(gps_dir / "probe.csv", index=False)

    joined = load_and_join_gps(network, gps_dir)
    assert joined["v85"].notna().any()
    assert joined["obs_count"].max() == 2


def test_join_context_layers_and_attributes(tmp_path: Path) -> None:
    network_path = _write_network(tmp_path)
    network = load_road_network(network_path)

    context_dir = tmp_path / "context"
    context_dir.mkdir()

    points = gpd.GeoDataFrame(
        {"name": ["school"]},
        geometry=[Point(121.005, 14.5)],
        crs="EPSG:4326",
    )
    points.to_file(context_dir / "schools.gpkg", layer="schools", driver="GPKG")

    markets = gpd.GeoDataFrame(
        {"name": ["market"]},
        geometry=[Point(121.006, 14.5)],
        crs="EPSG:4326",
    )
    markets.to_file(context_dir / "markets.gpkg", layer="markets", driver="GPKG")

    population = gpd.GeoDataFrame(
        {"population_density": [1000]},
        geometry=[Polygon([(120.99, 14.49), (121.03, 14.49), (121.03, 14.51), (120.99, 14.51)])],
        crs="EPSG:4326",
    )
    population.to_file(context_dir / "population.gpkg", layer="population", driver="GPKG")

    land_use = gpd.GeoDataFrame(
        {"land_use_class": ["residential"]},
        geometry=[Polygon([(120.99, 14.49), (121.03, 14.49), (121.03, 14.51), (120.99, 14.51)])],
        crs="EPSG:4326",
    )
    land_use.to_file(context_dir / "land_use.gpkg", layer="land_use", driver="GPKG")

    ptw = gpd.GeoDataFrame(
        {"ptw_index": [0.8]},
        geometry=[Polygon([(120.99, 14.49), (121.03, 14.49), (121.03, 14.51), (120.99, 14.51)])],
        crs="EPSG:4326",
    )
    ptw.to_file(context_dir / "ptw.gpkg", layer="ptw", driver="GPKG")

    joined = join_context_layers(network, context_dir)
    attributed = compute_network_attributes(joined)
    assert attributed["near_attractor"].sum() >= 1
    assert attributed["pop_density_norm"].max() > 0
    assert attributed["land_use_class"].notna().any()
    assert attributed["ptw_index"].max() > 0
    assert "intersection_density" in attributed.columns


def test_run_builds_master_table(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "road_network").mkdir(parents=True)
    (raw_root / "gps_probe").mkdir(parents=True)
    (raw_root / "context_layers").mkdir(parents=True)
    network_path = _write_network(raw_root / "road_network")
    gps = pd.DataFrame(
        {
            "segment_id": ["SEG-001"],
            "operating_speed": [58],
            "traffic_intensity": [100],
            "posted_speed_limit": [60],
        }
    )
    gps.to_csv(raw_root / "gps_probe" / "probe.csv", index=False)

    output_path = tmp_path / "segments_master.gpkg"
    result = run(str(raw_root / "road_network"), str(raw_root / "gps_probe"), str(raw_root / "context_layers"), output_path)
    assert Path(output_path).exists()
    assert len(result) == 2

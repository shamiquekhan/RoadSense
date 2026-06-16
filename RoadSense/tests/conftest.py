"""Shared pytest fixtures for RoadSense tests."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString


@pytest.fixture
def sample_segments() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "segment_id": ["SEG-001", "SEG-002", "SEG-003"],
            "functional_class": ["primary", "residential", "motorway"],
            "urban_rural": ["urban", "urban", "rural"],
            "posted_limit": [60.0, 30.0, 100.0],
            "v85": [78.0, 28.0, 95.0],
            "traffic_count": [1200.0, 200.0, 3000.0],
            "near_attractor": [1, 0, 0],
            "attractor_count": [3, 0, 0],
            "pop_density_norm": [0.8, 0.5, 0.1],
            "intersection_density": [12.0, 8.0, 1.0],
            "ptw_index": [0.6, 0.2, 0.1],
            "infrastructure_gap": [0.7, 0.4, 0.3],
            "length_m": [500.0, 200.0, 2000.0],
            "A_score": [0.8, 0.2, 0.1],
            "B_score": [0.9, 0.4, 0.1],
            "C_score": [0.7, 0.3, 0.2],
        },
        geometry=[
            LineString([(121.0, 14.5), (121.01, 14.5)]),
            LineString([(121.01, 14.5), (121.01, 14.51)]),
            LineString([(121.02, 14.5), (121.05, 14.5)]),
        ],
        crs="EPSG:4326",
    )

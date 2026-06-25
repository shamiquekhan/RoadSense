"""Shared pytest fixtures for RoadSense tests."""

from __future__ import annotations

import geopandas as gpd
import numpy as np  # noqa: F401 – used in test_data_loader via fixture
import pytest
from shapely.geometry import LineString


@pytest.fixture
def sample_segments_df() -> gpd.GeoDataFrame:
    """ADB-style DataFrame for 4-component scoring and loader tests."""
    return gpd.GeoDataFrame(
        {
            "OBJECTID": [1, 2, 3],
            "segment_id": ["SEG-001", "SEG-002", "SEG-003"],
            "AnalysisStatus": ["Valid", "Valid", "Valid"],
            "RoadClass": ["primary", "secondary", "motorway"],
            "LandUse": ["URBAN", "URBAN", "RURAL"],
            "SpeedLimit": [60.0, 30.0, 100.0],
            "F85thPercentileSpeed": [78.0, 28.0, 95.0],
            "MedianSpeed": [65.0, 25.0, 90.0],
            "PercentOverLimit": [0.3, 0.1, 0.05],
            "SampleSize_avg": [800.0, 600.0, 5000.0],
            "WeightedSample": [1200.0, 200.0, 3000.0],
            "RankedPercentile": [80.0, 30.0, 90.0],
            "Shape_Length": [500.0, 200.0, 2000.0],
        },
        geometry=[
            LineString([(121.0, 14.5), (121.01, 14.5)]),
            LineString([(121.01, 14.5), (121.01, 14.51)]),
            LineString([(121.02, 14.5), (121.05, 14.5)]),
        ],
        crs="EPSG:4326",
    )


@pytest.fixture
def sample_segments_roadsense() -> gpd.GeoDataFrame:
    """RoadSense-named fixture for 3-module scoring tests."""
    gdf = sample_segments_df()
    return gdf.rename(
        columns={
            "RoadClass": "functional_class",
            "LandUse": "urban_rural",
            "SpeedLimit": "posted_limit",
            "F85thPercentileSpeed": "v85",
            "SampleSize_avg": "obs_count",
            "WeightedSample": "traffic_count",
        }
    )

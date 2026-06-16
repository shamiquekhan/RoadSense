"""Unit tests for data loading and cleaning."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from roadsense.data.loader import (
    _fix_string_columns,
    _fix_speed_limit,
    _clip_bounded_fields,
    clean_adb,
)


class TestFixStringColumns:
    def test_landuse_normalised(self):
        df = pd.DataFrame({
            "LandUse": ["urban", "RURAL", "Urban", np.nan, ""],
            "RoadClass": ["primary", "secondary", "Trunk", "Motorway", "primary"],
        })
        df = _fix_string_columns(df)
        assert df["LandUse"].tolist() == ["URBAN", "RURAL", "URBAN", "RURAL", "RURAL"]
        assert df["RoadClass"].tolist() == ["primary", "secondary", "trunk", "motorway", "primary"]


class TestFixSpeedLimit:
    def test_string_to_numeric(self):
        df = pd.DataFrame({
            "SpeedLimit": ["55", "80", "30", None, "0"],
            "RoadClass": ["primary", "secondary", "trunk", "motorway", "secondary"],
        })
        df = _fix_speed_limit(df)
        assert df["SpeedLimit"].dtype in (np.float64, float)
        assert df.loc[0, "SpeedLimit"] == 55
        # Null and zero should be imputed
        assert df.loc[3, "SpeedLimit"] == 110  # motorway default
        assert df.loc[4, "SpeedLimit"] == 60  # secondary default


class TestClipBoundedFields:
    def test_clip_percent_over_limit(self):
        df = pd.DataFrame({
            "PercentOverLimit": [-0.1, 0.5, 1.5],
            "Percentile": [-0.1, 0.5, 1.5],
        })
        df = _clip_bounded_fields(df)
        assert df["PercentOverLimit"].tolist() == [0.0, 0.5, 1.0]
        assert df["Percentile"].tolist() == [0.0, 0.5, 1.0]


class TestCleanAdb:
    def test_valid_filter(self, sample_segments_df):
        import geopandas as gpd
        gdf = gpd.GeoDataFrame(
            sample_segments_df,
            geometry=[None] * len(sample_segments_df),
        )
        # Should filter to Valid only
        cleaned = clean_adb(gdf)
        assert len(cleaned) == len(gdf)  # all are Valid in fixture

    def test_invalid_removed(self, sample_segments_df):
        import geopandas as gpd
        df = sample_segments_df.copy()
        df.loc[0, "AnalysisStatus"] = "Not Included"
        gdf = gpd.GeoDataFrame(df, geometry=[None] * len(df))
        cleaned = clean_adb(gdf)
        assert len(cleaned) == len(df) - 1

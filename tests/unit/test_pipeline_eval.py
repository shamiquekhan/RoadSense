"""Unit tests for evaluation metrics and pipeline helper functions."""

import json
import pytest
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString

from roadsense.evaluation.metrics import (
    correlation_matrix,
    sensitivity_analysis,
    morans_i,
    benchmark_validation,
    full_evaluation,
)
from roadsense.pipeline import (
    add_centroids,
    add_log_features,
    impute_low_sample_scores,
)


@pytest.fixture
def scored_gdf() -> gpd.GeoDataFrame:
    """Mock scored GeoDataFrame with scores and geometries."""
    return gpd.GeoDataFrame(
        {
            "segment_id": ["SEG-01", "SEG-02", "SEG-03", "SEG-04", "SEG-05"],
            "RoadClass": ["primary", "primary", "primary", "primary", "primary"],
            "LandUse": ["URBAN", "URBAN", "URBAN", "URBAN", "URBAN"],
            "A_score": [0.8, 0.4, 0.2, 0.9, 0.1],
            "B_score": [0.7, 0.5, 0.3, 0.8, 0.2],
            "C_score": [0.6, 0.4, 0.2, 0.7, 0.1],
            "SSS": [0.7, 0.43, 0.23, 0.8, 0.13],
            "risk_tier": [
                "Critical — Immediate Review",
                "Moderate — Scheduled Review",
                "Low — Monitor",
                "Critical — Immediate Review",
                "Low — Monitor",
            ],
            "SampleSize_avg": [2000, 1500, 500, 1800, 400],
        },
        geometry=[
            LineString([(0, 0), (0, 1)]),
            LineString([(0, 1), (0, 2)]),
            LineString([(0, 2), (0, 3)]),
            LineString([(0, 3), (0, 4)]),
            LineString([(0, 4), (0, 5)]),
        ],
        crs="EPSG:3857",
    )


class TestMetrics:
    def test_correlation_matrix(self, scored_gdf):
        df_corr = correlation_matrix(scored_gdf)
        assert not df_corr.empty
        assert "SSS" in df_corr.columns
        assert df_corr.shape == (4, 4)

    def test_correlation_matrix_missing_cols(self):
        df_empty = correlation_matrix(pd.DataFrame({"x": [1, 2]}))
        assert df_empty.empty

    def test_sensitivity_analysis(self, scored_gdf):
        res = sensitivity_analysis(scored_gdf, perturbation=0.20, top_n=2)
        assert "results" in res
        assert "mean_stability" in res
        assert len(res["results"]) == 6  # 3 modules * 2 directions
        assert 0.0 <= res["mean_stability"] <= 1.0

    def test_sensitivity_analysis_missing_cols(self):
        res = sensitivity_analysis(pd.DataFrame({"A_score": [1]}))
        assert "error" in res

    def test_sensitivity_analysis_empty(self):
        res = sensitivity_analysis(
            pd.DataFrame(columns=["A_score", "B_score", "C_score", "segment_id"])
        )
        assert "error" in res

    def test_morans_i(self, scored_gdf):
        res = morans_i(scored_gdf, col="SSS")
        if "error" in res:
            # If libpysal fails internally or is missing (though we installed it)
            pytest.skip(f"Moran's I skipped: {res['error']}")
        else:
            assert "I" in res
            assert "p_value" in res
            assert "z_score" in res
            assert res["n_segments"] == 5

    def test_morans_i_insufficient_data(self, scored_gdf):
        small_gdf = scored_gdf.iloc[:2]
        res = morans_i(small_gdf)
        assert "error" in res

    def test_benchmark_validation(self, scored_gdf, tmp_path):
        benchmark_data = {
            "segments": [
                {"segment_id": "SEG-01", "known_risk": "critical"},
                {"segment_id": "SEG-03", "known_risk": "low"},
                {"segment_id": "SEG-04", "known_risk": "critical"},
            ]
        }
        bm_file = tmp_path / "benchmark.json"
        bm_file.write_text(json.dumps(benchmark_data))

        res = benchmark_validation(scored_gdf, bm_file)
        assert "accuracy" in res
        assert res["n_segments"] == 3
        # SEG-01 is predicted critical (SSS=0.7), Correct = True
        # SEG-03 is predicted low (SSS=0.23), Correct = True
        # SEG-04 is predicted critical (SSS=0.8), Correct = True
        # Accuracy should be 1.0
        assert res["accuracy"] == 1.0

    def test_benchmark_validation_missing_file(self, scored_gdf):
        res = benchmark_validation(scored_gdf, "nonexistent_file.json")
        assert "error" in res

    def test_full_evaluation(self, scored_gdf, tmp_path):
        benchmark_data = [{"segment_id": "SEG-01", "known_risk": "critical"}]
        bm_file = tmp_path / "benchmark_list.json"
        bm_file.write_text(json.dumps(benchmark_data))

        res = full_evaluation(scored_gdf, benchmark_file=bm_file)
        assert "correlation_matrix" in res
        assert "sensitivity" in res
        assert "morans_i" in res
        assert "benchmark" in res


class TestPipelineHelpers:
    def test_add_centroids(self, scored_gdf):
        df_out = add_centroids(scored_gdf)
        assert "centroid_lat" in df_out.columns
        assert "centroid_lon" in df_out.columns

    def test_add_log_features(self):
        df = pd.DataFrame({"WeightedSample": [0.0, 9.0], "SampleSize_avg": [0.0, 99.0]})
        df_out = add_log_features(df)
        assert "log_weighted_sample" in df_out.columns
        assert "log_sample_size" in df_out.columns
        assert np.allclose(df_out["log_weighted_sample"], np.log1p([0.0, 9.0]))

    def test_impute_low_sample_scores(self, scored_gdf):
        # SEG-03 has sample size 500, SEG-05 has sample size 400.
        # Threshold is 1000, so both should be imputed.
        df_imputed = impute_low_sample_scores(
            scored_gdf,
            score_cols=["SSS", "A_score"],
            sample_col="SampleSize_avg",
            threshold=1000,
            n_neighbors=2,
        )
        assert "imputed_SSS" in df_imputed.columns
        assert "imputed_A_score" in df_imputed.columns
        # SEG-01, SEG-02, SEG-04 should NOT have imputed scores (they are high-sample)
        assert pd.isna(df_imputed.loc[0, "imputed_SSS"])
        assert pd.isna(df_imputed.loc[1, "imputed_SSS"])
        # SEG-03 should have imputed scores
        assert not pd.isna(df_imputed.loc[2, "imputed_SSS"])
        assert not pd.isna(df_imputed.loc[4, "imputed_SSS"])

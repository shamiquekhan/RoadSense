"""Unit tests for core scoring functions."""

from __future__ import annotations

import pytest

from roadsense.scoring import (
    get_safe_system_limit,
    limit_misalignment_score,
    operating_speed_risk_score,
    pedestrian_fatality_risk,
    vru_exposure,
    classify_priority,
    explain_score,
    score_dataframe_4component,
    score_dataframe_roadsense,
)


class TestSafeSystemLimit:
    def test_known_combinations(self):
        assert get_safe_system_limit("secondary", "urban") == 30
        assert get_safe_system_limit("motorway", "rural") == 110
        assert get_safe_system_limit("primary", "urban") == 50

    def test_case_insensitive(self):
        assert get_safe_system_limit("SECONDARY", "URBAN") == 30
        assert get_safe_system_limit("Motorway", "Rural") == 110

    def test_fallback_default(self):
        assert get_safe_system_limit("unknown", "unknown") == 50


class TestLimitMisalignment:
    def test_no_misalignment(self):
        assert limit_misalignment_score(30, 30) == 0.0
        assert limit_misalignment_score(20, 30) == 0.0

    def test_partial_misalignment(self):
        # 50 vs 30 = gap 20, norm by 40 = 0.5
        assert limit_misalignment_score(50, 30) == 0.5

    def test_full_misalignment(self):
        # 70 vs 30 = gap 40, capped at 1.0
        assert limit_misalignment_score(70, 30) == 1.0
        assert limit_misalignment_score(100, 30) == 1.0


class TestOperatingSpeedRisk:
    def test_below_threshold(self):
        assert operating_speed_risk_score(30, 50) == 0.0

    def test_above_threshold(self):
        # 70 vs 50 = gap 20, norm by 40 = 0.5
        assert operating_speed_risk_score(70, 50) == 0.5


class TestPedestrianFatalityRisk:
    def test_sigmoid_shape(self):
        risk_30 = pedestrian_fatality_risk(30)
        risk_50 = pedestrian_fatality_risk(50)
        risk_70 = pedestrian_fatality_risk(70)
        assert 0.0 < risk_30 < risk_50 < risk_70 < 1.0
        # At 50 km/h, risk should be ~0.5
        assert abs(risk_50 - 0.5) < 0.05


class TestVRUExposure:
    def test_motorway_rural(self):
        assert vru_exposure("motorway", "rural") == pytest.approx(0.02, rel=1e-3)

    def test_secondary_urban(self):
        assert vru_exposure("secondary", "urban") == 0.9  # 0.9 * 1.0


class TestClassifyPriority:
    def test_critical(self):
        label, colour = classify_priority(0.70)
        assert "Critical" in label

    def test_low(self):
        label, colour = classify_priority(0.10)
        assert "Low" in label

    def test_boundaries(self):
        assert "Critical" in classify_priority(0.65)[0]
        assert "High" in classify_priority(0.45)[0]
        assert "Moderate" in classify_priority(0.25)[0]


class TestExplainScore:
    def test_safe_segment(self):
        text = explain_score(50, 45, "motorway", "rural")
        assert "consistent" in text.lower()

    def test_dangerous_segment(self):
        text = explain_score(80, 95, "secondary", "urban")
        assert "exceeds" in text
        assert "Safe System" in text

    def test_high_vru(self):
        text = explain_score(50, 60, "secondary", "urban", vru_risk_score=0.8)
        assert "VRU" in text


class TestScoreDataFrame:
    def test_4component_smoke(self, sample_segments_df):
        df = score_dataframe_4component(sample_segments_df)
        assert "speed_safety_score" in df.columns
        assert "priority_class" in df.columns
        assert "score_explanation" in df.columns
        assert df["speed_safety_score"].between(0, 1).all()

    def test_roadsense_smoke(self, sample_segments_df):
        df = score_dataframe_roadsense(sample_segments_df)
        assert "SSS" in df.columns
        assert "risk_tier" in df.columns
        assert "A_score" in df.columns
        assert "B_score" in df.columns
        assert "C_score" in df.columns
        assert df["SSS"].between(0, 1).all()

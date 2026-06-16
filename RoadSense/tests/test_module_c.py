"""Tests for Module C."""

from __future__ import annotations

from src.module_c import score_from_tags, score_from_precomputed_tags, score_dataframe


def test_score_from_tags_detects_protection() -> None:
    infra_gap, high_speed_flag = score_from_tags({"object--street-light": 1})
    assert infra_gap < 1.0
    assert high_speed_flag == 0.0


def test_score_from_precomputed_tags_uses_segment_id() -> None:
    infra_gap, high_speed_flag = score_from_precomputed_tags(
        "SEG-001",
        {"SEG-001": {"object--sign--speed-limit-80": 1}},
    )
    assert infra_gap <= 1.0
    assert high_speed_flag == 1.0


def test_score_dataframe_adds_expected_columns(sample_segments) -> None:
    scored = score_dataframe(sample_segments)
    for column in ["infrastructure_gap", "imagery_scene_class", "imagery_coverage", "C_score"]:
        assert column in scored.columns
    assert scored["C_score"].between(0, 1).all()

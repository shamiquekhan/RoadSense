"""Tests for Module A."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.module_a import compute_safe_system_gap, compute_speed_gap, get_safe_system_reference, normalise_to_unit, score_dataframe


def test_speed_gap_positive() -> None:
    row = pd.Series({"v85": 78.0, "posted_limit": 60.0})
    assert compute_speed_gap(row) == pytest.approx(18.0)


def test_speed_gap_nan_handling() -> None:
    row = pd.Series({"v85": float("nan"), "posted_limit": 60.0})
    assert np.isnan(compute_speed_gap(row))


def test_safe_system_reference_near_attractor() -> None:
    ref_no_attractor = get_safe_system_reference("primary", "urban", near_attractor=0)
    ref_near_attractor = get_safe_system_reference("primary", "urban", near_attractor=1)
    assert ref_near_attractor < ref_no_attractor


def test_safe_system_reference_minimum() -> None:
    ref = get_safe_system_reference("service", "urban", near_attractor=1)
    assert ref >= 20.0


def test_normalise_to_unit_bounds() -> None:
    values = pd.Series([18.0, -2.0, 5.0, 30.0])
    normalised = normalise_to_unit(values)
    assert (normalised >= 0).all()
    assert (normalised <= 1).all()


def test_score_dataframe_adds_expected_columns(sample_segments) -> None:
    scored = score_dataframe(sample_segments)
    for column in ["speed_gap", "safe_system_ref", "safe_system_gap", "speed_exceeds_limit", "A_score"]:
        assert column in scored.columns

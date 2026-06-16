"""Tests for Module B."""

from __future__ import annotations

import pandas as pd

from src.module_b import normalise, score_dataframe


def test_normalise_zero_variance() -> None:
    series = pd.Series([2.0, 2.0, 2.0])
    result = normalise(series)
    assert (result == 0.5).all()


def test_score_dataframe_adds_expected_columns(sample_segments) -> None:
    scored = score_dataframe(sample_segments)
    for column in ["attractor_score", "pop_score", "conflict_score", "ptw_score", "B_score"]:
        assert column in scored.columns
    assert scored["B_score"].between(0, 1).all()

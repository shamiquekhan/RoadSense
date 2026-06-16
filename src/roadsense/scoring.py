"""Speed Safety Score — core scoring functions.

Provides both the 4-component composite score and the 3-module
RoadSense scoring approach.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import (
    SAFE_SYSTEM_LIMITS,
    DEFAULT_SAFE_LIMIT,
    SCORE_WEIGHTS,
    ROAD_CLASS_VRU,
    LAND_USE_VRU,
    INFRA_GAP_MAP,
    PRIORITY_THRESHOLDS,
    PRIORITY_DEFAULT,
    MODULE_WEIGHTS,
)



def get_safe_system_limit(road_class: str, land_use: str) -> int:
    """Return the Safe System reference speed for a (road_class, land_use) pair."""
    return SAFE_SYSTEM_LIMITS.get(
        (road_class.lower(), land_use.lower()), DEFAULT_SAFE_LIMIT
    )



def limit_misalignment_score(speed_limit: float, ssl: float) -> float:
    """How far the posted limit exceeds the Safe System threshold (0–1)."""
    gap = max(speed_limit - ssl, 0)
    return min(gap / 40.0, 1.0)


def operating_speed_risk_score(f85: float, ssl: float) -> float:
    """How far actual traffic exceeds the Safe System threshold (0–1)."""
    gap = max(f85 - ssl, 0)
    return min(gap / 40.0, 1.0)


def pedestrian_fatality_risk(speed_kmh: float) -> float:
    """Pedestrian fatality risk curve — ITF/OECD (2018) Speed and Crash Risk, p.47.
    Originally derived from Pasanen (1992); recapitulated and updated by ITF."""
    return 1 / (1 + math.exp(-0.08 * (speed_kmh - 50)))


def vru_exposure(road_class: str, land_use: str) -> float:
    """Base VRU exposure from road class * land use."""
    rc = ROAD_CLASS_VRU.get(road_class.lower(), 0.5)
    lu = LAND_USE_VRU.get(land_use.lower(), 0.5)
    return rc * lu



def compute_vru_risk(
    road_class: str,
    land_use: str,
    f85: float,
    near_school: bool = False,
    near_market: bool = False,
    high_ptw_area: bool = False,
) -> float:
    """Composite VRU risk score (0–1) from available data."""
    base = vru_exposure(road_class, land_use)
    speed = pedestrian_fatality_risk(f85)
    boost = 0.0
    if near_school:
        boost += 0.20
    if near_market:
        boost += 0.15
    if high_ptw_area:
        boost += 0.15
    return min(base * speed + boost, 1.0)



def compute_composite_score(
    speed_limit: float,
    f85: float,
    road_class: str,
    land_use: str,
    ranked_percentile: float,
    vru_risk_score: float | None = None,
    weights: dict[str, float] | None = None,
) -> float:
    """Four-component Speed Safety Score (0–1)."""
    w = weights or SCORE_WEIGHTS
    ssl = get_safe_system_limit(road_class, land_use)
    vru = vru_risk_score if vru_risk_score is not None else compute_vru_risk(road_class, land_use, f85)

    A = limit_misalignment_score(speed_limit, ssl)
    B = operating_speed_risk_score(f85, ssl)
    C = vru
    D = ranked_percentile / 100.0

    return round(
        w["limit_misalignment"] * A + w["operating_speed"] * B + w["vru_exposure"] * C + w["volume"] * D,
        4,
    )


def compute_module_a_score(
    speed_limit: float, f85: float, road_class: str, land_use: str
) -> float:
    """RoadSense Module A: speed alignment (0–1)."""
    ssl = get_safe_system_limit(road_class, land_use)
    limit_score = limit_misalignment_score(speed_limit, ssl)
    speed_score = operating_speed_risk_score(f85, ssl)
    return round(0.50 * limit_score + 0.50 * speed_score, 4)


def compute_module_b_score(
    road_class: str, land_use: str, f85: float, ptw_flag: bool = False
) -> float:
    """RoadSense Module B: VRU exposure (0–1)."""
    base = vru_exposure(road_class, land_use)
    speed = pedestrian_fatality_risk(f85)
    raw = base * speed
    if ptw_flag:
        raw += 0.15
    if land_use.lower() == "urban":
        raw += 0.10
    return round(min(raw, 1.0), 4)


def compute_module_c_score(road_class: str, land_use: str, f85: float, posted: float) -> float:
    """RoadSense Module C: road environment proxy (0–1)."""
    rc = road_class.lower()
    lu = land_use.lower()
    infra_gap = INFRA_GAP_MAP.get((rc, lu), 0.50)
    speed_mismatch = max(f85 - posted, 0) / max(posted, 1)
    speed_mismatch = min(speed_mismatch, 1.0)
    urban_secondary_bonus = 0.15 if (rc == "secondary" and lu == "urban") else 0.0
    return round(min(0.60 * infra_gap + 0.25 * speed_mismatch + urban_secondary_bonus, 1.0), 4)



def classify_priority(
    score: float,
    thresholds: list[tuple[float, str, str]] | None = None,
    default: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Convert numeric score to (priority_label, hex_colour)."""
    thresholds = thresholds or PRIORITY_THRESHOLDS
    default = default or PRIORITY_DEFAULT
    for threshold, label, colour in thresholds:
        if score >= threshold:
            return label, colour
    return default



RELIABILITY_TIERS: list[tuple[int, str, str]] = [
    (5000, "High", "#1b5e20"),
    (1000, "Medium", "#f57f17"),
]
RELIABILITY_DEFAULT: tuple[str, str] = ("Low", "#b71c1c")


def compute_reliability_tier(
    sample_size: float,
    tiers: list[tuple[int, str, str]] | None = None,
    default: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Assign reliability tier based on SampleSize_avg.

    High (≥5000):  robust operating speed estimates
    Medium (≥1000): usable but noisier
    Low (<1000):   treat as indicative — high uncertainty
    """
    tiers = tiers or RELIABILITY_TIERS
    default = default or RELIABILITY_DEFAULT
    for threshold, label, colour in tiers:
        if sample_size >= threshold:
            return label, colour
    return default


def explain_score(
    speed_limit: float,
    f85: float,
    road_class: str,
    land_use: str,
    vru_risk_score: float | None = None,
) -> str:
    """Plain-language explanation of what drives this segment's score."""
    ssl = get_safe_system_limit(road_class, land_use)
    vru = vru_risk_score if vru_risk_score is not None else compute_vru_risk(road_class, land_use, f85)
    parts: list[str] = []
    if speed_limit > ssl:
        parts.append(
            f"Posted limit ({speed_limit:.0f} km/h) exceeds Safe System "
            f"recommendation ({ssl} km/h) for this {road_class} "
            f"in a {land_use} area by {speed_limit - ssl:.0f} km/h."
        )
    if f85 > ssl:
        parts.append(
            f"85% of vehicles travel at {f85:.0f} km/h — "
            f"{f85 - ssl:.0f} km/h above the survivable impact speed "
            f"({ssl} km/h) for this road context."
        )
    if vru > 0.6:
        parts.append(
            "This segment has high VRU exposure. "
            "Vulnerable road users face elevated risk at current speeds."
        )
    if not parts:
        return "Speed limit is broadly consistent with Safe System principles."
    return " ".join(parts)


def compute_roadsense_sss(
    a_score: float | pd.Series,
    b_score: float | pd.Series,
    c_score: float | pd.Series,
    weights: dict[str, float] | None = None,
) -> float | pd.Series:
    """RoadSense 3-module composite: SSS = w_A * A + w_B * B + w_C * C."""
    w = weights or MODULE_WEIGHTS
    return (w["module_a"] * a_score + w["module_b"] * b_score + w["module_c"] * c_score)



def score_dataframe_4component(df: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Apply 4-component composite scoring to a DataFrame.

    Expects columns: SpeedLimit, F85thPercentileSpeed, RoadClass, LandUse,
    RankedPercentile. Adds vru_risk_score, speed_safety_score, priority_class,
    score_explanation.

    Parameters
    ----------
    weights : dict, optional
        Override default component weights. Keys: limit_misalignment,
        operating_speed, vru_exposure, volume. Values must sum to 1.0.
        Example: {"limit_misalignment": 0.20, "operating_speed": 0.30,
                  "vru_exposure": 0.35, "volume": 0.15}
    """
    df = df.copy()
    df["safe_system_limit"] = df.apply(
        lambda r: get_safe_system_limit(r["RoadClass"], r["LandUse"]), axis=1
    )
    df["vru_risk_score"] = df.apply(
        lambda r: compute_vru_risk(
            r["RoadClass"], r["LandUse"], r["F85thPercentileSpeed"],
            near_school=r.get("near_school", False),
            near_market=r.get("near_market", False),
            high_ptw_area=r.get("high_ptw_area", False),
        ),
        axis=1,
    )
    df["speed_safety_score"] = df.apply(
        lambda r: compute_composite_score(
            r["SpeedLimit"], r["F85thPercentileSpeed"],
            r["RoadClass"], r["LandUse"], r["RankedPercentile"],
            r["vru_risk_score"], weights=weights,
        ),
        axis=1,
    )
    df["limit_gap"] = df["SpeedLimit"] - df["safe_system_limit"]
    df["operating_gap"] = df["F85thPercentileSpeed"] - df["safe_system_limit"]
    priority_results = df["speed_safety_score"].apply(classify_priority).tolist()
    df["priority_class"] = [r[0] for r in priority_results]
    df["priority_colour"] = [r[1] for r in priority_results]
    df["score_explanation"] = df.apply(
        lambda r: explain_score(
            r["SpeedLimit"], r["F85thPercentileSpeed"],
            r["RoadClass"], r["LandUse"], r["vru_risk_score"],
        ),
        axis=1,
    )
    return df


def _col(df: pd.DataFrame, adb_name: str, rs_name: str) -> str:
    """Return the column name present in the DataFrame (ADB or RoadSense naming)."""
    return adb_name if adb_name in df.columns else rs_name


def score_dataframe_roadsense(df: pd.DataFrame, module_weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Apply 3-module RoadSense scoring to a DataFrame.

    Accepts both ADB naming (SpeedLimit, F85thPercentileSpeed, RoadClass, LandUse)
    and RoadSense naming (posted_limit, v85, functional_class, urban_rural).
    Adds A_score, B_score, C_score, SSS, risk_tier, score_explanation.

    Parameters
    ----------
    module_weights : dict, optional
        Override default module weights. Keys: module_a, module_b, module_c.
        Values must sum to 1.0.
        Example: {"module_a": 0.40, "module_b": 0.30, "module_c": 0.30}
    """
    df = df.copy()

    sl_col = _col(df, "SpeedLimit", "posted_limit")
    f85_col = _col(df, "F85thPercentileSpeed", "v85")
    rc_col = _col(df, "RoadClass", "functional_class")
    lu_col = _col(df, "LandUse", "urban_rural")

    df["A_score"] = df.apply(
        lambda r: compute_module_a_score(r[sl_col], r[f85_col], r[rc_col], r[lu_col]),
        axis=1,
    )
    df["B_score"] = df.apply(
        lambda r: compute_module_b_score(
            r[rc_col], r[lu_col], r[f85_col],
            ptw_flag=(r[rc_col] in ["trunk", "primary"] and r[f85_col] > 80),
        ),
        axis=1,
    )
    df["C_score"] = df.apply(
        lambda r: compute_module_c_score(r[rc_col], r[lu_col], r[f85_col], r[sl_col]),
        axis=1,
    )
    df["SSS"] = compute_roadsense_sss(df["A_score"], df["B_score"], df["C_score"], weights=module_weights)
    df["safe_system_ref"] = df.apply(
        lambda r: get_safe_system_limit(r[rc_col], r[lu_col]), axis=1
    )
    df["safe_system_gap"] = df[sl_col] - df["safe_system_ref"]
    df["operating_gap"] = df[f85_col] - df["safe_system_ref"]
    risk_data = df["SSS"].apply(classify_priority).tolist()
    df["risk_tier"] = [r[0] for r in risk_data]
    df["risk_colour"] = [r[1] for r in risk_data]
    df["score_explanation"] = df.apply(
        lambda r: explain_score(r[sl_col], r[f85_col], r[rc_col], r[lu_col]),
        axis=1,
    )
    return df

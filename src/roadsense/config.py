"""Thresholds, weights, and defaults for the RoadSense pipeline."""

from pathlib import Path

# Safe System speed thresholds (km/h). Source: WHO 2021, ITF/OECD 2018.
SAFE_SYSTEM_LIMITS: dict[tuple[str, str], int] = {
    ("motorway", "rural"): 110,
    ("motorway", "urban"): 100,
    ("trunk", "rural"): 80,
    ("trunk", "urban"): 50,
    ("primary", "rural"): 70,
    ("primary", "urban"): 50,
    ("secondary", "rural"): 70,
    ("secondary", "urban"): 30,
}

DEFAULT_SAFE_LIMIT: int = 50

# Speed Safety Score component weights
SCORE_WEIGHTS: dict[str, float] = {
    "limit_misalignment": 0.30,
    "operating_speed": 0.30,
    "vru_exposure": 0.25,
    "volume": 0.15,
}

# VRU exposure multipliers
ROAD_CLASS_VRU: dict[str, float] = {
    "motorway": 0.05,
    "trunk": 0.30,
    "primary": 0.60,
    "secondary": 0.90,
}

LAND_USE_VRU: dict[str, float] = {
    "urban": 1.00,
    "rural": 0.40,
}

# Infrastructure gap proxy by road class and land use (0-1)
INFRA_GAP_MAP: dict[tuple[str, str], float] = {
    ("motorway", "urban"): 0.10,
    ("motorway", "rural"): 0.05,
    ("trunk", "urban"): 0.50,
    ("trunk", "rural"): 0.30,
    ("primary", "urban"): 0.70,
    ("primary", "rural"): 0.50,
    ("secondary", "urban"): 0.90,
    ("secondary", "rural"): 0.65,
}

# Priority tier thresholds — iRAP-aligned color scheme
PRIORITY_THRESHOLDS: list[tuple[float, str, str]] = [
    (0.65, "Critical — Immediate Review", "#E24B4A"),
    (0.45, "High — Priority Review", "#EF9F27"),
    (0.25, "Moderate — Scheduled Review", "#97C459"),
]

PRIORITY_DEFAULT: tuple[str, str] = ("Low — Monitor", "#5DCAA5")

# RoadSense 3-module approach weights
MODULE_WEIGHTS: dict[str, float] = {
    "module_a": 0.35,  # Speed alignment
    "module_b": 0.35,  # VRU exposure
    "module_c": 0.30,  # Road environment
}

# Data quality thresholds
MIN_SAMPLE_SIZE: int = 500
MIN_RELIABLE_SPEED: float = 5.0  # km/h; F85 below this is likely data error

# Speed limit imputation defaults when TomTom value is missing
SPEED_LIMIT_DEFAULTS: dict[str, int] = {
    "motorway": 110,
    "trunk": 90,
    "primary": 80,
    "secondary": 60,
}

# ADB columns dropped during cleaning (not used in scoring)
DROP_COLS: list[str] = [
    "RoadLength",
    "Percent_",
    "ForAnalysis",
    "SpeedLimitFloor",
    "NO_OF_Result_Segments",
    "ProvinceID",
    "PercentileBand",
    "InvPercentile",
    "ExcludeFromSpeedSPI",
    "Pass",
    "UrbanPC",
    "subtype",
]

# File paths
BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
RAW_DATA_DIR: Path = BASE_DIR / "data" / "raw"
PROCESSED_DATA_DIR: Path = BASE_DIR / "data" / "processed"
OUTPUT_DIR: Path = BASE_DIR / "outputs"
CONFIG_DIR: Path = BASE_DIR / "configs"

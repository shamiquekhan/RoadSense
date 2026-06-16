"""Module C: street imagery analysis."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import yaml
from loguru import logger
from tqdm import tqdm

TAG_PATH = Path("config/mapillary_tags.yaml")
API_TOKEN = os.getenv("MAPILLARY_API_TOKEN", "")
MAPILLARY_API = "https://graph.mapillary.com"
IMAGE_BUFFER_M = 50


def load_tag_config() -> dict:
    if TAG_PATH.exists():
        return yaml.safe_load(TAG_PATH.read_text(encoding="utf-8")) or {}
    return {"protective_features": [], "high_speed_indicators": []}


TAG_CFG = load_tag_config()
PROTECTIVE_FEATURES = TAG_CFG.get("protective_features", [])
HIGH_SPEED_INDICATORS = TAG_CFG.get("high_speed_indicators", [])


def _bbox_from_latlon(lat: float, lon: float, radius_m: int) -> str:
    delta = radius_m / 111_320
    return f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"


def fetch_mapillary_tags_for_segment(lat: float, lon: float, radius: int = IMAGE_BUFFER_M) -> dict:
    """Fetch image detections near a point from Mapillary API v4."""

    if not API_TOKEN:
        return {}

    params = {
        "access_token": API_TOKEN,
        "fields": "id,detections",
        "bbox": _bbox_from_latlon(lat, lon, radius),
        "limit": 20,
    }
    try:
        response = requests.get(f"{MAPILLARY_API}/images", params=params, timeout=10)
        response.raise_for_status()
        images = response.json().get("data", [])
        feature_counts = {name: 0 for name in PROTECTIVE_FEATURES + HIGH_SPEED_INDICATORS}
        for image in images:
            for detection in image.get("detections", {}).get("data", []):
                tag = detection.get("value", "")
                if tag in feature_counts:
                    feature_counts[tag] += 1
        return feature_counts
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning(f"Mapillary API error at ({lat:.4f}, {lon:.4f}): {exc}")
        return {}


def score_from_tags(feature_counts: dict) -> tuple[float, float]:
    protective_present = sum(1 for feature in PROTECTIVE_FEATURES if feature_counts.get(feature, 0) > 0)
    max_features = len(PROTECTIVE_FEATURES)
    infrastructure_gap = 1.0 - (protective_present / max_features) if max_features else 0.5
    high_speed_count = sum(feature_counts.get(feature, 0) for feature in HIGH_SPEED_INDICATORS)
    high_speed_flag = 1.0 if high_speed_count > 0 else 0.0
    return round(infrastructure_gap, 4), high_speed_flag


def score_from_precomputed_tags(segment_id: str, mapillary_data: dict) -> tuple[float, float]:
    segment_tags = mapillary_data.get(segment_id, {})
    return score_from_tags(segment_tags)


def clip_score_image(image_path: str) -> float:
    """Fallback CLIP zero-shot classification for a street image."""

    try:
        import open_clip
        import torch
        from PIL import Image

        model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
        tokenizer = open_clip.get_tokenizer("ViT-B-32")
        model.eval()

        safe_prompts = [
            "a street with a footpath and pedestrian crossing",
            "a road with bike lanes and street lighting",
            "a well-marked residential street with low traffic",
        ]
        risky_prompts = [
            "a high-speed road with no footpath or crossing",
            "a wide arterial road with no pedestrian infrastructure",
            "a rural highway with no sidewalk or lighting",
        ]

        image = preprocess(Image.open(image_path)).unsqueeze(0)
        text = tokenizer(safe_prompts + risky_prompts)
        with torch.no_grad():
            image_features = model.encode_image(image)
            text_features = model.encode_text(text)
            probabilities = (image_features @ text_features.T).softmax(dim=-1)[0]

        safe_probability = probabilities[: len(safe_prompts)].sum().item()
        risky_probability = probabilities[len(safe_prompts) :].sum().item()
        return round(risky_probability / (safe_probability + risky_probability + 1e-9), 4)
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning(f"CLIP scoring failed for {image_path}: {exc}")
        return 0.5


def score_dataframe(gdf: gpd.GeoDataFrame, mapillary_json: str = "data/raw/mapillary/detections.json", use_api: bool = False) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    precomputed = {}
    if Path(mapillary_json).exists():
        precomputed = json.loads(Path(mapillary_json).read_text(encoding="utf-8"))

    infra_gaps: list[float] = []
    hs_flags: list[float] = []
    coverage_flag: list[bool] = []

    utm_crs = gdf.estimate_utm_crs()
    centroids = gdf.to_crs(utm_crs).geometry.centroid.to_crs("EPSG:4326")

    for idx, row in tqdm(gdf.iterrows(), total=len(gdf), desc="Module C"):
        segment_id = row["segment_id"]
        if segment_id in precomputed:
            infrastructure_gap, high_speed_flag = score_from_precomputed_tags(segment_id, precomputed)
            coverage_flag.append(True)
        elif use_api and API_TOKEN:
            centroid = centroids.iloc[list(gdf.index).index(idx)]
            tags = fetch_mapillary_tags_for_segment(centroid.y, centroid.x)
            infrastructure_gap, high_speed_flag = score_from_tags(tags)
            coverage_flag.append(bool(tags))
        else:
            infrastructure_gap, high_speed_flag = 0.5, 0.0
            coverage_flag.append(False)

        infra_gaps.append(infrastructure_gap)
        hs_flags.append(high_speed_flag)

    gdf["infrastructure_gap"] = infra_gaps
    gdf["imagery_scene_class"] = ["high_speed_context" if value > 0 else "mixed_or_unknown" for value in hs_flags]
    gdf["imagery_coverage"] = coverage_flag
    gdf["C_score"] = (gdf["infrastructure_gap"] * (1 + 0.25 * pd.Series(hs_flags, index=gdf.index))).clip(upper=1.0).round(4)
    return gdf


def run(
    input_path: str = "data/processed/segments_master.gpkg",
    output_path: str = "data/processed/segments_master.gpkg",
    mapillary_json: str = "data/raw/mapillary/detections.json",
    use_api: bool = False,
) -> gpd.GeoDataFrame:
    logger.info("Module C: Street Imagery Analysis")
    gdf = gpd.read_file(input_path, layer="segments")
    scored = score_dataframe(gdf, mapillary_json=mapillary_json, use_api=use_api)
    scored.to_file(output_path, driver="GPKG", layer="segments")
    logger.success("Module C complete")
    return scored


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RoadSense Module C.")
    parser.add_argument("--input-path", default="data/processed/segments_master.gpkg")
    parser.add_argument("--output-path", default="data/processed/segments_master.gpkg")
    parser.add_argument("--mapillary-json", default="data/raw/mapillary/detections.json")
    parser.add_argument("--use-api", action="store_true")
    args = parser.parse_args()
    run(args.input_path, args.output_path, args.mapillary_json, args.use_api)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""OSM proximity enrichment for VRU risk scoring.

Two approaches:
1. **GeoFabrik PBF + pyrosm** (preferred) — download OSM extracts, extract POIs
   locally, spatial join via gpd.sjoin.  Fast, no rate limits, works offline.
2. **Overpass API** (fallback) — queries overpass-api.de per segment.  Respects
   rate limiting; intended for spot-checking or when PBF files are unavailable.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from loguru import logger
from shapely.geometry import Point

# ── POI tag definitions ──────────────────────────────────────────────
# Each entry maps to a column on the enriched output.
POI_DEFINITIONS: dict[str, list[dict[str, str]]] = {
    "school_count": [{"amenity": "school"}, {"amenity": "university"}, {"amenity": "college"}],
    "clinic_count": [{"amenity": "clinic"}, {"amenity": "hospital"}, {"amenity": "doctors"}],
    "market_count": [{"amenity": "marketplace"}, {"shop": "supermarket"}, {"shop": "mall"}],
    "bus_stop_count": [{"highway": "bus_stop"}, {"amenity": "bus_station"}],
}

BUFFER_METERS: int = 200

# ── pyrosm tag filters ───────────────────────────────────────────────
PYROSM_FILTERS: dict[str, Any] = {
    "amenity": ["school", "university", "college", "clinic", "hospital",
                "doctors", "marketplace", "bus_station"],
    "shop": ["supermarket", "mall"],
    "highway": ["bus_stop"],
}

# ── Overpass API (fallback) ──────────────────────────────────────────

OVERPASS_ENDPOINT: str = "https://overpass-api.de/api/interpreter"
REQUEST_DELAY: float = 2.0


def _build_overpass_query(lat: float, lon: float, radius: int) -> str:
    tags = []
    for variants in POI_DEFINITIONS.values():
        for v in variants:
            for k, val in v.items():
                tags.append(f'node[{k}={val}](around:{radius},{lat},{lon});')
    return f"[out:json];({''.join(tags)});out count;"


def _fetch_poi_counts(
    lat: float, lon: float, radius: int = BUFFER_METERS
) -> dict[str, int]:
    import urllib.error
    import urllib.request

    query = _build_overpass_query(lat, lon, radius)
    data = f"data={urllib.request.quote(query)}".encode()
    try:
        req = urllib.request.Request(OVERPASS_ENDPOINT, data=data)
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        logger.warning(f"Overpass request failed at ({lat:.4f}, {lon:.4f}): {exc}")
        return {key: 0 for key in POI_DEFINITIONS}

    elements = result.get("elements", [])
    counts = {key: 0 for key in POI_DEFINITIONS}
    for el in elements:
        tags = el.get("tags", {})
        for col_name, variants in POI_DEFINITIONS.items():
            for variant in variants:
                if all(tags.get(k) == v for k, v in variant.items()):
                    counts[col_name] += 1
                    break
    return counts


def enrich_with_osm_pois(
    gdf: gpd.GeoDataFrame,
    buffer_m: int = BUFFER_METERS,
    use_api: bool = True,
    cache_path: str | Path | None = None,
) -> gpd.GeoDataFrame:
    """Enrich road network with OSM POI counts via Overpass API (fallback).

    See `enrich_with_pyrosm()` for the preferred approach.
    """
    gdf = gdf.copy()
    for col in POI_DEFINITIONS:
        gdf[col] = 0

    if not use_api:
        logger.info("OSM API disabled — all POI counts default to 0")
        gdf["poi_count"] = 0
        gdf["near_school"] = False
        gdf["near_market"] = False
        return gdf

    cache: dict[str, dict[str, int]] = {}
    cache_file = Path(cache_path) if cache_path else None
    if cache_file and cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
            logger.info(f"Loaded {len(cache)} cached OSM lookups")
        except Exception:
            cache = {}

    if gdf.crs and not gdf.crs.is_geographic:
        geo = gdf.to_crs("EPSG:4326")
    else:
        geo = gdf
    centroids = geo.geometry.centroid

    n = len(gdf)
    for idx in gdf.index:
        lat, lon = centroids[idx].y, centroids[idx].x
        seg_id = str(idx)

        if seg_id in cache:
            counts = cache[seg_id]
        else:
            counts = _fetch_poi_counts(lat, lon, buffer_m)
            cache[seg_id] = counts
            if n > 10 and idx % 10 == 0:
                logger.info(f"  OSM enrichment: {idx + 1}/{n} segments")
            time.sleep(REQUEST_DELAY)

        for col, val in counts.items():
            gdf.at[idx, col] = val

    gdf["poi_count"] = sum(gdf[col] for col in POI_DEFINITIONS)
    gdf["near_school"] = gdf["school_count"] > 0
    gdf["near_market"] = gdf["market_count"] > 0

    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        logger.info(f"Saved {len(cache)} OSM lookups to cache")

    logger.info(f"OSM enrichment complete. Mean POIs per segment: {gdf['poi_count'].mean():.1f}")
    return gdf


def enrich_with_osm_precomputed(
    gdf: gpd.GeoDataFrame,
    cache_path: str | Path,
) -> gpd.GeoDataFrame:
    """Apply precomputed OSM enrichment from a cache file (no API calls)."""
    cache_file = Path(cache_path)
    if not cache_file.exists():
        logger.warning(f"OSM cache not found: {cache_path}")
        return enrich_with_osm_pois(gdf, use_api=False)

    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    for col in POI_DEFINITIONS:
        gdf[col] = 0

    for idx in gdf.index:
        seg_id = str(idx)
        counts = cache.get(seg_id, {k: 0 for k in POI_DEFINITIONS})
        for col, val in counts.items():
            gdf.at[idx, col] = val

    gdf["poi_count"] = sum(gdf[col] for col in POI_DEFINITIONS)
    gdf["near_school"] = gdf["school_count"] > 0
    gdf["near_market"] = gdf["market_count"] > 0
    logger.info(f"Applied precomputed OSM enrichment from cache ({len(cache)} lookups)")
    return gdf


# ── GeoFabrik PBF + pyrosm (preferred) ──────────────────────────────


def extract_pois_pyrosm(pbf_path: str | Path) -> gpd.GeoDataFrame:
    """Extract POIs from a GeoFabrik PBF file using pyrosm.

    Returns a GeoDataFrame of tagged POI points in EPSG:4326.
    """
    import pyrosm

    osm = pyrosm.OSM(str(pbf_path))
    pois = osm.get_pois(custom_filter=PYROSM_FILTERS)
    if pois is None or pois.empty:
        logger.warning(f"No POIs found in {pbf_path}")
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")
    pois = pois.to_crs("EPSG:4326")
    logger.info(f"  Extracted {len(pois)} POIs from {Path(pbf_path).name}")
    return pois


def _classify_pois(pois: gpd.GeoDataFrame, tags: dict[str, list[dict[str, str]]]) -> gpd.GeoDataFrame:
    """Add per-category boolean columns to a POI GeoDataFrame."""
    for cat_name, variants in tags.items():
        mask = pd.Series(False, index=pois.index)
        for variant in variants:
            sub = pd.Series(True, index=pois.index)
            for k, v in variant.items():
                if k in pois.columns:
                    sub &= pois[k] == v
                else:
                    sub = pd.Series(False, index=pois.index)
                    break
            mask |= sub
        pois[cat_name] = mask
    return pois


def enrich_with_pyrosm(
    gdf: gpd.GeoDataFrame,
    pbf_paths: list[str | Path],
    buffer_m: int = BUFFER_METERS,
    poi_tags: dict[str, list[dict[str, str]]] | None = None,
) -> gpd.GeoDataFrame:
    """Enrich road network with OSM POIs from GeoFabrik PBF files.

    This is the preferred enrichment method.  Extracts POIs locally with
    pyrosm, tags each by category, does a single spatial join per category.
    No rate limits, works offline, ~10 minutes for 14k segments.
    """
    tags = poi_tags or POI_DEFINITIONS
    gdf = gdf.copy()

    for col in tags:
        gdf[col] = 0

    all_pois: list[gpd.GeoDataFrame] = []
    for pbf_path in pbf_paths:
        logger.info(f"Processing PBF: {pbf_path}")
        pois = extract_pois_pyrosm(pbf_path)
        if not pois.empty:
            all_pois.append(pois)

    if not all_pois:
        logger.warning("No POIs found in any PBF file — all counts default to 0")
        return _finalise_enrichment(gdf, tags)

    pois = pd.concat(all_pois, ignore_index=True)
    pois = _classify_pois(pois, tags)

    # Buffer segments once in projected CRS
    gdf_proj = gdf.to_crs("EPSG:3857")
    buffered = gdf_proj[["geometry"]].copy()
    buffered["geometry"] = buffered.geometry.buffer(buffer_m)

    for cat_name in tags:
        cat_pois = pois[pois[cat_name]].copy()
        if cat_pois.empty:
            continue
        cat_pois_proj = cat_pois[["geometry"]].to_crs("EPSG:3857")
        cat_pois_proj["_dummy"] = 1

        joined = gpd.sjoin(
            buffered, cat_pois_proj, how="left", predicate="intersects",
        )
        counts = joined.groupby(joined.index)["_dummy"].sum()
        gdf[cat_name] = counts.reindex(gdf.index, fill_value=0).astype(int)

    return _finalise_enrichment(gdf, tags)


def _finalise_enrichment(
    gdf: gpd.GeoDataFrame, tags: dict[str, list[dict[str, str]]]
) -> gpd.GeoDataFrame:
    gdf["poi_count"] = sum(gdf[col] for col in tags)
    gdf["near_school"] = gdf.get("school_count", pd.Series(0, index=gdf.index)) > 0
    gdf["near_market"] = gdf.get("market_count", pd.Series(0, index=gdf.index)) > 0

    school_pct = gdf["near_school"].mean() * 100
    market_pct = gdf["near_market"].mean() * 100
    logger.info(f"pyrosm enrichment complete. "
                f"Segments near schools: {school_pct:.1f}%, "
                f"near markets: {market_pct:.1f}%")
    return gdf


# Improved urban/rural classification using OSM land use polygons.
# Overrides GRUMP classification when OSM built-area data is available.

URBAN_LAND_USE: set[str] = {
    "residential", "commercial", "retail", "industrial",
    "mixed", "institutional", "religious", "cemetery",
    "construction", "brownfield", "depot", "garages",
    "hospital", "school", "university", "college",
    "recreation_ground", "village_green",
}

RURAL_LAND_USE: set[str] = {
    "farmland", "farmyard", "forest", "meadow", "orchard",
    "vineyard", "scrub", "grass", "heath", "wood",
    "plant_nursery", "greenhouse_horticulture",
    "aquaculture", "salt_pond", "quarry",
}


def extract_land_use_pyrosm(pbf_path: str | Path) -> gpd.GeoDataFrame:
    """Extract land use polygons from a GeoFabrik PBF file using pyrosm."""
    import pyrosm

    osm = pyrosm.OSM(str(pbf_path))
    landuse = osm.get_landuse()
    if landuse is None or landuse.empty:
        logger.warning(f"No land use polygons found in {pbf_path}")
        return gpd.GeoDataFrame(columns=["geometry", "landuse"], geometry="geometry", crs="EPSG:4326")

    landuse = landuse.to_crs("EPSG:4326")
    lu_col = next((c for c in ["landuse", "land_use", "LU"] if c in landuse.columns), None)
    if lu_col:
        landuse["landuse"] = landuse[lu_col].astype(str).str.lower().str.strip()
    landuse = landuse[landuse["landuse"].isin(URBAN_LAND_USE | RURAL_LAND_USE)].copy()
    logger.info(f"  Extracted {len(landuse)} land use polygons from {Path(pbf_path).name}")
    return landuse


def improve_urban_classification(
    gdf: gpd.GeoDataFrame,
    pbf_paths: list[str | Path],
    buffer_m: int = 200,
) -> gpd.GeoDataFrame:
    """Override GRUMP LandUse with OSM land use proximity.

    For each road segment, checks OSM land use polygons within `buffer_m`.
    Majority urban land use → classify URBAN. Majority rural → RURAL.
    Mixed or no data → fall back to original LandUse value.
    Adds `urban_classification_confidence` (0-1) and `urban_source`.
    """
    gdf = gdf.copy()
    gdf["urban_classification_confidence"] = 0.0
    gdf["urban_source"] = "GRUMP"

    all_landuse: list[gpd.GeoDataFrame] = []
    for pbf_path in pbf_paths:
        logger.info(f"Processing land use PBF: {pbf_path}")
        lu = extract_land_use_pyrosm(pbf_path)
        if not lu.empty:
            all_landuse.append(lu)

    if not all_landuse:
        logger.warning("No land use data extracted — keeping GRUMP classification")
        return gdf

    landuse = pd.concat(all_landuse, ignore_index=True)
    landuse_proj = landuse.to_crs("EPSG:3857")
    landuse_proj["urban_flag"] = landuse_proj["landuse"].isin(URBAN_LAND_USE).astype(int)

    gdf_proj = gdf.to_crs("EPSG:3857")
    buffered = gdf_proj[["geometry"]].copy()
    buffered["geometry"] = buffered.geometry.buffer(buffer_m)
    buffered["idx"] = range(len(buffered))

    joined = gpd.sjoin(buffered, landuse_proj, how="left", predicate="intersects")
    urban_pct = joined.groupby("idx")["urban_flag"].mean()
    count = joined.groupby("idx")["urban_flag"].count()

    for idx in gdf.index:
        u = urban_pct.get(idx, None)
        c = count.get(idx, None)
        if c is None or c == 0:
            continue
        confidence = min(c / 10.0, 1.0)
        if u >= 0.5:
            gdf.at[idx, "LandUse"] = "URBAN"
            gdf.at[idx, "urban_source"] = "OSM"
        elif u <= 0.3:
            gdf.at[idx, "LandUse"] = "RURAL"
            gdf.at[idx, "urban_source"] = "OSM"
        else:
            gdf.at[idx, "urban_source"] = "mixed"
        gdf.at[idx, "urban_classification_confidence"] = round(confidence, 2)

    changed = (gdf["urban_source"] == "OSM").sum()
    logger.info(f"Urban classification improved: {changed}/{len(gdf)} segments "
                f"reclassified from GRUMP via OSM land use")
    return gdf

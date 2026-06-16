# RoadSense

RoadSense is an AI-powered road safety analytics platform that checks whether posted speed limits are genuinely protecting road users or simply numbers on a sign. It combines GPS probe data, road network geometry, street-level imagery, and contextual layers such as schools, markets, and population density to build a segment-by-segment view of risk and produce a transparent Speed Safety Score for policy action.

The score blends three signals: how far the posted limit deviates from observed operating speed, how exposed vulnerable road users are at that location, and what the physical road environment looks like on the ground. Each segment is classified into four risk tiers: Critical, High, Medium, and Low, with plain-language explanations designed for transport ministries and other non-technical decision-makers.

## Pipeline Overview

![RoadSense pipeline overview](docs/architecture.svg)

## Scoring Approaches

RoadSense implements two independent scoring methodologies:

### 4-Component Composite Score

A four-factor weighted score combining:

| Component | Factor | Weight | Description |
|---|---|---|---|
| **A — Limit Misalignment** | How far the posted limit exceeds the Safe System threshold | 30% | `max(SpeedLimit - SSL, 0) / 40`, capped at 1.0 |
| **B — Operating Speed Risk** | How far actual traffic (F85) exceeds the Safe System threshold | 30% | `max(F85 - SSL, 0) / 40`, capped at 1.0 |
| **C — VRU Exposure** | Pedestrian fatality risk × road class / land use exposure | 25% | Logistic fatality curve (ITF/OECD 2018) × VRU base score |
| **D — Volume** | Ranked traffic volume percentile | 15% | Normalised `RankedPercentile / 100` |

**Score = 0.30A + 0.30B + 0.25C + 0.15D** (range 0–1, higher = worse).

Safe System limits (SSL) are drawn from WHO 2021 and ITF/OECD 2018 recommendations per (road_class, land_use) pair — e.g. secondary urban roads have SSL = 30 km/h.

### 3-Module RoadSense Score

Three independent modules that mirror the 4-component factors but are computed differently:

| Module | Signal | Weight | Approach |
|---|---|---|---|
| **A — Speed Alignment** | Limit gap + operating speed gap | 35% | Average of limit misalignment and operating speed risk |
| **B — VRU Exposure** | Land use × road class × speed risk + PTW bonus | 35% | Same fatality curve; adds PTW flag on trunk/primary roads with F85 > 80 km/h |
| **C — Road Environment** | Infrastructure gap proxy + speed mismatch | 30% | Looks up infra gap by (road_class, land_use); adds speed mismatch penalty |

**SSS = 0.35A + 0.35B + 0.30C** (range 0–1, higher = worse).

Both approaches classify segments into four risk tiers:

| Tier | Score Range | Action |
|---|---|---|
| Critical — Immediate Review | ≥ 0.65 | Immediate Safe System intervention |
| High — Priority Review | 0.45 – 0.65 | Schedule priority review |
| Moderate — Scheduled Review | 0.25 – 0.45 | Monitor and plan upgrades |
| Low — Monitor | < 0.25 | Maintain current approach |

## Setup

Requires Python 3.10+.

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate    # Windows

# Install the package and dependencies
pip install -e .
pip install -r requirements-dev.txt  # optional, for development
```

> **Note:** The ADB challenge data package is NDA-protected and not included in this repository. Place your GeoJSON/GPKG files in `data/raw/`.

## Run

The recommended entrypoint runs both approaches:

```bash
python run_pipeline.py --approach both
```

Other options:

```bash
# 4-component score only
python run_pipeline.py --approach 4component

# RoadSense 3-module score only
python run_pipeline.py --approach roadsense

# Include OSM enrichment (schools, markets) via Overpass API
python run_pipeline.py --approach 4component --osm

# Enrich via local OSM PBF file (faster, offline)
python run_pipeline.py --approach 4component --pbf /path/to/region.osm.pbf

# View the output map
python run_pipeline.py --approach 4component --serve
```

Or use the Makefile:

```bash
make run          # 4-component only
make run-both     # both approaches
make serve        # 4-component + HTTP server
```

## Outputs

Outputs are written to `outputs/`:

| File | Description |
|---|---|
| `speed_safety_scores.csv` | 4-component scored segments (tabular) |
| `speed_safety_scores.gpkg` | 4-component scored segments (geospatial) |
| `speed_safety_scores_map.html` | Interactive folium map for 4-component results |
| `roadsense_scores.csv` | 3-module scored segments (tabular) |
| `roadsense_scores.gpkg` | 3-module scored segments (geospatial) |
| `roadsense_scores_map.html` | Interactive folium map for 3-module results |

**Interactive maps:**
- [4-Component Map](https://shamiquekhan.github.io/RoadSense/4component_map.html) (GitHub Pages)
- [RoadSense Map](https://shamiquekhan.github.io/RoadSense/roadsense_map.html) (GitHub Pages)

## Methodology

RoadSense follows a five-stage pipeline: data ingestion and cleaning, spatial preprocessing, three parallel analysis modules (or 4-component composite scoring), priority tier classification, and geospatial visualisation.

### Data Pipeline

1. **Ingestion** — Loads ADB GPS probe datasets for Thailand and Maharashtra; filters valid sections with sufficient sample size (≥500).
2. **Cleaning** — Drops invalid records, imputes missing speed limits by road class, removes segments with F85 < 5 km/h (likely data errors).
3. **Scoring** — Applies either 4-component composite or 3-module RoadSense approach per segment.
4. **Classification** — Maps numeric scores to four risk tiers (Critical / High / Moderate / Low) with plain-language explanations.
5. **Export & Visualise** — Saves GeoJSON, GeoPackage, CSV, and an interactive folium map.

### Safe System Reference Speeds

Safe System limits are drawn from WHO (2021) *Global Plan for the Decade of Action for Road Safety* and ITF/OECD (2018) *Speed and Crash Risk*:

| Road Class | Urban (km/h) | Rural (km/h) |
|---|---|---|
| Motorway | 100 | 110 |
| Trunk | 50 | 80 |
| Primary | 50 | 70 |
| Secondary | 30 | 70 |

Where no match is found, a default of 50 km/h is applied.

## Data Sources and Citations

This project uses the following data sources:

| Dataset | Source | Licence | Citation |
|---|---|---|---|
| ADB Challenge GPS Probe Data | ADB AI for Safer Roads 2026 challenge data package | NDA / challenge terms | Asian Development Bank. (2026). *AI for Safer Roads 2026 — Speed and Volume Data for Thailand and Maharashtra*. ADB Challenge Dataset. |
| OpenStreetMap Road Network | OpenStreetMap via OSMnx / pyrosm | ODbL 1.0 | OpenStreetMap contributors. (2026). Planet dump. https://planet.openstreetmap.org |
| Mapillary Street-Level Imagery | Mapillary API / open-clip-torch | CC-BY-SA 4.0 | Mapillary. (2026). Mapillary street-level imagery and computer vision detections. https://www.mapillary.com |
| Safe System Reference Speeds | WHO / iRAP / ITF-OECD | Open access | World Health Organization. (2021). *Global Plan for the Decade of Action for Road Safety 2021–2030*. Geneva: WHO. https://www.who.int/publications/i/item/9789240032817 |
| Pedestrian Fatality Risk Curve | ITF/OECD | Open access | ITF/OECD. (2018). *Speed and Crash Risk*. International Transport Forum Research Report. Paris: OECD Publishing. https://www.itf-oecd.org/speed-and-crash-risk |
| Points of Interest (Schools, Markets) | OpenStreetMap / Overpass API | ODbL 1.0 | OpenStreetMap contributors. See above. |

## Licence

MIT License. See [LICENSE](LICENSE).

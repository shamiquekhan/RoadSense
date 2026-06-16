# RoadSense

RoadSense is an AI-powered road safety analytics platform that checks whether posted speed limits are genuinely protecting road users or simply numbers on a sign. It combines GPS probe data, road network geometry, street-level imagery, and contextual layers such as schools, markets, and population density to build a segment-by-segment view of risk and produce a transparent Speed Safety Score for policy action.

The score blends three signals: how far the posted limit deviates from observed operating speed, how exposed vulnerable road users are at that location, and what the physical road environment looks like on the ground. Each segment is classified into four risk tiers: Critical, High, Medium, and Low, with plain-language explanations designed for transport ministries and other non-technical decision-makers.

## Pipeline Overview

![RoadSense pipeline overview](docs/architecture.svg)

## Setup

Create and activate a Python environment, then install the dependencies:

```bash
pip install -r requirements.txt
```

If you prefer conda, use `environment.yml` instead.

## Run

The recommended run order is:

```bash
python -m src.utils audit
python -m src.preprocessing
python -m src.module_a
python -m src.module_b
python -m src.module_c
python -m src.scoring --config config/scoring_weights.yaml
python -m src.evaluation
python -m src.visualise
```

The composite scoring entrypoint is:

```bash
python src/scoring.py --config config/scoring_weights.yaml
```

## Outputs

- `data/processed/segments_master.gpkg` - master segment table after preprocessing
- `outputs/all_segments_scored.gpkg` - full scored dataset
- `outputs/geojson/all_segments_scored.geojson` - web-friendly scored export
- `outputs/geojson/priority_segments_top100.geojson` - top-priority export for GIS tools
- `outputs/maps/roadsense_priority_map.html` - interactive review map
- `docs/evaluation_results.md` - evaluation summary and validation notes

## Methodology

RoadSense follows a five-stage pipeline: data ingestion, spatial preprocessing, three parallel analysis modules, composite scoring, and geospatial visualisation. Module A measures speed alignment against observed operating speed and Safe System reference speeds. Module B estimates vulnerable road user exposure using attractors, population density, conflict potential, land use, and powered two-wheeler context. Module C uses Mapillary detections or a CLIP fallback to estimate protective infrastructure coverage.

Those signals are normalised and combined into a single Speed Safety Score per segment. The scoring is intentionally transparent so the same inputs always produce the same outputs, and so the assumptions behind each step can be documented and reviewed. Evaluation includes internal consistency checks, spatial autocorrelation, benchmark validation, and sensitivity testing.

## Data Sources and Citations

Add the exact citations for each project dataset here, including the ADB challenge data, road network source, GPS probe source, imagery source, and contextual layers such as schools, markets, and population density.

Suggested citation groups:
- ADB Challenges data package
- OpenStreetMap / OSMnx-derived road network layers
- Mapillary imagery and machine learning tags
- iRAP or WHO Safe System reference speeds
- Local census, land use, and point-of-interest datasets

## Licence

MIT License. See [LICENSE](LICENSE).

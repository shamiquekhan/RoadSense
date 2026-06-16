# RoadSense — Quick Start

## Prerequisites

- Python 3.11+
- ~500 MB free disk space (GeoJSON outputs)
- Internet connection (for OSM enrichment, optional)

## Installation

```bash
# Clone the repo
git clone https://github.com/shamique/roadsense.git
cd roadsense

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# Install package and dev dependencies
pip install -e .
pip install -r requirements-dev.txt
```

## Run the Pipeline

### 4-Component Pipeline (root methodology)

```bash
python run_pipeline.py --approach 4component
```

This produces:
- `outputs/speed_safety_scores.csv` — scoring table
- `outputs/speed_safety_scores.gpkg` — GeoPackage with geometry
- `outputs/speed_safety_scores.geojson` — GeoJSON
- `outputs/speed_safety_scores_map.html` — interactive Folium map

### RoadSense 3-Module Pipeline (experimental)

```bash
python run_pipeline.py --approach roadsense
```

### Both pipelines

```bash
python run_pipeline.py --approach both
```

### With OSM enrichment (schools, markets, clinics)

```bash
python run_pipeline.py --approach 4component --osm
```

**Note**: OSM enrichment queries the Overpass API with a 2-second delay per request. For 14,384 segments this takes ~8 hours. Results are cached in `outputs/osm_cache.json` for reuse.

### Serve the map via HTTP

```bash
python run_pipeline.py --approach 4component --serve
```

Opens a local HTTP server on port 8080 serving the generated map.

## View the Results

1. Open `outputs/speed_safety_scores_map.html` in a browser
2. Click any road segment to see its score, speed data, and explanation
3. Use the layer control to toggle the basemap
4. The legend in the bottom-right shows the four priority tiers

## Run Tests

```bash
# All tests with coverage
make test

# Or directly
python -m pytest tests/ -v --cov=src
```

24 unit tests covering scoring, data loading, priority classification, and explanations. Minimum coverage threshold: 30%.

## Format and Lint

```bash
make format    # auto-format with black
make lint      # check with black + flake8
```

## Using the Makefile

| Command | Action |
|---|---|
| `make setup` | Install package + copy `.env.example` |
| `make install` | Install package + dev dependencies |
| `make test` | Run tests with coverage |
| `make lint` | Check code style |
| `make format` | Auto-format with black |
| `make run` | Run 4-component pipeline |
| `make run-roadsense` | Run RoadSense 3-module pipeline |
| `make run-both` | Run both pipelines |
| `make run-osm` | Run with OSM enrichment |
| `make serve` | Run and serve map via HTTP |
| `make clean` | Remove outputs and caches |

## Configuration

All tunable parameters are in `src/roadsense/config.py`:
- Safe System speed thresholds
- Scoring weights (each component)
- Priority tier boundaries
- VRU exposure multipliers
- Data quality thresholds

YAML overrides go in `configs/train.yaml`.

## Understanding the Output

### Score interpretation (0–1)

| Range | Tier | What it means |
|---|---|---|
| ≥ 0.65 | Critical | Speed limit severely misaligned — immediate review |
| ≥ 0.45 | High | Significant safety concern — priority review |
| ≥ 0.25 | Moderate | Some misalignment — scheduled review |
| < 0.25 | Low | Speed limit broadly appropriate — monitor |

### Key columns in the scoring table

| Column | Description |
|---|---|
| `segment_id` | Unique road section identifier |
| `SpeedLimit` / `posted_limit` | Posted speed limit (km/h) |
| `F85thPercentileSpeed` / `v85` | 85th percentile operating speed |
| `safe_system_limit` / `safe_system_ref` | Safe System recommended limit |
| `limit_gap` | Posted minus safe system limit |
| `operating_gap` | F85 minus safe system limit |
| `speed_safety_score` / `SSS` | Final 0–1 score |
| `priority_class` / `risk_tier` | Priority tier label |
| `score_explanation` | Plain-language explanation |

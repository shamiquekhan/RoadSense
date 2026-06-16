# RoadSense — Project Structure

## Top-level layout

```
roadsense/
├── run_pipeline.py              # Primary entry point
├── Makefile                     # install, test, run, lint, clean
├── pyproject.toml               # Package metadata and dependencies
├── requirements.txt             # Runtime dependencies
├── requirements-dev.txt         # Dev dependencies
├── .env.example                 # Environment variable template
├── .gitignore
├── LICENSE
│
├── src/roadsense/
│   ├── config.py                # Thresholds, weights, paths
│   ├── scoring.py               # Speed Safety Score computation
│   ├── pipeline.py              # Orchestration: load → score → export
│   ├── data/
│   │   ├── loader.py            # GeoJSON loading and cleaning
│   │   └── osm_enrich.py        # OSM POI and land-use enrichment
│   ├── evaluation/
│   │   └── metrics.py           # Correlation, sensitivity, Moran's I
│   └── visualisation/
│       └── map.py               # Folium interactive map
│
├── tests/unit/
│   ├── test_scoring.py          # 18 tests
│   └── test_data_loader.py      # 6 tests
│
├── configs/                     # YAML configs (reference only)
├── scripts/                     # download_pbf.sh, batch_score.py
├── data/                        # raw/ (gitignored), pbf/ (gitignored), README.md
├── outputs/                     # Generated scores, maps, GeoJSON (gitignored)
├── experimental/                # Phase 2 modular architecture
└── docs/                        # QUICKSTART.md, HTML maps, index.html
```

## Module responsibilities

| Module | Purpose |
|---|---|
| `config.py` | Single source of truth for thresholds, weights, defaults, and paths |
| `scoring.py` | Core scoring — 4-component and 3-module approaches |
| `pipeline.py` | Loads data, applies scoring, exports results, generates map |
| `data/loader.py` | Loads ADB GeoJSON, applies quality filters, imputes missing data |
| `data/osm_enrich.py` | Extracts POIs and land use from OSM PBF files via pyrosm |
| `evaluation/metrics.py` | Spearman correlation, weight sensitivity, Moran's I |
| `visualisation/map.py` | Folium map with colour-coded segments, popups, budget widget |

## Two scoring approaches

1. **4-Component** (primary) — weights limit misalignment (30%), operating speed (30%), VRU exposure (25%), volume (15%). Thresholds at 0.65/0.45/0.25.

2. **RoadSense 3-Module** (experimental) — speed alignment (35%), VRU exposure (35%), road environment (30%). Same tier structure.

Run both with `python run_pipeline.py --approach both`.

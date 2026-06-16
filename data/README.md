# Data Directory

## Required Input Files

The following files are **NDA-protected** and must be placed manually:

- `raw/ADB_Innovation_Maharashtra.geojson` — Maharashtra road network with speed data
- `raw/ADB_Innovation_Thailand.geojson` — Thailand road network with speed data

These are distributed by ADB / Agilysis to registered challenge participants. Do not commit them to version control.

## Optional Files

- `pbf/thailand-latest.osm.pbf` — OSM extract for Thailand (download from GeoFabrik, ~200MB)
- `pbf/maharashtra-latest.osm.pbf` — OSM extract for Maharashtra (download from GeoFabrik)

Run `scripts/download_pbf.sh` to fetch OSM data automatically.

## Outputs

Generated outputs (scores, maps, GeoJSON) are written to `outputs/`.

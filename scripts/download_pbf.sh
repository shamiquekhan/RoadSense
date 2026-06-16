#!/usr/bin/env bash
# Download GeoFabrik OSM PBF extracts for pyrosm enrichment.
# Usage: bash scripts/download_pbf.sh [output_dir]
set -euo pipefail

OUT="${1:-data/pbf}"
mkdir -p "$OUT"

echo "==> Downloading Thailand OSM extract (~200 MB)..."
wget -c -O "$OUT/thailand-latest.osm.pbf" \
  "https://download.geofabrik.de/asia/thailand-latest.osm.pbf"

echo "==> Downloading Maharashtra OSM extract (~200 MB)..."
wget -c -O "$OUT/maharashtra-latest.osm.pbf" \
  "https://download.geofabrik.de/asia/india/maharashtra-latest.osm.pbf"

echo "==> Done.  Files in $OUT:"
ls -lh "$OUT"/*.osm.pbf

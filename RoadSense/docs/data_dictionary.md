# Data Dictionary

Document all raw and derived datasets here.

## Raw sources
- `gps_probe_*.csv` - operating speeds, posted speed limits, traffic intensity, and segment linkage fields
- `road_network_*.gpkg` - road geometry and baseline network attributes
- `mapillary_*.json` - image metadata and ML detections
- `context_layers_*.gpkg` - schools, markets, population density, land use, PTW indicators

## Derived outputs
- `data/processed/segments_master.gpkg` - master segment table
- `outputs/all_segments_scored.gpkg` - scored segment layer
- `outputs/priority_segments_top100.geojson` - top-priority export
- `outputs/speed_safety_map.html` - interactive map

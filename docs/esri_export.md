# ESRI GIS Sandbox — Export Guide

**Purpose:** Phase 2 of the ADB challenge requires finalists to upload spatial outputs into ADB's enterprise ESRI GIS environment. This document describes how RoadSense outputs map to ESRI-compatible formats and schemas.

---

## Output Files and ESRI Compatibility

| File | Format | ESRI Compatible | Notes |
|---|---|---|---|
| `outputs/speed_safety_scores.gpkg` | GeoPackage | Yes | Native ESRI support via ArcGIS Pro 2.5+ / ArcMap 10.6+ |
| `outputs/speed_safety_scores.geojson` | GeoJSON | Yes | Import via ArcGIS Pro (drag-and-drop) or `arcpy.conversion.JSONToFeatures` |
| `outputs/speed_safety_scores.csv` | CSV with lat/lon | Yes | Add XY data via ArcMap or ArcGIS Pro |
| `outputs/roadsense_scores.gpkg` | GeoPackage | Yes | As above |
| `outputs/roadsense_scores.geojson` | GeoJSON | Yes | As above |

---

## Coordinate System

All RoadSense outputs use **EPSG:4326 (WGS 84)** — latitude/longitude coordinates. This is the standard for web-based GIS and is natively supported by ESRI.

If your ESRI project requires a projected coordinate system, reproject via:

**ArcGIS Pro:** Right-click layer > Properties > Source > Coordinate System > Search for appropriate UTM zone or country-specific projection.

**Python (arcpy):**
```python
import arcpy
arcpy.Project_management(
    "speed_safety_scores.gpkg",
    "speed_safety_scores_utm.gpkg",
    arcpy.SpatialReference(32647)  # UTM zone 47N (covers Thailand, Maharashtra)
)
```

---

## Recommended Geodatabase Schema

When importing into an ESRI file geodatabase, the following field mapping applies:

| Field Name | Type | Length | Description |
|---|---|---|---|
| `segment_id` | Text | 50 | Unique segment identifier |
| `region` | Text | 50 | Country/region name (Thailand, Maharashtra) |
| `RoadClass` | Text | 50 | Functional road classification |
| `LandUse` | Text | 10 | Urban or Rural designation |
| `SpeedLimit` | Double | — | Posted speed limit (km/h) |
| `F85thPercentileSpeed` | Double | — | 85th percentile operating speed (km/h) |
| `safe_system_limit` | Double | — | Safe System reference speed (km/h) |
| `limit_gap` | Double | — | SpeedLimit minus safe_system_limit (km/h) |
| `operating_gap` | Double | — | F85 minus safe_system_limit (km/h) |
| `speed_safety_score` | Double | — | 4-Component composite score (0-1) |
| `SSS` | Double | — | 3-Module composite score (0-1) |
| `vru_risk_score` | Double | — | VRU risk component (0-1) |
| `A_score` | Double | — | Module A: Speed alignment |
| `B_score` | Double | — | Module B: VRU exposure |
| `C_score` | Double | — | Module C: Road environment |
| `priority_class` | Text | 50 | Risk tier label |
| `risk_tier` | Text | 50 | Risk tier label (3-module) |
| `reliability_tier` | Text | 10 | High / Medium / Low |
| `score_explanation` | Text | 500 | Plain-language explanation |
| `Shape_Length` | Double | — | Segment length (meters) |

---

## ArcGIS Pro Quick Start

1. Open ArcGIS Pro and create a new Map project.
2. Drag `outputs/speed_safety_scores.gpkg` from Windows Explorer into the Map pane.
3. Right-click the layer > Symbology > Classify by `priority_class` using unique values.
4. Apply a red-amber-green colour ramp:
   - Critical: `#d32f2f`
   - High: `#f57c00`
   - Moderate: `#fbc02d`
   - Low: `#388e3c`
5. Set transparency based on `reliability_tier`:
   - High: 15% transparent
   - Medium: 45% transparent
   - Low: 70% transparent
6. Enable popups with `score_explanation` field for click-to-inspect.

---

## ESRI Dashboard / StoryMap Integration

For Phase 2, the recommended workflow:

1. **Import GeoPackage** into ArcGIS Pro and publish as a hosted feature layer to ArcGIS Online / Enterprise.
2. **Create an ArcGIS Dashboard** with:
   - A map showing segments colour-coded by risk tier
   - A side panel with counts and length summaries per tier
   - A filter for region, road class, and reliability
3. **Or build an ESRI StoryMap** with:
   - An introductory section explaining the Safe System methodology
   - An embedded interactive map
   - Data tables showing top-20 critical segments
   - Policy recommendations based on score distributions

---

## Python (arcpy) Automation Script

For batch processing multiple regions, the following arcpy script ingests all GPKG outputs:

```python
import arcpy
from pathlib import Path

OUTPUT_DIR = Path("outputs")
GDB = "roadsense_phase2.gdb"

arcpy.CreateFileGDB_management(".", GDB)

for gpkg in OUTPUT_DIR.glob("*.gpkg"):
    name = gpkg.stem
    arcpy.GeoPackageToGeodatabase_management(str(gpkg), GDB)
    print(f"Imported {name} into {GDB}")

print("All layers ready for mapping.")
```

---

## Notes

- GeoPackage is preferred over Shapefile because it handles field names longer than 10 characters, supports GeoJSON-style attributes, and preserves the geometry column without truncation.
- If using Shapefile, field names will be truncated to 10 characters. The `score_explanation` field will be lost. Use GeoPackage or geodatabase instead.
- The `Shape_Length` field is automatically populated by ESRI when importing; the existing field is preserved for pre-computed length values.

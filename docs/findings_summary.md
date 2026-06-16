# RoadSense: Speed Safety Score for Safer Roads

## Findings Summary

**Prepared for:** ADB AI for Safer Roads Innovation Challenge
**Team:** Neuron Nexus
**Date:** June 2026

> **Note on data:** The numbers in this report (14,793 segments, 11,445 km Critical, etc.) are from the full ADB challenge dataset. The open-source repository includes a 100-segment synthetic demo for pipeline testing. See `data/raw/README.md` for details.

---

## 1. Executive Summary

RoadSense analyzes 14,793 road segments across Thailand and Maharashtra using GPS probe data, road network geometry, and street-level imagery to produce a Speed Safety Score (0–1) for every segment. The score measures how well posted speed limits align with the Safe System approach — the principle that human bodies can only withstand impact speeds of 30–50 km/h depending on road context.

**Key finding:** 77.9% of road segments have mean operating speeds above the Safe System threshold for their road type and land use. 12.2% of network length (11,445 km) is classified Critical — requiring immediate intervention. Secondary urban roads in both countries are the most dangerous category, with mean operating gaps exceeding 20 km/h above survivable impact speeds.

---

## 2. Methodology Overview

RoadSense implements two independent scoring approaches for cross-validation:

### 4-Component Composite Score

Four weighted factors per segment:

| Component | Weight | What it measures |
|---|---|---|
| Limit Misalignment | 30% | How far the posted limit exceeds Safe System recommendations |
| Operating Speed Risk | 30% | How far actual traffic (85th percentile speed) exceeds Safe System thresholds |
| VRU Exposure | 25% | Pedestrian fatality risk × road class / land use exposure |
| Traffic Volume | 15% | Normalised traffic volume percentile |

### 3-Module RoadSense Score

Three modules at equal weights (35%, 35%, 30%):
- **Module A — Speed Alignment:** Average of limit gap and operating speed gap
- **Module B — VRU Exposure:** Land use, road class, speed risk, and powered two-wheeler context
- **Module C — Road Environment:** Infrastructure gap proxy based on road class/land use, plus speed mismatch penalty

Both approaches produce scores in [0, 1] classified into four tiers:

| Tier | Score Range | Action Required |
|---|---|---|
| Critical | ≥ 0.65 | Immediate Safe System intervention |
| High | 0.45 – 0.65 | Priority review and countermeasure design |
| Moderate | 0.25 – 0.45 | Scheduled review and monitoring |
| Low | < 0.25 | Maintain current approach |

---

## 3. Key Findings

### 3.1 Network-Level Risk Distribution (4-Component)

| Risk Tier | Length (km) | % of Network |
|---|---|---|
| Critical — Immediate Review | 11,445 | 12.2% |
| High — Priority Review | 19,313 | 20.7% |
| Moderate — Scheduled Review | 25,499 | 27.3% |
| Low — Monitor | 37,253 | 39.8% |

**Mean network score: 0.415** (moderate risk)

### 3.2 Critical Findings

1. **Speed limits are systematically too high.** 77.9% of segments have posted speed limits exceeding Safe System recommendations. The average limit misalignment is 13 km/h above Safe System thresholds on urban primary roads.

2. **Traffic routinely exceeds survivable speeds.** On 76.6% of segments, 85th percentile operating speeds are above the Safe System threshold for that road context. The average operating gap on Critical segments is 38 km/h — a pedestrian struck at this speed faces near-certain fatality.

3. **Secondary urban roads are the most dangerous category.** These roads (typically mixed-use with foot traffic, shops, and residential access) have a Safe System limit of 30 km/h but frequently carry posted limits of 50–60 km/h and actual speeds above 60 km/h.

4. **VRU exposure amplifies risk.** 35% of segments have high VRU exposure scores (>0.6), concentrated in urban areas near schools, markets, and mixed land use. These segments receive double penalty — high operating speeds and high pedestrian presence.

### 3.3 Regional Findings

| Metric | Thailand | Maharashtra |
|---|---|---|
| Total segments analyzed | 9,732 | 5,061 |
| Critical segments (%) | 14.1% | 9.8% |
| Mean Speed Safety Score | 0.428 | 0.395 |
| Mean operating gap (km/h) | 11.4 | 8.7 |

### 3.4 RoadSense 3-Module Cross-Validation

The 3-module approach produces broadly consistent rankings (correlation >0.85 with 4-component scores), with slightly lower overall scores (mean SSS: 0.450 vs 0.415). Module-level diagnostics reveal:

- **Module A** (Speed Alignment) drives most Critical classifications — segments with high A scores almost always score Critical overall.
- **Module B** (VRU Exposure) is the most discriminating variable between urban and rural risk profiles.
- **Module C** (Road Environment) is the weakest signal due to reliance on static proxy values; future Mapillary/CLIP imagery integration would strengthen this module significantly.

---

## 4. Policy Recommendations

### 4.1 Immediate Priorities (Critical Tier — 11,445 km)

1. **Audit posted speed limits** on all Critical segments. Many carry limits 20–40 km/h above Safe System recommendations. Lowering limits to Safe System levels is the fastest, lowest-cost intervention available.

2. **Deploy traffic calming** on secondary urban roads with operating speeds >50 km/h. Speed humps, raised crossings, and lane narrowing can reduce speeds by 10–15 km/h with minimal infrastructure cost.

3. **Prioritize crossings for pedestrians** at VRU-critical segments near schools and markets. Marked crossings, pedestrian refuges, and signalised crossings at 500 m intervals in urban areas.

### 4.2 Medium-Term Actions (High Tier — 19,313 km)

4. **Reclassify road hierarchies** where the posted limit and road function are mismatched. A road that functions as a local access street but carries a 60 km/h primary road limit should be reclassified.

5. **Strengthen enforcement** at locations where operating speeds consistently exceed posted limits by >15 km/h. Automated speed cameras at high-risk urban primary roads.

6. **Integrate VRU risk into road design standards.** Current design standards in both countries prioritise vehicle throughput over pedestrian safety. Segments flagged as high-VRU should trigger protected pedestrian infrastructure in any redesign.

### 4.3 Systemic Changes

7. **Adopt Safe System speed limits as the national default.** Move from case-by-case speed limit setting to context-based defaults (e.g., all urban secondary roads default to 30 km/h unless a formal assessment justifies higher).

8. **Build a data-driven speed management program.** The RoadSense pipeline can be run quarterly to track changes, evaluate interventions, and update priorities. A national road safety observatory could host this as a live dashboard.

9. **Expand data collection** to include:
   - Dedicated pedestrian and cyclist counts at VRU-critical locations
   - Street-level imagery collection (Mapillary or similar) for infrastructure gap validation
   - Crash data (currently not used in scoring but essential for outcome validation)

---

## 5. Replication in Data-Scarce Countries

The RoadSense methodology is designed for replication across Asia-Pacific. Key adaptations:

| Data Source | If unavailable | Alternative |
|---|---|---|
| GPS probe data | Many LMICs lack probe data | Use OSM road classification + design speed as proxy for operating speed |
| Mapillary imagery | Limited coverage | CLIP zero-shot classification on any available street photos, or skip Module C entirely |
| Official speed limits | Not digitised | Extract from OSM `maxspeed` tags (available for ~40% of roads in most countries) |
| Schools / POIs | Always available via OSM | Overpass API provides global coverage at no cost |
| Traffic volume data | No volume data | Remove Volume component from 4-component score (weight redistributed to other factors) |

A minimal viable deployment requires only:
1. OSM road network
2. OSM speed limit tags
3. OSM points of interest (schools, markets)
4. Any available speed data (even spot speed measurements at 50 locations can calibrate the model)

---

## 6. Validation & Limitations

### Validation

- **Internal consistency:** Both scoring approaches produce correlated rankings (r > 0.85), confirming the methodology is robust to weighting choices.
- **Spatial autocorrelation:** Moran's I analysis confirms that high-risk segments cluster spatially (p < 0.01), validating that the score captures genuine geographic patterns rather than noise.
- **Sensitivity analysis:** Varying component weights by ±10% changes absolute scores but preserves >95% of tier classifications, showing the tier system is stable.

### Limitations

1. **No crash data validation.** The ADB challenge dataset does not include crash records. The score measures *risk factors* (speed, exposure, infrastructure proxies) rather than *observed crashes*. This is a deliberate Safe System design choice — we measure what makes roads dangerous, not what has already killed people.
2. **Imagery coverage gaps.** Module C relies on infrastructure proxies (road class + land use lookups) rather than actual infrastructure detection. Full Mapillary/CLIP integration would improve Module C accuracy.
3. **Sample size bias.** Segments with small sample sizes (<500 observations) are excluded. This may bias results toward higher-volume roads.
4. **Single time period.** The data represents one observation period. Seasonal and temporal variations in speed and volume are not captured.

---

## References

- World Health Organization. (2021). *Global Plan for the Decade of Action for Road Safety 2021–2030*. Geneva: WHO.
- ITF/OECD. (2018). *Speed and Crash Risk*. International Transport Forum Research Report. Paris: OECD Publishing.
- Asian Development Bank. (2026). *AI for Safer Roads 2026 — Speed and Volume Data for Thailand and Maharashtra*. ADB Challenge Dataset.
- OpenStreetMap contributors. (2026). Planet dump. https://planet.openstreetmap.org
- Mapillary. (2026). Mapillary street-level imagery and computer vision detections. https://www.mapillary.com

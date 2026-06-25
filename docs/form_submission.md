# ADB Challenge — Form Submission Content

## Copy-paste these values into the form at https://adbchallenges.org/

---

### Submission Title
RoadSense: AI-Powered Speed Safety Score and VRU Exposure Analysis

---

### Executive Summary

RoadSense is an AI-powered road safety analytics platform that answers a simple question: are posted speed limits actually protecting people, or just numbers on a sign? We analyzed 14,793 road segments across Thailand and Maharashtra using GPS probe data, OpenStreetMap road networks, and street-level imagery to produce a Speed Safety Score (0–1) for every segment.

**What we found:** 77.9% of segments have traffic travelling above Safe System survivable speeds. 12.2% of the total network (11,445 km) is classified Critical — meaning a crash at these locations is highly likely to result in death or serious injury. Secondary urban roads in both countries are the most dangerous category, carrying posted limits of 50–60 km/h on roads where the Safe System recommends 30 km/h.

**How we measure it:** Our 4-component score combines (1) how far the posted limit exceeds Safe System thresholds, (2) how far actual traffic exceeds those thresholds, (3) pedestrian and vulnerable road user exposure, and (4) traffic volume. Each segment is classified into four tiers: Critical, High, Moderate, or Low — with plain-language explanations designed for transport ministry officials.

**What governments should do:** Immediately audit speed limits on all 11,445 km of Critical segments, deploy traffic calming on secondary urban roads where speeds exceed 50 km/h, and adopt Safe System speed limits as the national default for each road class and land-use type. The methodology is designed to work in any country with basic road network data — even those without GPS probe data or street imagery can run a minimal version using just OpenStreetMap.

---

### Methodology Description

**Data Sources**

The analysis uses three categories of data:

1. **ADB Challenge GPS Probe Data** — Speed and volume measurements for road segments in Thailand and Maharashtra. Key fields include SpeedLimit, F85thPercentileSpeed (85th percentile operating speed), MedianSpeed, PercentOverLimit, SampleSize_avg, RoadClass, LandUse, and RankedPercentile.

2. **OpenStreetMap** — Road network geometry via OSMnx/pyrosm; points of interest (schools, markets) via Overpass API for VRU context enrichment; speed limit tags as fallback where official limits are missing.

3. **Safe System Reference Speeds** — Drawn from WHO (2021) Global Plan for the Decade of Action for Road Safety and ITF/OECD (2018) Speed and Crash Risk. These define survivable impact speeds per (road_class, land_use) pair — e.g., secondary urban roads: 30 km/h, primary urban: 50 km/h, trunk rural: 80 km/h.

**Data Preprocessing**

The ADB GPS data undergoes the following cleaning pipeline:

- **Validity filter:** Only segments with AnalysisStatus = "Valid" are retained.
- **Sample size threshold:** Segments with SampleSize_avg < 500 are dropped to ensure statistical reliability.
- **Speed limit imputation:** Missing or zero speed limits are imputed by road class defaults (motorway=110, trunk=90, primary=80, secondary=60 km/h).
- **Speed floor:** Segments with F85thPercentileSpeed < 5 km/h are removed (likely data errors).
- **Column normalization:** LandUse values are standardized (upper-cased, NaN filled to RURAL), RoadClass is lower-cased, bounded fields (PercentOverLimit) are clipped to [0, 1].

After cleaning, 14,793 out of 69,966 raw segments remain (79% reduction).

**Scoring Framework**

**4-Component Composite Score:**

Score = 0.30 × L + 0.30 × O + 0.25 × V + 0.15 × T

Where:
- L = Limit Misalignment: max(SpeedLimit − SSL, 0) / 40, capped at 1.0
- O = Operating Speed Risk: max(F85 − SSL, 0) / 40, capped at 1.0
- V = VRU Exposure: Pedestrian fatality risk × road class multiplier × land use multiplier
- T = Traffic Volume: RankedPercentile / 100
- SSL = Safe System Limit from WHO/ITF reference table

Pedestrian fatality risk uses the logistic curve: 1 / (1 + exp(−0.08 × (speed − 50))) derived from Pasanen (1992) and ITF/OECD (2018). At 30 km/h, fatality risk is ~17%; at 50 km/h, ~50%; at 70 km/h, ~83%.

**3-Module RoadSense Score (cross-validation):**

SSS = 0.35 × A + 0.35 × B + 0.30 × C

Each module operates independently:
- **Module A (Speed Alignment):** Average of limit misalignment and operating speed risk scores
- **Module B (VRU Exposure):** Land use × road class × speed risk, with powered two-wheeler bonus on trunk/primary roads where F85 > 80 km/h
- **Module C (Road Environment):** Infrastructure gap score from a static (road class, land use) lookup table calibrated to Safe System guidance, plus speed mismatch penalty where F85 exceeds posted speed

**Risk Tier Classification:**

| Tier | Score | Action |
|---|---|---|
| Critical | ≥ 0.65 | Immediate Safe System intervention |
| High | 0.45–0.65 | Priority review |
| Moderate | 0.25–0.45 | Scheduled review |
| Low | < 0.25 | Monitor |

**Speed-Unsafe Segment Identification**

Speed-Unsafe Segments are those classified as Critical or High (score ≥ 0.45). These are segments where at least one of the following conditions holds:
- Posted limit exceeds Safe System recommendation by ≥ 20 km/h
- 85th percentile operating speed exceeds Safe System limit by ≥ 15 km/h
- High VRU exposure (>0.6) combined with operating speeds above Safe System threshold

**Validation Approach**

1. **Cross-method consistency:** Both scoring approaches produce correlated rankings (Pearson r > 0.85), confirming the relative risk ordering is robust to methodological choices.
2. **Spatial autocorrelation:** Moran's I test confirms that high-risk segments cluster spatially (p < 0.01), validating that the score captures genuine geographic risk patterns.
3. **Sensitivity analysis:** Varying each component weight by ±10 percentage points changes absolute scores but preserves >95% of tier classifications.
4. **Explanatory transparency:** Every segment includes a plain-language explanation identifying the specific factors driving its score (e.g., "Posted limit exceeds Safe System recommendation by 30 km/h for this primary road in a rural area").

**Replicability**

The methodology is designed for deployment in any Asia-Pacific country:

| Data Source | Alternative if Unavailable |
|---|---|
| GPS probe data | OSM road classification + design speed as proxy |
| Mapillary imagery | CLIP zero-shot on any available street photos |
| Official speed limits | OSM maxspeed tags (~40% global coverage) |
| Traffic volume data | Remove Volume component; redistribute weights |
| Schools / POIs | Overpass API (free, global) |

A minimal deployment requires only an OSM road network, speed limit tags, and any available speed measurements — even 50 spot-speed readings can calibrate the model.

**Limitations**

- No crash data was available for outcome validation. The score measures risk factors, not observed crashes.
- Module C relies on infrastructure proxies rather than direct detection. Full Mapillary/CLIP integration would improve accuracy.
- Segments with <500 samples are excluded, potentially biasing toward higher-volume roads.
- The data represents a single observation period — seasonal variations are not captured.

---

### Findings Summary

See full 4-page Word document: https://github.com/shamiquekhan/RoadSense/blob/main/docs/findings_summary.docx

Key findings:
- **12.2% of the network (11,445 km) is Critical.** These segments need immediate Safe System intervention.
- **77.9% of segments have posted limits exceeding Safe System recommendations.**
- **76.6% of segments have traffic exceeding survivable speeds.**
- **Secondary urban roads are the most dangerous category** — Safe System recommends 30 km/h but roads carry 50–60 km/h limits with actual speeds >60 km/h.
- **35% of segments have high VRU exposure** — concentrated near schools and markets.
- **Both countries show similar patterns:** Thailand mean score 0.428, Maharashtra 0.395.
- **Policy action is clear:** audit limits on Critical segments, deploy traffic calming, and adopt context-based Safe System speed defaults nationally.

---

### Motivation

*(Note: Keep the live version of this field on the ADB website. It is more specific and compelling than this draft, as it highlights your personal context and resources.)*

I chose to participate in this challenge because road safety is one of the most solvable yet persistently neglected public health issues in developing countries. Over 1.3 million people die on roads annually — the majority in Asia-Pacific — and speed is the single most important factor determining whether a crash results in a fatality or an injury.

What excites me about this challenge is that the data and tools now exist to move from anecdotal policy-making to evidence-based speed management. GPS probe data, OpenStreetMap, and computer vision models like CLIP make it possible to assess every road segment in a country at minimal cost.

I built RoadSense because I believe transport ministries should have a tool that tells them not just where crashes have happened (which is reactive), but where *risk is highest* (which is preventive). The Safe System approach — adopted by Sweden, the Netherlands, and increasingly across the OECD — has proven that treating speed as a systemic issue rather than a driver-behaviour issue saves lives. My goal is to make this approach accessible and operational for ADB member countries.

---

### Section 1: Team Information

**Team Name:** Neuron Nexus

**Team Lead:** Shamique Khan

**Email:** shamiquekhan18@gmail.com

**Country:** India

**Organization:** Vellore Institute of Technology Bhopal

**Highest Education:** B.Tech (Computer Science Engineering — AI & ML)

**LinkedIn:** https://www.linkedin.com/in/shamique-khan/

**Team Members:**
- Shamique Khan | 2006 | India | shamiquekhan18@gmail.com

**Team Composition:**
Shamique Khan — Data Science, AI/ML, backend engineering, full-stack project development. Independently designed and built the entire RoadSense pipeline including data preprocessing, multi-module scoring engines, geospatial visualization, and CI/CD infrastructure.

**Previous Experience:**
*(Note: Keep the live version of this field on the ADB website. It is stronger because it includes details about your weather forecasting model, investment advisor agent, ARAMS pipeline, and sleep-staging device.)*

I have experience in data science and machine learning projects, including building end-to-end analytical pipelines, geospatial data processing with GeoPandas and OSMnx, and deploying interactive visualizations. This project represents my first application of these skills to transport safety, combining my technical background with a commitment to social impact.

---

### Eligibility Confirmation

Select ALL:
- [x] All team members are residents of or affiliated with an ADB member country
- [x] Our team has read and agrees to the challenge rules and terms and conditions
- [x] Our team agrees to the data use terms and conditions governing the challenge datasets
- [x] The submission is our own original work and does not infringe on any third-party intellectual property

---

### Pilot Interest

**Yes, we would be available and interested**

---

### Deliverable Links (GitHub)

**Analytical Model:** https://github.com/shamiquekhan/RoadSense

**Speed Safety Score:** https://github.com/shamiquekhan/RoadSense/blob/main/outputs/speed_safety_scores.csv

**Geospatial Visualization:** https://shamiquekhan.github.io/RoadSense/speed_safety_scores_map.html

---

### How did you hear about this challenge?

LinkedIn, University / Academic Network, Email

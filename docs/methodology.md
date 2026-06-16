# Methodology

RoadSense follows a five-stage pipeline: data ingestion, spatial preprocessing, three parallel analysis modules, composite scoring, and geospatial visualisation.

## 1. Data ingestion and audit

Raw GPS probe, road network, Mapillary, and contextual layers are loaded from `data/raw/`. The audit step checks row counts, schema coverage, missing values, CRS consistency, and the presence of required spatial keys before scoring begins.

## 2. Spatial preprocessing

Preprocessing produces a single segment-level master table in `data/processed/segments_master.gpkg`. It standardises segment IDs, computes segment length, aggregates GPS probe observations, and joins contextual layers with documented buffer assumptions.

## 3. Module A: speed alignment

Module A compares observed operating speed with the posted limit and a Safe System reference speed. The output captures both `speed_gap` and `safe_system_gap`, then normalises them into `A_score`.

## 4. Module B: VRU exposure

Module B estimates exposure using attractor presence, population density, conflict potential, land use, and PTW indicators. These are normalised and combined into `B_score`.

## 5. Module C: road environment proxy

Module C assigns an infrastructure gap score based on road class and land use using a static lookup table calibrated to published Safe System guidance. A speed mismatch penalty (proportional to the gap between observed 85th percentile speed and the posted limit) is added. The combined score is written as `C_score`. Future releases will replace the static lookup with real infrastructure detection from Mapillary street-level imagery.

## 6. Composite scoring and evaluation

The Speed Safety Score is a weighted sum of `A_score`, `B_score`, and `C_score`. Evaluation covers internal consistency checks, spatial autocorrelation, benchmark validation, and sensitivity analysis to weight perturbations.

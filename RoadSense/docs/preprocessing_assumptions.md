# Preprocessing Assumptions

## Spatial reference system

- Store geometries in `EPSG:4326`.
- Reproject to a local UTM zone for length and distance calculations.

## Map matching and GPS join

- Prefer direct `segment_id` joins when the probe data already includes a segment key.
- Otherwise snap GPS points to the nearest segment within a 15 m tolerance.
- Aggregate probe speeds per segment using mean speed, 85th percentile speed, speed standard deviation, and observation count.

## Context layer buffers

- Schools, markets, and bus stops: 150 m buffer radius.
- Population density: 300 m sampling buffer around segment centroids.
- PTW indicators: segment or zone overlay, with a 200 m context radius where applicable.
- Intersection density: endpoint proximity counted within a 50 m buffer.
- Mapillary imagery: 50 m image search radius around segment centroids.

## Join rules

- Segment attributes should be preserved as the master row key.
- Missing contextual values should be set to zero for score inputs when no source is available.
- Land use should be assigned from the polygon containing the segment centroid.
- When multiple attractor layers exist, keep both the per-layer count and the combined attractor count.

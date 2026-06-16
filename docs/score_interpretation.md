# Understanding the RoadSense Speed Safety Score

The Speed Safety Score is a number from 0 to 1 assigned to each road segment. A higher score means the segment is more likely to need a speed limit review because the current limit does not appear to fit the road, its use, or the people who travel on it.

RoadSense combines three signals. First, it looks at whether traffic is moving much faster or slower than the posted limit. Second, it estimates how exposed pedestrians, cyclists, and powered two-wheeler users are to harm. Third, it reads the road environment from street imagery to see whether protective features are present.

The score is not a measure of driver behaviour alone. It is a measure of whether the system around the road user is aligned with safe speeds. That makes it useful for ministries that need a clear, repeatable way to prioritise reviews.

## Risk tiers

| Tier | Score | Meaning |
|---|---|---|---|
| Critical | ≥ 0.65 | Immediate review recommended |
| High | 0.45 – 0.65 | Priority review within 12 months |
| Moderate | 0.25 – 0.45 | Monitor in the next cycle |
| Low | < 0.25 | No immediate action required |

## How to read the popup

Each map popup explains the segment in plain language: posted limit, observed speed, Safe System reference, vulnerability context, and the recommended action. The aim is to let a policy team understand the reason for a score without needing to inspect the code.

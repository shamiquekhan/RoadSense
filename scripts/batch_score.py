#!/usr/bin/env python3
"""Run the full RoadSense scoring pipeline — entry point for both approaches.

Usage:
    python scripts/batch_score.py --approach 4component
    python scripts/batch_score.py --approach roadsense
    python scripts/batch_score.py --data-dir /path/to/data
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roadsense.pipeline import run_pipeline_4component, run_pipeline_roadsense
from roadsense.config import RAW_DATA_DIR, OUTPUT_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RoadSense scoring pipeline.")
    parser.add_argument(
        "--approach", choices=["4component", "roadsense", "both"],
        default="both", help="Scoring approach to use"
    )
    parser.add_argument("--data-dir", default=str(RAW_DATA_DIR), help="Path to raw ADB data")
    parser.add_argument("--out-dir", default=str(OUTPUT_DIR), help="Output directory")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)

    if args.approach in ("4component", "both"):
        run_pipeline_4component(data_dir, out_dir)

    if args.approach in ("roadsense", "both"):
        run_pipeline_roadsense(data_dir, out_dir)

    print("\n✓ Pipeline complete. Outputs in:", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

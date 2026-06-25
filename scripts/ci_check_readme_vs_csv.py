#!/usr/bin/env python3
"""CI check: ensure README Results Summary matches reports/baseline_comparison.csv

This script reads `reports/baseline_comparison.csv` (RandomForest rows) and the
Results Summary table in `RoadSense/README.md`, compares MAE, RMSE, and R²
values (rounded to the published precision), and returns non-zero on mismatch.
"""

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "outputs" / "network_kpis.csv"
README_PATH = ROOT / "README.md"


def load_csv_metrics(csv_path):
    metrics = {}
    if not csv_path.exists():
        print(f"Missing CSV: {csv_path}")
        sys.exit(2)
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("model") != "RandomForestRegressor":
                continue
            fs = row.get("feature_set", "").lower()
            split = row.get("split", "")
            # map to README labels
            model_label = "Full Features" if fs == "full" else "Safe Features"
            if split == "random":
                split_label = "Random"
            elif split == "Thailand_to_Maharashtra":
                split_label = "Thailand → Maharashtra"
            elif split == "Maharashtra_to_Thailand":
                split_label = "Maharashtra → Thailand"
            else:
                split_label = split
            key = (model_label, split_label)
            mae = float(row.get("MAE") or 0)
            rmse = float(row.get("RMSE") or 0)
            r2 = float(row.get("R2") or 0)
            # formatting to match README: MAE/RMSE 4 decimals, R2 3 decimals
            metrics[key] = {
                "MAE": round(mae, 4),
                "RMSE": round(rmse, 4),
                "R2": round(r2, 3),
            }
    return metrics


def parse_readme_table(readme_path):
    if not readme_path.exists():
        print(f"Missing README: {readme_path}")
        sys.exit(2)
    text = readme_path.read_text()
    m = re.search(r"### Results Summary\n(\|[\s\S]*?)\n## ", text)
    if not m:
        # fallback: from header to end
        m2 = re.search(r"### Results Summary\n([\s\S]*)", text)
        if not m2:
            print("Results Summary table not found in README")
            sys.exit(2)
        table_text = m2.group(1)
    else:
        table_text = m.group(1)
    rows = []
    for line in table_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        # skip separator line
        if re.match(r"^\|[-\s:|]+$", line):
            continue
        parts = [p.strip() for p in line.split("|")][1:-1]
        if len(parts) < 5:
            continue
        # skip header row
        if parts[0].lower() == "model" or parts[1].lower().startswith("split"):
            continue
        model_label, split_label, mae_s, rmse_s, r2_s = parts[:5]
        try:
            mae = float(mae_s)
            rmse = float(rmse_s)
            r2 = float(r2_s)
        except ValueError:
            print(f"Failed to parse numbers in README row: {line}")
            sys.exit(2)
        rows.append(
            (
                (model_label, split_label),
                {"MAE": round(mae, 4), "RMSE": round(rmse, 4), "R2": round(r2, 3)},
            )
        )
    return dict(rows)


def main():
    csv_metrics = load_csv_metrics(CSV_PATH)
    readme_metrics = parse_readme_table(README_PATH)
    ok = True
    for key, csv_val in csv_metrics.items():
        readme_val = readme_metrics.get(key)
        if readme_val is None:
            print(f"Missing README entry for {key}")
            ok = False
            continue
        for k in ("MAE", "RMSE", "R2"):
            if csv_val[k] != readme_val[k]:
                print(f"Mismatch {key} {k}: CSV={csv_val[k]} README={readme_val[k]}")
                ok = False
    if not ok:
        print("FAILED: README metrics do not match CSV")
        sys.exit(1)
    print("OK: README metrics match reports/baseline_comparison.csv")


if __name__ == "__main__":
    main()

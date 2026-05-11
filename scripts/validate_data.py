#!/usr/bin/env python3
"""CSV structure & cross-reference checks for the Sweden 4-zone case.

Used by `make validate` and the `validate-data` CI workflow. Exits 0 on
success, 1 with a punch list on failure.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Allowed resolutions: 1h (8760 steps/yr) and 15min (35040 steps/yr).
VALID_N = {8760, 35040}


def main() -> int:
    errors: list[str] = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    # Network has the 12 Nordic zones -------------------------------------
    EXPECTED_ZONES = [
        "SE1", "SE2", "SE3", "SE4",
        "NO1", "NO2", "NO3", "NO4", "NO5",
        "FI", "DK1", "DK2",
    ]
    rows = list(csv.reader(open(REPO / "system" / "Network.csv")))
    zones = [r[0] for r in rows[1:] if r and r[0]]
    check(zones == EXPECTED_ZONES,
          f"Network.csv: zones must be {EXPECTED_ZONES}, got {zones}")

    # Demand: header + N rows, where N matches Timesteps_per_Rep_Period ----
    rows = list(csv.reader(open(REPO / "system" / "Demand_data.csv")))
    hdr = rows[0]
    tspr_idx = hdr.index("Timesteps_per_Rep_Period")
    declared_N = int(rows[1][tspr_idx])
    check(declared_N in VALID_N,
          f"Demand_data.csv: Timesteps_per_Rep_Period={declared_N} "
          f"not in {sorted(VALID_N)} (expected 8760 for 1-h or 35040 for 15-min)")
    N = declared_N
    check(len(rows) == N + 1,
          f"Demand_data.csv: expected {N + 1} rows (header + {N} steps), got {len(rows)}")
    for z in range(1, len(EXPECTED_ZONES) + 1):
        check(f"Demand_MW_z{z}" in hdr,
              f"Demand_data.csv: missing column Demand_MW_z{z}")

    # Variability: header + N rows ----------------------------------------
    rows = list(csv.reader(open(REPO / "system" / "Generators_variability.csv")))
    check(len(rows) == N + 1,
          f"Generators_variability.csv: expected {N + 1} rows, got {len(rows)}")

    var_resources = set(rows[0][1:])
    declared: set[str] = set()
    for fn in ("Thermal.csv", "Vre.csv", "Storage.csv", "Hydro.csv"):
        p = REPO / "resources" / fn
        if not p.exists():
            continue
        with p.open() as f:
            r = csv.reader(f)
            hdr = next(r)
            idx = hdr.index("Resource")
            for row in r:
                if row and row[idx]:
                    declared.add(row[idx])
    missing = var_resources - declared
    extra = declared - var_resources
    check(not missing,
          f"Resources in variability CSV but missing from resource CSVs: {sorted(missing)}")
    check(not extra,
          f"Resources declared but absent from variability CSV: {sorted(extra)}")

    # Fuels: header + emit row + N rows -----------------------------------
    rows = list(csv.reader(open(REPO / "system" / "Fuels_data.csv")))
    check(
        len(rows) == N + 2,
        f"Fuels_data.csv: expected {N + 2} rows (header + emit + {N} steps), "
        f"got {len(rows)}",
    )
    fuels_hdr = rows[0][1:]
    with (REPO / "resources" / "Thermal.csv").open() as f:
        r = csv.reader(f)
        hdr = next(r)
        fi = hdr.index("Fuel")
        for row in r:
            fuel = row[fi]
            check(fuel in fuels_hdr,
                  f"Thermal resource {row[0]} uses fuel {fuel!r} missing from Fuels_data.csv")

    if errors:
        print("Validation failed:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("All CSV structure checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

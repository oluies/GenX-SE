#!/usr/bin/env python3
"""CSV structure & cross-reference checks for the Sweden 4-zone case.

Used by `make validate` and the `validate-data` CI workflow. Exits 0 on
success, 1 with a punch list on failure.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

HOURS = 8760
REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    # Network has 4 zones --------------------------------------------------
    rows = list(csv.reader(open(REPO / "system" / "Network.csv")))
    check(len(rows) == 5,
          f"Network.csv: expected 5 rows (header + 4 zones), got {len(rows)}")
    zones = [r[0] for r in rows[1:] if r and r[0]]
    check(zones == ["SE1", "SE2", "SE3", "SE4"],
          f"Network.csv: zones must be SE1..SE4, got {zones}")

    # Demand: header + 8760 rows ------------------------------------------
    rows = list(csv.reader(open(REPO / "system" / "Demand_data.csv")))
    check(len(rows) == HOURS + 1,
          f"Demand_data.csv: expected {HOURS + 1} rows, got {len(rows)}")
    hdr = rows[0]
    for z in ("Demand_MW_z1", "Demand_MW_z2", "Demand_MW_z3", "Demand_MW_z4"):
        check(z in hdr, f"Demand_data.csv: missing column {z}")

    # Variability: header + 8760 rows -------------------------------------
    rows = list(csv.reader(open(REPO / "system" / "Generators_variability.csv")))
    check(len(rows) == HOURS + 1,
          f"Generators_variability.csv: expected {HOURS + 1} rows, got {len(rows)}")

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

    # Fuels: header + emit row + 8760 rows --------------------------------
    rows = list(csv.reader(open(REPO / "system" / "Fuels_data.csv")))
    check(
        len(rows) == HOURS + 2,
        f"Fuels_data.csv: expected {HOURS + 2} rows (header + emit + {HOURS} hours), "
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

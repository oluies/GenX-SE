#!/usr/bin/env python3
"""Rescale resource CSVs for a different timestep length.

GenX's unit-commitment and storage constraints are written *per timestep*:

    Up_Time / Down_Time         — in timesteps
    Ramp_Up_Percentage          — fraction of capacity per timestep
    Ramp_Dn_Percentage          — fraction of capacity per timestep
    Min_Duration / Max_Duration — in timesteps (storage)

So switching from 1-h to 15-min timesteps requires:

    Up_Time           ×4
    Down_Time         ×4
    Min_Duration      ×4
    Max_Duration      ×4
    Ramp_Up_Percentage  /4
    Ramp_Dn_Percentage  /4

Costs, capacities, heat rates, fuel mappings, start-up costs (per startup,
not per timestep), and min-power are *not* timestep-dependent and stay
unchanged.

Run before switching `build_timeseries.py --resolution 15min`:

    python3 scripts/rescale_resources.py --to 15min
    python3 scripts/rescale_resources.py --to 1h     # restore

By default this rescales in-place with a `.bak.<from>` backup. Use
`--out DIR` to write into a sibling folder instead.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESOURCES = REPO / "resources"

# Columns that scale with timestep length, and their direction.
# +1 = multiply by factor (times scale with shorter steps)
# -1 = divide by factor (rates per step shrink with shorter steps)
COLUMNS = {
    "Up_Time":            +1,
    "Down_Time":          +1,
    "Min_Duration":       +1,
    "Max_Duration":       +1,
    "Ramp_Up_Percentage": -1,
    "Ramp_Dn_Percentage": -1,
}

# Resource CSV filenames to scan
FILES = ["Thermal.csv", "Vre.csv", "Storage.csv", "Hydro.csv"]


def factor_for(from_res: str, to_res: str) -> float:
    """How many *to_res* steps fit in one *from_res* step."""
    step_h = {"1h": 1.0, "15min": 0.25}
    return step_h[from_res] / step_h[to_res]


def _coerce_number(s: str) -> float | int | str:
    """Return the value as int when it round-trips, float otherwise, else raw str."""
    try:
        v = float(s)
    except ValueError:
        return s
    iv = int(v)
    return iv if iv == v else v


def rescale_csv(path: Path, scale: float, dry_run: bool, out: Path | None) -> bool:
    """Returns True if anything changed."""
    if not path.exists():
        return False
    with path.open() as f:
        rows = list(csv.reader(f))
    if not rows:
        return False
    hdr = rows[0]
    col_idx = {c: hdr.index(c) for c in COLUMNS if c in hdr}
    if not col_idx:
        return False

    changed = False
    new_rows = [hdr]
    for row in rows[1:]:
        new_row = list(row)
        for name, idx in col_idx.items():
            cell = row[idx]
            if cell == "" or cell is None:
                continue
            try:
                v = float(cell)
            except ValueError:
                continue
            direction = COLUMNS[name]
            v_new = v * scale if direction > 0 else v / scale
            # Up_Time/Down_Time should stay integer if input was integer
            if name in {"Up_Time", "Down_Time", "Min_Duration", "Max_Duration"}:
                v_new = int(round(v_new))
                new_row[idx] = str(v_new)
            else:
                # Keep at most 6 decimal places; strip trailing zeros
                new_row[idx] = f"{v_new:.6f}".rstrip("0").rstrip(".")
            if new_row[idx] != cell:
                changed = True
        new_rows.append(new_row)

    target = out / path.name if out else path
    if dry_run:
        if changed:
            print(f"  would rewrite {path.name} (changed columns: {sorted(col_idx)})")
        return changed

    if not out and changed:
        # in-place: backup first
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerows(new_rows)
    if changed:
        print(f"  rewrote {target.relative_to(REPO)} (columns: {sorted(col_idx)})")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="from_res", choices=["1h", "15min"],
                    default="1h", help="Current resolution of the resource CSVs")
    ap.add_argument("--to", dest="to_res", choices=["1h", "15min"], required=True,
                    help="Target resolution")
    ap.add_argument("--out", type=Path, default=None,
                    help="Write rescaled CSVs into DIR instead of in-place")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change without writing")
    args = ap.parse_args()

    if args.from_res == args.to_res:
        print(f"From and to are both {args.from_res} — nothing to do.")
        return 0

    scale = factor_for(args.from_res, args.to_res)
    print(f"Rescaling resource CSVs: {args.from_res} -> {args.to_res} "
          f"(timestep factor = {scale}×)")
    if args.dry_run:
        print("DRY RUN — no files will be written")

    any_changed = False
    for fn in FILES:
        path = RESOURCES / fn
        out_dir = args.out
        if rescale_csv(path, scale, args.dry_run, out_dir):
            any_changed = True

    if not any_changed:
        print("No matching columns found — nothing to do.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

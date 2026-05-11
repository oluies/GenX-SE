#!/usr/bin/env python3
"""
Generate synthetic but Nordic-shaped time series for the GenX-SE case
at either 1-hour or 15-minute resolution. Covers all 12 Nordic bidding
zones: SE1-4, NO1-5, FI, DK1, DK2.

Outputs to system/:
    Demand_data.csv             (one column per zone)
    Generators_variability.csv  (one column per resource discovered in resources/*.csv)
    Fuels_data.csv

The Nordic synchronous area moved to a 15-min Imbalance Settlement Period
in 2023-2024 and the day-ahead market (Nord Pool / SDAC) followed in
October 2025. Pass `--resolution 15min` to emit 35040-step series that
align with that market design.

Profiles are deterministic (seeded RNG) so reruns are reproducible.

Replace these files with real ENTSO-E / SMHI / Renewables.ninja data
via `data/fetch_entsoe.py --resolution {1h,15min}`.
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYS = HERE / "system"
RESOURCES = HERE / "resources"
SYS.mkdir(exist_ok=True)


# ---- Zone master table ------------------------------------------------
# id = the integer the resource CSVs use in the Zone column.
# label = the human/header label (used in Demand_MW_zN columns is z<id>).
# avg_mw = annual mean demand in MW.
# lat = latitude for solar geometry.
ZONES = [
    {"id":  1, "label": "SE1", "avg_mw": 2000, "lat": 65.6},
    {"id":  2, "label": "SE2", "avg_mw": 2500, "lat": 62.4},
    {"id":  3, "label": "SE3", "avg_mw": 8500, "lat": 59.3},
    {"id":  4, "label": "SE4", "avg_mw": 3000, "lat": 55.6},
    {"id":  5, "label": "NO1", "avg_mw": 4100, "lat": 59.9},   # Oslo
    {"id":  6, "label": "NO2", "avg_mw": 4100, "lat": 58.9},   # Stavanger
    {"id":  7, "label": "NO3", "avg_mw": 2500, "lat": 63.4},   # Trondheim
    {"id":  8, "label": "NO4", "avg_mw": 1800, "lat": 69.6},   # Tromsø
    {"id":  9, "label": "NO5", "avg_mw": 2500, "lat": 60.4},   # Bergen
    {"id": 10, "label": "FI",  "avg_mw": 9100, "lat": 60.2},
    {"id": 11, "label": "DK1", "avg_mw": 2800, "lat": 56.2},
    {"id": 12, "label": "DK2", "avg_mw": 1400, "lat": 55.7},
]
ZONE_BY_ID = {z["id"]: z for z in ZONES}


# ---- Resolution-aware time helpers -----------------------------------
def steps_per_year(resolution: str) -> int:
    return {"1h": 8760, "15min": 35040}[resolution]


def steps_per_day(resolution: str) -> int:
    return {"1h": 24, "15min": 96}[resolution]


def hours_per_step(resolution: str) -> float:
    return {"1h": 1.0, "15min": 0.25}[resolution]


def day_of_year(t: int, resolution: str) -> int:
    return (t // steps_per_day(resolution)) % 365


def hour_of_day(t: int, resolution: str) -> float:
    return (t % steps_per_day(resolution)) * hours_per_step(resolution)


# ---- Demand profile (MW) ---------------------------------------------
def demand_profile(avg_mw: float, resolution: str, rng: random.Random,
                   winter_amp: float = 0.42) -> list[float]:
    """Daily + weekly + seasonal demand shape. winter_amp controls how
    pronounced the winter peak is — Nordic countries with electric heating
    (NO, SE) ~0.42; DK (less electric heating) ~0.25."""
    out = []
    N = steps_per_year(resolution)
    for t in range(N):
        d = day_of_year(t, resolution)
        hh = hour_of_day(t, resolution)
        seasonal = 1.0 + winter_amp * math.cos(2 * math.pi * (d - 15) / 365)
        daily = (
            1.0
            + 0.18 * math.exp(-((hh - 8) ** 2) / 8.0)
            + 0.22 * math.exp(-((hh - 18) ** 2) / 10.0)
            - 0.18 * math.exp(-((hh - 3) ** 2) / 8.0)
        )
        dow = (t // steps_per_day(resolution)) % 7
        weekly = 0.94 if dow >= 5 else 1.0
        noise_amp = 0.03 if resolution == "1h" else 0.05
        noise = 1.0 + noise_amp * (rng.random() - 0.5)
        out.append(avg_mw * seasonal * daily * weekly * noise)
    return out


# ---- VRE/Hydro profiles ---------------------------------------------
def wind_profile(annual_cf: float, resolution: str, rng: random.Random,
                 seasonal_amp: float = 0.22) -> list[float]:
    N = steps_per_year(resolution)
    phi = 0.92 if resolution == "1h" else 0.98
    sigma = 0.4 if resolution == "1h" else 0.2
    state = 0.0
    out = []
    for t in range(N):
        d = day_of_year(t, resolution)
        seasonal = 1.0 + seasonal_amp * math.cos(2 * math.pi * (d - 15) / 365)
        state = phi * state + sigma * (rng.random() - 0.5)
        cf = annual_cf * seasonal * (1.0 + state)
        out.append(min(0.95, max(0.0, cf)))
    return out


def solar_profile(annual_cf: float, lat_deg: float, resolution: str,
                  rng: random.Random) -> list[float]:
    N = steps_per_year(resolution)
    out = []
    for t in range(N):
        d = day_of_year(t, resolution)
        hh = hour_of_day(t, resolution)
        decl = math.radians(23.45) * math.sin(2 * math.pi * (d - 81) / 365)
        lat = math.radians(lat_deg)
        ha = math.radians(15 * (hh - 12))
        cos_zen = (
            math.sin(lat) * math.sin(decl)
            + math.cos(lat) * math.cos(decl) * math.cos(ha)
        )
        if cos_zen <= 0:
            out.append(0.0)
            continue
        cloud = 0.55 + 0.45 * rng.random()
        out.append(min(0.9, max(0.0, cos_zen * cloud * 1.2)))
    mean_cf = sum(out) / N
    if mean_cf > 0:
        scale = annual_cf / mean_cf
        out = [min(0.9, v * scale) for v in out]
    return out


def hydro_inflow(annual_cf: float, melt_amp: float, melt_day: int,
                 resolution: str, rng: random.Random) -> list[float]:
    N = steps_per_year(resolution)
    out = []
    for t in range(N):
        d = day_of_year(t, resolution)
        melt = melt_amp * math.exp(-((d - melt_day) ** 2) / (35 ** 2))
        autumn = 0.15 * melt_amp * math.exp(-((d - 285) ** 2) / (40 ** 2))
        base = annual_cf * 0.7
        noise = 1.0 + 0.08 * (rng.random() - 0.5)
        out.append(max(0.0, (base + melt + autumn) * noise))
    mean_cf = sum(out) / N
    if mean_cf > 0:
        out = [v * (annual_cf / mean_cf) for v in out]
    return out


# ---- Resource classification + profile dispatch ----------------------
def classify(name: str) -> str:
    n = name.lower()
    if "nuclear" in n or "biomass" in n or "chp" in n or "gas" in n or "oil" in n or "peaker" in n:
        return "thermal"
    if "offshore_wind" in n:
        return "offshore_wind"
    if "wind" in n:
        return "onshore_wind"
    if "solar" in n or "pv" in n:
        return "solar_pv"
    if "battery" in n or "storage" in n:
        return "storage"
    if "hydro" in n:
        return "hydro"
    return "other"


def discover_resources() -> list[tuple[str, int]]:
    """Walk resources/*.csv and return [(resource_name, zone_id), ...]."""
    out = []
    for fn in ("Thermal.csv", "Vre.csv", "Storage.csv", "Hydro.csv"):
        p = RESOURCES / fn
        if not p.exists():
            continue
        with p.open() as f:
            rdr = csv.reader(f)
            hdr = next(rdr)
            i_name = hdr.index("Resource")
            i_zone = hdr.index("Zone")
            for row in rdr:
                if row and row[i_name]:
                    out.append((row[i_name], int(row[i_zone])))
    return out


def profile_for(name: str, zone_id: int, resolution: str,
                rng: random.Random) -> list[float]:
    N = steps_per_year(resolution)
    kind = classify(name)
    zone = ZONE_BY_ID[zone_id]
    if kind in ("thermal", "storage", "other"):
        return [1.0] * N

    if kind == "onshore_wind":
        # Northern + coastal slightly higher than inland
        cf = 0.40 if zone["lat"] > 62 else 0.35
        return wind_profile(cf, resolution, rng, seasonal_amp=0.23)
    if kind == "offshore_wind":
        return wind_profile(0.46, resolution, rng, seasonal_amp=0.18)
    if kind == "solar_pv":
        # Lower CF at higher latitudes — geometry alone accounts for most of it,
        # but cap the annual mean too.
        target_cf = max(0.06, 0.14 - 0.005 * (zone["lat"] - 55))
        return solar_profile(target_cf, zone["lat"], resolution, rng)
    if kind == "hydro":
        # NO has bigger melt amplitude, later peak. FI has flatter profile.
        label = zone["label"]
        if label.startswith("NO"):
            return hydro_inflow(0.50, 0.55, melt_day=135, resolution=resolution, rng=rng)
        if label == "FI":
            return hydro_inflow(0.35, 0.20, melt_day=110, resolution=resolution, rng=rng)
        # SE — bigger melt in north
        cf = {"SE1": 0.50, "SE2": 0.48, "SE3": 0.42, "SE4": 0.35}.get(label, 0.45)
        amp = {"SE1": 0.55, "SE2": 0.50, "SE3": 0.30, "SE4": 0.15}.get(label, 0.40)
        return hydro_inflow(cf, amp, melt_day=120, resolution=resolution, rng=rng)
    return [1.0] * N


# ---- Writers ---------------------------------------------------------
def winter_amp_for(label: str) -> float:
    if label.startswith("DK"):
        return 0.25
    if label.startswith("NO") or label.startswith("FI"):
        return 0.45
    return 0.42


def write_demand(resolution: str, rng: random.Random) -> None:
    N = steps_per_year(resolution)
    demands = {
        z["id"]: demand_profile(z["avg_mw"], resolution, rng, winter_amp_for(z["label"]))
        for z in ZONES
    }
    fp = SYS / "Demand_data.csv"
    cols = [f"Demand_MW_z{z['id']}" for z in ZONES]
    with fp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Voll", "Demand_Segment", "Cost_of_Demand_Curtailment_per_MW",
            "Max_Demand_Curtailment", "$/MWh", "Rep_Periods",
            "Timesteps_per_Rep_Period", "Sub_Weights", "Time_Index",
            *cols,
        ])
        seg_rows = [
            ("50000", "1", "1",    "1",     "2000"),
            ("",      "2", "0.9",  "0.04",  "1800"),
            ("",      "3", "0.55", "0.024", "1100"),
            ("",      "4", "0.2",  "0.003", "400"),
        ]
        for t in range(N):
            voll, seg, cost, maxcurt, dollar = (
                seg_rows[t] if t < len(seg_rows) else ("", "", "", "", "")
            )
            rep = "1" if t == 0 else ""
            tspr = str(N) if t == 0 else ""
            subw = "8760" if t == 0 else ""
            w.writerow([
                voll, seg, cost, maxcurt, dollar, rep, tspr, subw, t + 1,
                *(round(demands[z["id"]][t], 1) for z in ZONES),
            ])
    print(f"  wrote {fp.name} ({N} rows, {len(ZONES)} zones)")


def write_variability(resolution: str, rng: random.Random) -> None:
    N = steps_per_year(resolution)
    resources = discover_resources()
    if not resources:
        raise RuntimeError(
            "No resources discovered in resources/*.csv — run with resource "
            "CSVs in place."
        )
    series = {name: profile_for(name, zone_id, resolution, rng)
              for name, zone_id in resources}
    fp = SYS / "Generators_variability.csv"
    cols = [name for name, _ in resources]
    with fp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time_Index"] + cols)
        for t in range(N):
            w.writerow([t + 1] + [round(series[c][t], 5) for c in cols])
    print(f"  wrote {fp.name} ({N} rows, {len(cols)} resources)")


def write_fuels(resolution: str) -> None:
    N = steps_per_year(resolution)
    emit = {"SE_uranium": 0.0, "SE_oil": 0.075, "SE_biomass": 0.0, "None": 0.0}
    base = {"SE_uranium": 0.5, "SE_oil": 15.0, "SE_biomass": 8.0, "None": 0.0}

    def price(t, b, amp=0.15):
        d = day_of_year(t, resolution)
        return b * (1.0 + amp * math.cos(2 * math.pi * (d - 15) / 365))

    cols = ["SE_uranium", "SE_oil", "SE_biomass", "None"]
    fp = SYS / "Fuels_data.csv"
    with fp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time_Index"] + cols)
        w.writerow([0] + [emit[c] for c in cols])
        for t in range(N):
            row = [t + 1]
            for c in cols:
                row.append(0 if c == "None" else round(price(t, base[c]), 4))
            w.writerow(row)
    print(f"  wrote {fp.name} ({N + 1} rows incl. emission factors)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resolution", choices=["1h", "15min"], default="1h",
                    help="Time step length (default: 1h)")
    ap.add_argument("--seed", type=int, default=20260511,
                    help="RNG seed for reproducible output")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    N = steps_per_year(args.resolution)
    print(f"Building Nordic time-series in {SYS}/ ({args.resolution}, {N} steps, "
          f"{len(ZONES)} zones)")
    write_demand(args.resolution, rng)
    write_variability(args.resolution, rng)
    write_fuels(args.resolution)
    print(f"Done. {N} timesteps × {len(ZONES)} zones. seed={args.seed}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

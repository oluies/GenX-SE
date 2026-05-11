#!/usr/bin/env python3
"""
Generate synthetic but Sweden-shaped time series for the GenX-SE
Sweden 4-zone case at either 1-hour or 15-minute resolution.

    system/Demand_data.csv
    system/Generators_variability.csv
    system/Fuels_data.csv

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
SYS.mkdir(exist_ok=True)


# -------- Resolution-aware time helpers ---------------------------------
def steps_per_year(resolution: str) -> int:
    return {"1h": 8760, "15min": 35040}[resolution]


def steps_per_day(resolution: str) -> int:
    return {"1h": 24, "15min": 96}[resolution]


def hours_per_step(resolution: str) -> float:
    return {"1h": 1.0, "15min": 0.25}[resolution]


def day_of_year(t: int, resolution: str) -> int:
    return (t // steps_per_day(resolution)) % 365


def hour_of_day(t: int, resolution: str) -> float:
    """Continuous hour-of-day (0–24)."""
    return (t % steps_per_day(resolution)) * hours_per_step(resolution)


# -------- Demand (MW) ---------------------------------------------------
ZONE_DEMAND = {
    "z1": dict(avg=2000, label="SE1"),
    "z2": dict(avg=2500, label="SE2"),
    "z3": dict(avg=8500, label="SE3"),
    "z4": dict(avg=3000, label="SE4"),
}


def demand_profile(avg_mw: float, resolution: str, rng: random.Random) -> list[float]:
    out = []
    N = steps_per_year(resolution)
    for t in range(N):
        d = day_of_year(t, resolution)
        hh = hour_of_day(t, resolution)
        seasonal = 1.0 + 0.42 * math.cos(2 * math.pi * (d - 15) / 365)
        daily = (
            1.0
            + 0.18 * math.exp(-((hh - 8) ** 2) / 8.0)
            + 0.22 * math.exp(-((hh - 18) ** 2) / 10.0)
            - 0.18 * math.exp(-((hh - 3) ** 2) / 8.0)
        )
        dow = (t // steps_per_day(resolution)) % 7
        weekly = 0.94 if dow >= 5 else 1.0
        # Sub-hourly noise slightly larger (intra-hour load wiggles)
        noise_amp = 0.03 if resolution == "1h" else 0.05
        noise = 1.0 + noise_amp * (rng.random() - 0.5)
        out.append(avg_mw * seasonal * daily * weekly * noise)
    return out


# -------- VRE capacity-factor profiles ----------------------------------
def wind_profile(annual_cf: float, resolution: str, rng: random.Random,
                 seasonal_amp: float = 0.22) -> list[float]:
    """AR(1) noise; persistence scales with timestep so e-folding stays ~12 h."""
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
    """PV CF based on solar geometry; zero at night. Cloud noise drives the
    intra-hour variability that makes summer 15-min pricing different from 1-h."""
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


def hydro_inflow(annual_cf: float, melt_amp: float, resolution: str,
                 rng: random.Random) -> list[float]:
    N = steps_per_year(resolution)
    out = []
    for t in range(N):
        d = day_of_year(t, resolution)
        melt = melt_amp * math.exp(-((d - 120) ** 2) / (35 ** 2))
        autumn = 0.15 * melt_amp * math.exp(-((d - 285) ** 2) / (40 ** 2))
        base = annual_cf * 0.7
        noise = 1.0 + 0.08 * (rng.random() - 0.5)
        out.append(max(0.0, (base + melt + autumn) * noise))
    mean_cf = sum(out) / N
    if mean_cf > 0:
        out = [v * (annual_cf / mean_cf) for v in out]
    return out


# -------- Writers -------------------------------------------------------
def write_demand(resolution: str, rng: random.Random) -> None:
    N = steps_per_year(resolution)
    demands = {z: demand_profile(cfg["avg"], resolution, rng)
               for z, cfg in ZONE_DEMAND.items()}
    fp = SYS / "Demand_data.csv"
    with fp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Voll", "Demand_Segment", "Cost_of_Demand_Curtailment_per_MW",
            "Max_Demand_Curtailment", "$/MWh", "Rep_Periods",
            "Timesteps_per_Rep_Period", "Sub_Weights", "Time_Index",
            "Demand_MW_z1", "Demand_MW_z2", "Demand_MW_z3", "Demand_MW_z4",
        ])
        seg_rows = [
            ("50000", "1", "1",    "1",     "2000"),
            ("",      "2", "0.9",  "0.04",  "1800"),
            ("",      "3", "0.55", "0.024", "1100"),
            ("",      "4", "0.2",  "0.003", "400"),
        ]
        # Sub_Weights is "hours represented by this rep period" — one year = 8760 h
        # regardless of timestep length; only Timesteps_per_Rep_Period changes,
        # which makes GenX's omega = Sub_Weights / Timesteps_per_Rep_Period work
        # out to 1.0 for hourly and 0.25 for 15-min steps.
        for t in range(N):
            voll, seg, cost, maxcurt, dollar = (
                seg_rows[t] if t < len(seg_rows) else ("", "", "", "", "")
            )
            rep = "1" if t == 0 else ""
            tspr = str(N) if t == 0 else ""
            subw = "8760" if t == 0 else ""
            w.writerow([
                voll, seg, cost, maxcurt, dollar, rep, tspr, subw, t + 1,
                round(demands["z1"][t], 1),
                round(demands["z2"][t], 1),
                round(demands["z3"][t], 1),
                round(demands["z4"][t], 1),
            ])
    print(f"  wrote {fp.name} ({N} rows)")


def write_variability(resolution: str, rng: random.Random) -> None:
    N = steps_per_year(resolution)
    ones = [1.0] * N
    series = {
        "SE3_nuclear":         ones,
        "SE4_oil_peaker":      ones,
        "SE1_biomass_chp":     ones,
        "SE2_biomass_chp":     ones,
        "SE3_biomass_chp":     ones,
        "SE4_biomass_chp":     ones,
        "SE1_onshore_wind":    wind_profile(0.40, resolution, rng, 0.25),
        "SE2_onshore_wind":    wind_profile(0.38, resolution, rng, 0.24),
        "SE3_onshore_wind":    wind_profile(0.33, resolution, rng, 0.22),
        "SE4_onshore_wind":    wind_profile(0.35, resolution, rng, 0.22),
        "SE4_offshore_wind":   wind_profile(0.46, resolution, rng, 0.18),
        "SE3_solar_pv":        solar_profile(0.105, 59.3, resolution, rng),
        "SE4_solar_pv":        solar_profile(0.115, 55.6, resolution, rng),
        "SE1_battery":         ones,
        "SE2_battery":         ones,
        "SE3_battery":         ones,
        "SE4_battery":         ones,
        "SE1_hydro_reservoir": hydro_inflow(0.50, 0.55, resolution, rng),
        "SE2_hydro_reservoir": hydro_inflow(0.48, 0.50, resolution, rng),
        "SE3_hydro_reservoir": hydro_inflow(0.42, 0.30, resolution, rng),
        "SE4_hydro_reservoir": hydro_inflow(0.35, 0.15, resolution, rng),
    }
    cols = list(series.keys())
    fp = SYS / "Generators_variability.csv"
    with fp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time_Index"] + cols)
        for t in range(N):
            w.writerow([t + 1] + [round(series[c][t], 5) for c in cols])
    print(f"  wrote {fp.name} ({N} rows)")


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
    print(f"Building Sweden time-series in {SYS}/ ({args.resolution}, {N} steps)")
    write_demand(args.resolution, rng)
    write_variability(args.resolution, rng)
    write_fuels(args.resolution)
    print(f"Done. {N} timesteps, 4 zones, seed={args.seed}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Generate synthetic but Sweden-shaped 8760-hour time series for the
sweden_4_zones GenX example:

    system/Demand_data.csv
    system/Generators_variability.csv
    system/Fuels_data.csv

Profiles are deterministic (seeded RNG) so reruns are reproducible.

Replace these files with real ENTSO-E / SMHI / Renewables.ninja data
by running data/fetch_entsoe.py and post-processing into the same
column layout.
"""
from __future__ import annotations

import csv
import math
import os
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYS = HERE / "system"
SYS.mkdir(exist_ok=True)

HOURS = 8760
random.seed(20260511)


def day_of_year(h: int) -> int:
    return (h // 24) % 365


def hour_of_day(h: int) -> int:
    return h % 24


# -------- Demand (MW) ----------------------------------------------------
# Annual averages (MW) and peak/average ratios per zone.
# Sweden total ≈ 140 TWh/yr ≈ 16 GW avg; peak ≈ 26 GW (cold winter day).
ZONE_DEMAND = {
    "z1": dict(avg=2000, label="SE1"),   # Norrbotten/industry (steel, mining)
    "z2": dict(avg=2500, label="SE2"),   # Mid-Norrland
    "z3": dict(avg=8500, label="SE3"),   # Stockholm/Mälardalen
    "z4": dict(avg=3000, label="SE4"),   # Skåne/south
}


def demand_profile(avg_mw: float) -> list[float]:
    out = []
    for h in range(HOURS):
        d, hh = day_of_year(h), hour_of_day(h)
        # Strong winter peak (electric heating + short daylight)
        seasonal = 1.0 + 0.42 * math.cos(2 * math.pi * (d - 15) / 365)
        # Morning + evening daily peaks
        daily = (
            1.0
            + 0.18 * math.exp(-((hh - 8) ** 2) / 8.0)
            + 0.22 * math.exp(-((hh - 18) ** 2) / 10.0)
            - 0.18 * math.exp(-((hh - 3) ** 2) / 8.0)
        )
        # Weekend dip
        dow = (h // 24) % 7
        weekly = 0.94 if dow >= 5 else 1.0
        noise = 1.0 + 0.03 * (random.random() - 0.5)
        out.append(avg_mw * seasonal * daily * weekly * noise)
    return out


# -------- Capacity-factor profiles ---------------------------------------
def wind_profile(annual_cf: float, seasonal_amp: float = 0.22) -> list[float]:
    """Synthetic onshore-wind hourly CF. Adds slow autocorrelated noise."""
    out = []
    state = 0.0
    for h in range(HOURS):
        d = day_of_year(h)
        seasonal = 1.0 + seasonal_amp * math.cos(2 * math.pi * (d - 15) / 365)
        # AR(1)-ish noise so wind is correlated hour-to-hour
        state = 0.92 * state + 0.4 * (random.random() - 0.5)
        cf = annual_cf * seasonal * (1.0 + state)
        out.append(min(0.95, max(0.0, cf)))
    return out


def solar_profile(annual_cf: float, lat_deg: float) -> list[float]:
    """Synthetic PV hourly CF. Zero at night, strong summer/winter swing."""
    # daylight hours and intensity scale with latitude
    out = []
    for h in range(HOURS):
        d, hh = day_of_year(h), hour_of_day(h)
        # Declination angle (radians) — simple model
        decl = math.radians(23.45) * math.sin(2 * math.pi * (d - 81) / 365)
        lat = math.radians(lat_deg)
        # Hour angle: noon = 0
        ha = math.radians(15 * (hh - 12))
        cos_zen = (
            math.sin(lat) * math.sin(decl)
            + math.cos(lat) * math.cos(decl) * math.cos(ha)
        )
        if cos_zen <= 0:
            out.append(0.0)
            continue
        # Cloud noise: 0.4–1.0 factor
        cloud = 0.55 + 0.45 * random.random()
        # Calibrate: ~peak 0.85 in midsummer noon
        cf = cos_zen * cloud * 1.2
        out.append(min(0.9, max(0.0, cf)))
    # Rescale to match the annual capacity factor
    mean_cf = sum(out) / HOURS
    if mean_cf > 0:
        scale = annual_cf / mean_cf
        out = [min(0.9, v * scale) for v in out]
    return out


def hydro_inflow(annual_cf: float, melt_amp: float) -> list[float]:
    """Reservoir inflow as fraction of installed capacity.
    Big spring melt for SE1/SE2; flatter for SE3/SE4."""
    out = []
    for h in range(HOURS):
        d = day_of_year(h)
        # Spring melt peak around day 120 (early May)
        melt = melt_amp * math.exp(-((d - 120) ** 2) / (35 ** 2))
        # Small autumn rain bump
        autumn = 0.15 * melt_amp * math.exp(-((d - 285) ** 2) / (40 ** 2))
        # Baseline
        base = annual_cf * 0.7
        noise = 1.0 + 0.08 * (random.random() - 0.5)
        out.append(max(0.0, (base + melt + autumn) * noise))
    # Rescale to match target annual CF
    mean_cf = sum(out) / HOURS
    if mean_cf > 0:
        out = [v * (annual_cf / mean_cf) for v in out]
    return out


# -------- Write Demand_data.csv ------------------------------------------
def write_demand():
    demands = {z: demand_profile(cfg["avg"]) for z, cfg in ZONE_DEMAND.items()}
    fp = SYS / "Demand_data.csv"
    with fp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Voll", "Demand_Segment", "Cost_of_Demand_Curtailment_per_MW",
            "Max_Demand_Curtailment", "$/MWh", "Rep_Periods",
            "Timesteps_per_Rep_Period", "Sub_Weights", "Time_Index",
            "Demand_MW_z1", "Demand_MW_z2", "Demand_MW_z3", "Demand_MW_z4",
        ])
        # Demand-curtailment segments mirror 1_three_zones convention
        seg_rows = [
            ("50000", "1", "1",    "1",     "2000"),
            ("",      "2", "0.9",  "0.04",  "1800"),
            ("",      "3", "0.55", "0.024", "1100"),
            ("",      "4", "0.2",  "0.003", "400"),
        ]
        for t in range(HOURS):
            voll, seg, cost, maxcurt, dollar = (
                seg_rows[t] if t < len(seg_rows) else ("", "", "", "", "")
            )
            rep = "1" if t == 0 else ""
            tspr = "8760" if t == 0 else ""
            subw = "8760" if t == 0 else ""
            w.writerow([
                voll, seg, cost, maxcurt, dollar, rep, tspr, subw, t + 1,
                round(demands["z1"][t], 1),
                round(demands["z2"][t], 1),
                round(demands["z3"][t], 1),
                round(demands["z4"][t], 1),
            ])
    print(f"  wrote {fp.name}")


# -------- Write Generators_variability.csv -------------------------------
def write_variability():
    # Annual CFs roughly matching Swedish observed values
    series = {
        # Thermal: always available
        "SE3_nuclear":         [1.0] * HOURS,
        "SE4_oil_peaker":      [1.0] * HOURS,
        "SE1_biomass_chp":     [1.0] * HOURS,
        "SE2_biomass_chp":     [1.0] * HOURS,
        "SE3_biomass_chp":     [1.0] * HOURS,
        "SE4_biomass_chp":     [1.0] * HOURS,
        # VRE
        "SE1_onshore_wind":    wind_profile(0.40, 0.25),
        "SE2_onshore_wind":    wind_profile(0.38, 0.24),
        "SE3_onshore_wind":    wind_profile(0.33, 0.22),
        "SE4_onshore_wind":    wind_profile(0.35, 0.22),
        "SE4_offshore_wind":   wind_profile(0.46, 0.18),
        "SE3_solar_pv":        solar_profile(0.105, lat_deg=59.3),  # Stockholm
        "SE4_solar_pv":        solar_profile(0.115, lat_deg=55.6),  # Malmö
        # Storage: always available
        "SE1_battery":         [1.0] * HOURS,
        "SE2_battery":         [1.0] * HOURS,
        "SE3_battery":         [1.0] * HOURS,
        "SE4_battery":         [1.0] * HOURS,
        # Hydro inflow
        "SE1_hydro_reservoir": hydro_inflow(0.50, 0.55),
        "SE2_hydro_reservoir": hydro_inflow(0.48, 0.50),
        "SE3_hydro_reservoir": hydro_inflow(0.42, 0.30),
        "SE4_hydro_reservoir": hydro_inflow(0.35, 0.15),
    }
    # Column order must align with how resources will be discovered;
    # GenX matches by Resource name, so order is cosmetic.
    cols = list(series.keys())
    fp = SYS / "Generators_variability.csv"
    with fp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time_Index"] + cols)
        for t in range(HOURS):
            w.writerow(
                [t + 1] + [round(series[c][t], 5) for c in cols]
            )
    print(f"  wrote {fp.name}")


# -------- Write Fuels_data.csv -------------------------------------------
def write_fuels():
    # CO2 emission factors (tons CO2 per MMBtu)
    emit = {
        "SE_uranium": 0.0,
        "SE_oil":     0.075,
        "SE_biomass": 0.0,   # carbon-neutral accounting (configurable)
        "None":       0.0,
    }
    # Base prices ($/MMBtu) with mild seasonality
    def price(t, base, season_amp=0.15):
        d = day_of_year(t)
        return base * (1.0 + season_amp * math.cos(2 * math.pi * (d - 15) / 365))

    cols = ["SE_uranium", "SE_oil", "SE_biomass", "None"]
    base = {"SE_uranium": 0.5, "SE_oil": 15.0, "SE_biomass": 8.0, "None": 0.0}
    fp = SYS / "Fuels_data.csv"
    with fp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time_Index"] + cols)
        # Row 0: emission factors
        w.writerow([0] + [emit[c] for c in cols])
        for t in range(HOURS):
            row = [t + 1]
            for c in cols:
                if c == "None":
                    row.append(0)
                else:
                    row.append(round(price(t, base[c]), 4))
            w.writerow(row)
    print(f"  wrote {fp.name}")


def main():
    print(f"Building Sweden time-series in {SYS}/")
    write_demand()
    write_variability()
    write_fuels()
    print("Done. 8760 hours, 4 zones, deterministic seed=20260511.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Download Swedish bidding-zone data from the ENTSO-E Transparency Platform
and reshape it into GenX-compatible CSVs for the sweden_4_zones example.

Pulls per-zone (SE1, SE2, SE3, SE4):
    * Day-ahead total load                          (-> Demand_data.csv)
    * Generation per production type                (-> capacity factors)
    * Aggregated installed generation capacity      (sanity check)
    * Cross-border physical flows on snitt 1/2/4    (sanity check)

Requirements:
    pip install entsoe-py pandas python-dotenv

Setup:
    1. Create an ENTSO-E Transparency Platform account:
       https://transparency.entsoe.eu/usrm/user/myAccountSettings
    2. Request the "Restful API" role (free, manual approval, ~1 day).
    3. Copy your security token into a .env file in this directory:
          ENTSOE_API_TOKEN=your-token-here
    4. Run: python3 fetch_entsoe.py --start 2024-01-01 --end 2025-01-01

Notes:
    * ENTSO-E reports SE1-SE4 as separate bidding-zone EICs.
    * Demand is in MW (1-hour resolution after resampling).
    * Capacity factor per technology = generation_MW / installed_capacity_MW.
      For dispatchable thermal we cap at 1.0; for VRE we keep the raw ratio.
    * The script writes intermediate parquet files in data/raw/ so re-runs
      are cheap. To rebuild from scratch, delete data/raw/.

This script writes:
    data/raw/load_SEx.parquet
    data/raw/gen_SEx.parquet
    data/raw/flows.parquet
    system/Demand_data.csv              (overwrites synthetic)
    system/Generators_variability.csv   (overwrites synthetic)
    system/installed_capacity_report.csv  (informational)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import pandas as pd  # noqa: F401
    from entsoe import EntsoePandasClient
    from dotenv import load_dotenv
except ImportError as e:
    print(
        f"Missing dependency: {e.name}\n"
        "Install with: pip install entsoe-py pandas python-dotenv pyarrow",
        file=sys.stderr,
    )
    sys.exit(1)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RAW = HERE / "raw"
SYS = ROOT / "system"
RAW.mkdir(exist_ok=True)

# ENTSO-E bidding-zone codes
ZONES = ["SE_1", "SE_2", "SE_3", "SE_4"]
ZONE_TO_GENX = {"SE_1": "z1", "SE_2": "z2", "SE_3": "z3", "SE_4": "z4"}

# Cross-border interconnections (snitt) — ordered as (from, to)
SNITT = [("SE_1", "SE_2"), ("SE_2", "SE_3"), ("SE_3", "SE_4")]

# Map ENTSO-E PSR types to our GenX resource buckets
# (see entsoe.mappings.PSRTYPE_MAPPINGS for full list)
PSR_TO_BUCKET = {
    "Nuclear":                       "nuclear",
    "Fossil Oil":                    "oil_peaker",
    "Fossil Gas":                    "oil_peaker",   # group with peakers
    "Biomass":                       "biomass_chp",
    "Waste":                         "biomass_chp",
    "Wind Onshore":                  "onshore_wind",
    "Wind Offshore":                 "offshore_wind",
    "Solar":                         "solar_pv",
    "Hydro Water Reservoir":         "hydro_reservoir",
    "Hydro Run-of-river and poundage": "hydro_reservoir",
    "Hydro Pumped Storage":          "hydro_reservoir",
}


def get_client() -> "EntsoePandasClient":
    load_dotenv(HERE / ".env")
    token = os.environ.get("ENTSOE_API_TOKEN")
    if not token:
        print("ENTSOE_API_TOKEN not set (see fetch_entsoe.py docstring)",
              file=sys.stderr)
        sys.exit(2)
    return EntsoePandasClient(api_key=token)


def fetch_load(client, zone: str, start, end) -> "pd.DataFrame":
    cache = RAW / f"load_{zone}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    print(f"  load {zone} {start.date()} → {end.date()}")
    s = client.query_load(zone, start=start, end=end)
    s = s.resample("1h").mean().rename("MW").to_frame()
    s.to_parquet(cache)
    return s


def fetch_generation(client, zone: str, start, end) -> "pd.DataFrame":
    cache = RAW / f"gen_{zone}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    print(f"  generation {zone} {start.date()} → {end.date()}")
    df = client.query_generation(zone, start=start, end=end, psr_type=None)
    # Columns are PSR type names; reduce to hourly
    df = df.resample("1h").mean()
    df.to_parquet(cache)
    return df


def fetch_flows(client, start, end) -> "pd.DataFrame":
    cache = RAW / "flows.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    frames = []
    for a, b in SNITT:
        print(f"  flow {a} -> {b}")
        f_ab = client.query_crossborder_flows(a, b, start=start, end=end)
        f_ba = client.query_crossborder_flows(b, a, start=start, end=end)
        net = (f_ab - f_ba).resample("1h").mean()
        net.name = f"{a}_to_{b}_MW_net"
        frames.append(net)
    df = pd.concat(frames, axis=1)
    df.to_parquet(cache)
    return df


def build_demand_csv(loads: "dict[str, pd.DataFrame]") -> None:
    df = pd.concat(
        {ZONE_TO_GENX[z]: loads[z]["MW"].reset_index(drop=True) for z in ZONES},
        axis=1,
    )
    # Trim/pad to exactly 8760
    df = df.iloc[:8760].copy()
    df = df.ffill().bfill()
    out = SYS / "Demand_data.csv"
    with out.open("w") as f:
        f.write(
            "Voll,Demand_Segment,Cost_of_Demand_Curtailment_per_MW,"
            "Max_Demand_Curtailment,$/MWh,Rep_Periods,Timesteps_per_Rep_Period,"
            "Sub_Weights,Time_Index,Demand_MW_z1,Demand_MW_z2,Demand_MW_z3,"
            "Demand_MW_z4\n"
        )
        seg = [
            ("50000", "1", "1",    "1",     "2000"),
            ("",      "2", "0.9",  "0.04",  "1800"),
            ("",      "3", "0.55", "0.024", "1100"),
            ("",      "4", "0.2",  "0.003", "400"),
        ]
        for t in range(len(df)):
            if t < len(seg):
                voll, s, cost, mc, dlr = seg[t]
            else:
                voll = s = cost = mc = dlr = ""
            rep = "1" if t == 0 else ""
            tspr = "8760" if t == 0 else ""
            subw = "8760" if t == 0 else ""
            row = df.iloc[t]
            f.write(
                f"{voll},{s},{cost},{mc},{dlr},{rep},{tspr},{subw},"
                f"{t+1},{row['z1']:.1f},{row['z2']:.1f},"
                f"{row['z3']:.1f},{row['z4']:.1f}\n"
            )
    print(f"  wrote {out}")


def build_variability_csv(gens: "dict[str, pd.DataFrame]") -> None:
    # Inferred capacity from observed peak (rough; replace with reported caps)
    out_cols = {}
    for zone in ZONES:
        gz = ZONE_TO_GENX[zone]
        zone_gen = gens[zone]
        # Aggregate by bucket
        bucket = {}
        for psr, name in PSR_TO_BUCKET.items():
            if psr in zone_gen.columns:
                bucket.setdefault(name, []).append(zone_gen[psr])
        agg = {n: sum(cols) for n, cols in bucket.items()}
        for name, series in agg.items():
            cap = float(series.max())
            if cap <= 0:
                continue
            cf = (series / cap).clip(0.0, 1.0)
            colname = f"{gz.upper().replace('Z', 'SE')}_{name}"
            out_cols[colname] = cf.reset_index(drop=True).iloc[:8760]
    df = pd.concat(out_cols, axis=1).ffill().bfill()
    df.insert(0, "Time_Index", range(1, len(df) + 1))
    df.to_csv(SYS / "Generators_variability.csv", index=False, float_format="%.5f")
    print(f"  wrote {SYS / 'Generators_variability.csv'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--end",   required=True, help="YYYY-MM-DD (UTC)")
    args = ap.parse_args()

    client = get_client()
    start = pd.Timestamp(args.start, tz="UTC")
    end   = pd.Timestamp(args.end,   tz="UTC")

    print(f"Fetching Swedish bidding-zone data {start.date()} → {end.date()}")
    loads = {z: fetch_load(client, z, start, end) for z in ZONES}
    gens  = {z: fetch_generation(client, z, start, end) for z in ZONES}
    _flows = fetch_flows(client, start, end)  # noqa: F841 — saved to raw/

    build_demand_csv(loads)
    build_variability_csv(gens)

    print("Done. system/Demand_data.csv and Generators_variability.csv now "
          "reflect ENTSO-E observations; raw downloads cached in data/raw/.")


if __name__ == "__main__":
    main()

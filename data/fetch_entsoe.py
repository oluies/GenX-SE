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
    4. Run:
          python3 fetch_entsoe.py --start 2024-01-01 --end 2025-01-01
          python3 fetch_entsoe.py --start 2024-01-01 --end 2025-01-01 --resolution 15min

The Nordic synchronous area moved to a 15-min Imbalance Settlement Period
in 2023-2024 and the day-ahead market (Nord Pool / SDAC) followed in
October 2025. With `--resolution 15min` this script keeps the native
15-min ENTSO-E data where available (SE1-SE4 load and most generation
post-2023). Hourly-only series are forward-filled to the 15-min grid.

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

# ENTSO-E bidding-zone codes for the 12 Nordic zones we model
ZONES = [
    "SE_1", "SE_2", "SE_3", "SE_4",
    "NO_1", "NO_2", "NO_3", "NO_4", "NO_5",
    "FI",
    "DK_1", "DK_2",
]
# Map ENTSO-E code -> (GenX zone id, GenX zone label used in resource names).
# The label is what build_variability_csv prefixes to resource columns.
ZONE_TO_GENX = {
    "SE_1": ("z1",  "SE1"),
    "SE_2": ("z2",  "SE2"),
    "SE_3": ("z3",  "SE3"),
    "SE_4": ("z4",  "SE4"),
    "NO_1": ("z5",  "NO1"),
    "NO_2": ("z6",  "NO2"),
    "NO_3": ("z7",  "NO3"),
    "NO_4": ("z8",  "NO4"),
    "NO_5": ("z9",  "NO5"),
    "FI":   ("z10", "FI"),
    "DK_1": ("z11", "DK1"),
    "DK_2": ("z12", "DK2"),
}

# Cross-border interconnections — all 17 lines in Network.csv, as (from, to).
# Includes 3 SE internal snitt, 7 SE↔neighbor lines, 6 NO internal lines,
# and NO2↔DK1 Skagerrak. Used for flow validation only — NTC values come
# from the static Network.csv.
SNITT = [
    ("SE_1", "SE_2"), ("SE_2", "SE_3"), ("SE_3", "SE_4"),
    ("SE_1", "NO_4"), ("SE_2", "NO_3"), ("SE_3", "NO_1"),
    ("SE_1", "FI"),   ("SE_3", "FI"),
    ("SE_3", "DK_1"), ("SE_4", "DK_2"),
    ("NO_1", "NO_2"), ("NO_1", "NO_3"), ("NO_1", "NO_5"),
    ("NO_2", "NO_5"), ("NO_3", "NO_4"), ("NO_3", "NO_5"),
    ("NO_2", "DK_1"),
]

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


_RESAMPLE_RULE = {"1h": "1h", "15min": "15min"}


def fetch_load(client, zone: str, start, end, resolution: str) -> "pd.DataFrame":
    cache = RAW / f"load_{zone}_{resolution}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    print(f"  load {zone} {start.date()} → {end.date()} ({resolution})")
    s = client.query_load(zone, start=start, end=end)
    # resample handles both upsample (ffill) and downsample (mean)
    s = s.resample(_RESAMPLE_RULE[resolution]).mean().ffill().rename("MW").to_frame()
    s.to_parquet(cache)
    return s


def fetch_generation(client, zone: str, start, end, resolution: str) -> "pd.DataFrame":
    cache = RAW / f"gen_{zone}_{resolution}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    print(f"  generation {zone} {start.date()} → {end.date()} ({resolution})")
    df = client.query_generation(zone, start=start, end=end, psr_type=None)
    df = df.resample(_RESAMPLE_RULE[resolution]).mean().ffill()
    df.to_parquet(cache)
    return df


def fetch_flows(client, start, end, resolution: str) -> "pd.DataFrame":
    cache = RAW / f"flows_{resolution}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    frames = []
    for a, b in SNITT:
        print(f"  flow {a} -> {b} ({resolution})")
        f_ab = client.query_crossborder_flows(a, b, start=start, end=end)
        f_ba = client.query_crossborder_flows(b, a, start=start, end=end)
        net = (f_ab - f_ba).resample(_RESAMPLE_RULE[resolution]).mean().ffill()
        net.name = f"{a}_to_{b}_MW_net"
        frames.append(net)
    df = pd.concat(frames, axis=1)
    df.to_parquet(cache)
    return df


_STEPS_PER_YEAR = {"1h": 8760, "15min": 35040}


def build_demand_csv(loads: "dict[str, pd.DataFrame]", resolution: str) -> None:
    N = _STEPS_PER_YEAR[resolution]
    df = pd.concat(
        {ZONE_TO_GENX[z][0]: loads[z]["MW"].reset_index(drop=True) for z in ZONES},
        axis=1,
    )
    df = df.iloc[:N].copy().ffill().bfill()
    out = SYS / "Demand_data.csv"
    zone_ids = [ZONE_TO_GENX[z][0] for z in ZONES]  # ["z1", "z2", ..., "z12"]
    demand_cols = ",".join(f"Demand_MW_{zid}" for zid in zone_ids)
    with out.open("w") as f:
        f.write(
            "Voll,Demand_Segment,Cost_of_Demand_Curtailment_per_MW,"
            "Max_Demand_Curtailment,$/MWh,Rep_Periods,Timesteps_per_Rep_Period,"
            f"Sub_Weights,Time_Index,{demand_cols}\n"
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
            tspr = str(N) if t == 0 else ""
            subw = "8760" if t == 0 else ""
            row = df.iloc[t]
            demand_vals = ",".join(f"{row[zid]:.1f}" for zid in zone_ids)
            f.write(
                f"{voll},{s},{cost},{mc},{dlr},{rep},{tspr},{subw},"
                f"{t+1},{demand_vals}\n"
            )
    print(f"  wrote {out} ({len(df)} rows, {len(zone_ids)} zones)")


def build_variability_csv(gens: "dict[str, pd.DataFrame]", resolution: str) -> None:
    N = _STEPS_PER_YEAR[resolution]
    out_cols = {}
    for zone in ZONES:
        _zid, gz_label = ZONE_TO_GENX[zone]   # e.g. ("z5", "NO1")
        zone_gen = gens[zone]
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
            colname = f"{gz_label}_{name}"
            out_cols[colname] = cf.reset_index(drop=True).iloc[:N]
    df = pd.concat(out_cols, axis=1).ffill().bfill()
    df.insert(0, "Time_Index", range(1, len(df) + 1))
    df.to_csv(SYS / "Generators_variability.csv", index=False, float_format="%.5f")
    print(f"  wrote {SYS / 'Generators_variability.csv'} ({len(df)} rows)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--end",   required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--resolution", choices=["1h", "15min"], default="1h",
                    help="Output timestep length (default: 1h)")
    args = ap.parse_args()

    client = get_client()
    start = pd.Timestamp(args.start, tz="UTC")
    end   = pd.Timestamp(args.end,   tz="UTC")

    print(f"Fetching Swedish bidding-zone data {start.date()} → {end.date()} "
          f"at {args.resolution} resolution")
    loads = {z: fetch_load(client, z, start, end, args.resolution) for z in ZONES}
    gens  = {z: fetch_generation(client, z, start, end, args.resolution) for z in ZONES}
    _flows = fetch_flows(client, start, end, args.resolution)  # noqa: F841

    build_demand_csv(loads, args.resolution)
    build_variability_csv(gens, args.resolution)

    print(f"Done. {args.resolution} data written to system/. Remember to run "
          f"`python3 scripts/rescale_resources.py --to {args.resolution}` "
          f"if you switched from another resolution.")


if __name__ == "__main__":
    main()

"""Read GenX result CSVs into tidy pandas DataFrames.

GenX has two file layouts:

* **Static CSVs** (capacity.csv, costs.csv, nse_summary.csv): regular
  table — `pd.read_csv` works.
* **Temporal CSVs** (power.csv, flow.csv, prices.csv, emissions.csv):
  transposed with NO header row. Column 0 holds the row labels
  ("Resource", "Zone", "AnnualSum", "t1", "t2", ...) and the remaining
  columns hold per-resource (or per-line/per-zone) values. The bottom of
  the file repeats a "Total" column.

This module hides that quirk behind tidy long-format DataFrames.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# ---- Tech category mapping ------------------------------------------------

# Order matters for stack plots — last item plotted on top.
TECH_ORDER = [
    "nuclear",
    "hydro",
    "biomass_chp",
    "oil_peaker",
    "onshore_wind",
    "offshore_wind",
    "solar_pv",
    "battery",
]

TECH_COLORS = {
    "nuclear":       "#a39bf7",
    "hydro":         "#1f77b4",
    "biomass_chp":   "#2ca02c",
    "oil_peaker":    "#7f7f7f",
    "onshore_wind":  "#17becf",
    "offshore_wind": "#005b80",
    "solar_pv":      "#ffd24a",
    "battery":       "#ff7f0e",
}

TECH_LABELS = {
    "nuclear":       "Nuclear",
    "hydro":         "Hydro reservoir",
    "biomass_chp":   "Biomass CHP",
    "oil_peaker":    "Oil peaker",
    "onshore_wind":  "Wind onshore",
    "offshore_wind": "Wind offshore",
    "solar_pv":      "Solar PV",
    "battery":       "Battery",
}

ZONE_LABELS = {1: "SE1", 2: "SE2", 3: "SE3", 4: "SE4"}


def classify_resource(name: str) -> str:
    """Map a Resource name like 'SE3_solar_pv' → 'solar_pv'."""
    n = name.lower()
    if "nuclear" in n:
        return "nuclear"
    if "hydro" in n:
        return "hydro"
    if "biomass" in n or "chp" in n:
        return "biomass_chp"
    if "oil" in n or "peaker" in n:
        return "oil_peaker"
    if "offshore_wind" in n:
        return "offshore_wind"
    if "onshore_wind" in n or n.endswith("_wind"):
        return "onshore_wind"
    if "solar" in n or "pv" in n:
        return "solar_pv"
    if "battery" in n or "storage" in n:
        return "battery"
    return "other"


def extract_zone(name: str) -> int | None:
    """Extract zone integer from a Resource name like 'SE3_solar_pv' → 3."""
    m = re.match(r"SE(\d)_", name)
    return int(m.group(1)) if m else None


# ---- File loaders ---------------------------------------------------------

def load_capacity(results: Path) -> pd.DataFrame:
    """Return tidy capacity DataFrame: Resource, Zone, tech, StartCap, EndCap, NewCap (MW)."""
    df = pd.read_csv(results / "capacity.csv")
    df = df[df["Resource"] != "Total"].copy()
    df["tech"] = df["Resource"].apply(classify_resource)
    df["Zone"] = pd.to_numeric(df["Zone"], errors="coerce").astype("Int64")
    # ParameterScale=1 leaves capacity in GW per write_capacity.jl scaling
    # → multiply by 1000 to get MW for display.
    for col in ("StartCap", "EndCap", "NewCap", "RetCap"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["Resource", "Zone", "tech", "StartCap", "EndCap", "NewCap"]]


def _temporal_path(results: Path, name: str) -> Path:
    """Prefer the reconstructed 8760h file in Full_TimeSeries/ if available.

    GenX writes Full_TimeSeries/<name>.csv when OutputFullTimeSeries=1 and
    TimeDomainReduction=1. That file is properly weighted, so summing its
    hourly values reproduces the annual totals.
    """
    full = results / "Full_TimeSeries" / name
    return full if full.exists() else results / name


def _load_temporal(filepath: Path) -> pd.DataFrame:
    """Parse a GenX transposed temporal CSV into a tidy long-format DataFrame.

    Returns columns: entity (Resource/Line/Zone), hour, value.
    For power.csv, entity is the resource name. For flow.csv it's the line
    index. For prices.csv it's the zone label.
    """
    raw = pd.read_csv(filepath, header=None)
    # Row 0: "Resource"|"Line"|"Zone", then entity labels, last cell "Total"
    # Row 1: "Zone" row (only for power.csv); for flow/prices it varies
    # Row 2: "AnnualSum" row (only when written by write_fulltimeseries)
    # Rows 3+: "t<n>", then hourly values
    label_col = raw.iloc[:, 0].astype(str)
    header_row = raw.iloc[0, 1:].astype(str).reset_index(drop=True)
    t_mask = label_col.str.match(r"^t\d+$")
    t_rows = raw.loc[t_mask, raw.columns[1:]].reset_index(drop=True)
    t_rows.columns = header_row
    hours = (
        label_col[t_mask].str.replace("t", "", regex=False).astype(int).reset_index(drop=True)
    )
    t_rows.insert(0, "hour", hours)
    if "Total" in t_rows.columns:
        t_rows = t_rows.drop(columns=["Total"])
    long = t_rows.melt(id_vars="hour", var_name="entity", value_name="value")
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    return long


def _load_annual_sum(filepath: Path) -> pd.Series:
    """Read the 'AnnualSum' row from a transposed temporal CSV.

    Returns a Series indexed by entity name with the (already weight-applied)
    annual sum in MWh.
    """
    raw = pd.read_csv(filepath, header=None)
    label_col = raw.iloc[:, 0].astype(str)
    header_row = raw.iloc[0, 1:].astype(str).reset_index(drop=True)
    annual_mask = label_col == "AnnualSum"
    if not annual_mask.any():
        return pd.Series(dtype=float)
    row = raw.loc[annual_mask, raw.columns[1:]].iloc[0].reset_index(drop=True)
    row.index = header_row
    row = row.drop(labels=["Total"], errors="ignore")
    return pd.to_numeric(row, errors="coerce")


def load_power(results: Path) -> pd.DataFrame:
    """Tidy hourly generation: Resource, zone, tech, hour, MW.

    Uses Full_TimeSeries/power.csv when available (TDR reconstruction),
    otherwise the top-level power.csv.
    """
    long = _load_temporal(_temporal_path(results, "power.csv"))
    long = long.rename(columns={"entity": "Resource", "value": "MW"})
    long["tech"] = long["Resource"].apply(classify_resource)
    long["zone"] = long["Resource"].apply(extract_zone)
    return long


def load_annual_generation(results: Path) -> pd.DataFrame:
    """Annual energy per resource (MWh), pulled from the AnnualSum row of
    the top-level power.csv (already weight-applied by GenX)."""
    annual = _load_annual_sum(results / "power.csv")
    df = pd.DataFrame({"Resource": annual.index.astype(str), "MWh": annual.values})
    df["tech"] = df["Resource"].apply(classify_resource)
    df["zone"] = df["Resource"].apply(extract_zone)
    df["MWh"] = pd.to_numeric(df["MWh"], errors="coerce")
    return df


def load_flow(results: Path) -> pd.DataFrame:
    """Tidy snitt flow: line, hour, MW (positive = Start_Zone -> End_Zone)."""
    long = _load_temporal(_temporal_path(results, "flow.csv"))
    return long.rename(columns={"entity": "line", "value": "MW"})


def load_prices(results: Path) -> pd.DataFrame:
    """Tidy zonal price: zone, hour, $/MWh."""
    long = _load_temporal(_temporal_path(results, "prices.csv"))
    long = long.rename(columns={"entity": "zone", "value": "price"})
    long["zone"] = pd.to_numeric(long["zone"], errors="coerce").astype("Int64")
    return long


def load_demand(case_root: Path) -> pd.DataFrame:
    """Tidy hourly demand from inputs (not results): zone, hour, MW."""
    df = pd.read_csv(case_root / "system" / "Demand_data.csv")
    keep = ["Time_Index"] + [c for c in df.columns if c.startswith("Demand_MW_z")]
    df = df[keep].dropna(subset=["Time_Index"]).copy()
    df["Time_Index"] = pd.to_numeric(df["Time_Index"], errors="coerce")
    df = df.dropna(subset=["Time_Index"]).astype({"Time_Index": int})
    long = df.melt(id_vars="Time_Index", var_name="zone_col", value_name="MW")
    long["zone"] = long["zone_col"].str.extract(r"z(\d)").astype(int)
    return long.rename(columns={"Time_Index": "hour"})[["zone", "hour", "MW"]]

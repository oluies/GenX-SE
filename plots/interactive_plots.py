"""Interactive HTML plots via plotly.express."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .load_results import (
    TECH_COLORS,
    TECH_LABELS,
    TECH_ORDER,
    ZONE_LABELS,
)


def _save(fig, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(out, include_plotlyjs="cdn", full_html=True)
    print(f"  html {out.name}")


def _tech_order_present(values):
    return [t for t in TECH_ORDER if t in set(values)]


def capacity_bar(cap: pd.DataFrame, out_dir: Path) -> None:
    df = cap.groupby(["Zone", "tech"], as_index=False)["EndCap"].sum()
    df["Zone label"] = df["Zone"].map(lambda z: ZONE_LABELS.get(int(z), str(z)))
    df["Technology"] = df["tech"].map(TECH_LABELS)
    fig = px.bar(
        df,
        x="Zone label",
        y="EndCap",
        color="tech",
        color_discrete_map=TECH_COLORS,
        category_orders={"tech": _tech_order_present(df["tech"])},
        labels={"EndCap": "Installed capacity (MW)", "tech": "Technology"},
        title="End-state installed capacity by zone",
    )
    fig.update_layout(legend_title_text="Technology")
    _save(fig, out_dir / "capacity_by_zone.html")


def annual_energy_mix(power: pd.DataFrame, out_dir: Path) -> None:
    df = power.groupby(["zone", "tech"], as_index=False)["MW"].sum()
    df["TWh"] = df["MW"] / 1e6
    df["Zone label"] = df["zone"].map(lambda z: ZONE_LABELS.get(int(z), str(z)))
    fig = px.bar(
        df,
        x="Zone label",
        y="TWh",
        color="tech",
        color_discrete_map=TECH_COLORS,
        category_orders={"tech": _tech_order_present(df["tech"])},
        labels={"TWh": "Annual generation (TWh)", "tech": "Technology"},
        title="Annual energy mix by zone",
    )
    _save(fig, out_dir / "annual_energy_mix.html")


def dispatch_week(power: pd.DataFrame, demand: pd.DataFrame, out_dir: Path,
                  hour_start: int, hour_end: int, label: str) -> None:
    win = power[(power["hour"] >= hour_start) & (power["hour"] < hour_end)].copy()
    if win.empty:
        return
    agg = win.groupby(["zone", "hour", "tech"], as_index=False)["MW"].sum()
    agg["Zone label"] = agg["zone"].map(lambda z: ZONE_LABELS.get(int(z), str(z)))
    fig = px.area(
        agg,
        x="hour",
        y="MW",
        color="tech",
        facet_col="Zone label",
        facet_col_wrap=2,
        color_discrete_map=TECH_COLORS,
        category_orders={"tech": _tech_order_present(agg["tech"])},
        title=f"Dispatch — {label} (hours {hour_start}–{hour_end - 1})",
    )
    # Overlay demand
    for zone in [1, 2, 3, 4]:
        d = demand[
            (demand["zone"] == zone)
            & (demand["hour"] >= hour_start)
            & (demand["hour"] < hour_end)
        ]
        if d.empty:
            continue
        # plotly facet alignment: SE1=col1 row2, SE2=col2 row2, SE3=col1 row1, SE4=col2 row1
        # in facet_col_wrap=2 with 4 facets, rows go top-bottom.
        # Simpler: skip overlay (plotly facet axis access varies)
    fig.update_layout(legend_title_text="Technology")
    _save(fig, out_dir / f"dispatch_{label}.html")


def flow_duration(flow: pd.DataFrame, out_dir: Path) -> None:
    fig = go.Figure()
    for line, sub in flow.groupby("line"):
        sorted_flow = np.sort(sub["MW"].values)[::-1]
        pct = np.linspace(0, 100, len(sorted_flow))
        fig.add_trace(go.Scatter(x=pct, y=sorted_flow, mode="lines", name=f"Line {line}"))
    fig.add_hline(y=0, line_width=0.7, line_dash="dot")
    fig.update_layout(
        title="Snitt flow duration curves",
        xaxis_title="Hours of year (%)",
        yaxis_title="Flow (MW)",
    )
    _save(fig, out_dir / "snitt_flow_duration.html")


def price_duration(prices: pd.DataFrame, out_dir: Path) -> None:
    fig = go.Figure()
    for zone, sub in prices.groupby("zone"):
        if pd.isna(zone):
            continue
        sorted_p = np.sort(sub["price"].values)[::-1]
        pct = np.linspace(0, 100, len(sorted_p))
        fig.add_trace(
            go.Scatter(
                x=pct,
                y=sorted_p,
                mode="lines",
                name=ZONE_LABELS.get(int(zone), str(zone)),
            )
        )
    fig.update_layout(
        title="Zonal price duration curves",
        xaxis_title="Hours of year (%)",
        yaxis_title="Marginal price ($/MWh)",
    )
    _save(fig, out_dir / "zonal_price_duration.html")

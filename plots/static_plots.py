"""Static PNG/SVG plots via matplotlib + seaborn."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from .load_results import (
    TECH_COLORS,
    TECH_LABELS,
    TECH_ORDER,
    ZONE_LABELS,
)

sns.set_theme(style="whitegrid", context="paper", font_scale=1.05)


def _save(fig, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160, bbox_inches="tight")
    fig.savefig(out.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)
    print(f"  png {out.name}")


def capacity_bar(cap: pd.DataFrame, out_dir: Path) -> None:
    g = (
        cap.groupby(["Zone", "tech"], as_index=False)["EndCap"]
        .sum()
        .pivot(index="Zone", columns="tech", values="EndCap")
        .reindex(columns=[t for t in TECH_ORDER if t in cap["tech"].unique()])
        .fillna(0.0)
    )
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bottoms = np.zeros(len(g.index))
    for tech in g.columns:
        vals = g[tech].values
        ax.bar(
            [ZONE_LABELS.get(int(z), str(z)) for z in g.index],
            vals,
            bottom=bottoms,
            color=TECH_COLORS.get(tech, "#bbb"),
            label=TECH_LABELS.get(tech, tech),
            edgecolor="white",
            linewidth=0.6,
        )
        bottoms += vals
    ax.set_ylabel("Installed capacity (MW)")
    ax.set_title("End-state installed capacity by zone")
    ax.legend(loc="upper right", frameon=False, fontsize=8)
    _save(fig, out_dir / "capacity_by_zone.png")


def annual_energy_mix(power: pd.DataFrame, out_dir: Path) -> None:
    energy = (
        power.groupby(["zone", "tech"], as_index=False)["MW"].sum()
        .rename(columns={"MW": "MWh"})
    )
    energy["TWh"] = energy["MWh"] / 1e6
    pivot = (
        energy.pivot(index="zone", columns="tech", values="TWh")
        .reindex(columns=[t for t in TECH_ORDER if t in energy["tech"].unique()])
        .fillna(0.0)
    )
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bottoms = np.zeros(len(pivot.index))
    for tech in pivot.columns:
        vals = pivot[tech].values
        ax.bar(
            [ZONE_LABELS.get(int(z), str(z)) for z in pivot.index],
            vals,
            bottom=bottoms,
            color=TECH_COLORS.get(tech, "#bbb"),
            label=TECH_LABELS.get(tech, tech),
            edgecolor="white",
            linewidth=0.6,
        )
        bottoms += vals
    ax.set_ylabel("Annual generation (TWh)")
    ax.set_title("Annual energy mix by zone")
    ax.legend(loc="upper right", frameon=False, fontsize=8)
    _save(fig, out_dir / "annual_energy_mix.png")


def dispatch_week(power: pd.DataFrame, demand: pd.DataFrame, out_dir: Path,
                  hour_start: int, hour_end: int, label: str) -> None:
    """Stacked-area dispatch for a 168-h window, one panel per zone."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
    for ax, zone in zip(axes.flatten(), [1, 2, 3, 4]):
        win = power[
            (power["zone"] == zone)
            & (power["hour"] >= hour_start)
            & (power["hour"] < hour_end)
        ]
        if win.empty:
            ax.set_visible(False)
            continue
        pivot = (
            win.groupby(["hour", "tech"], as_index=False)["MW"].sum()
            .pivot(index="hour", columns="tech", values="MW")
            .reindex(columns=[t for t in TECH_ORDER if t in win["tech"].unique()])
            .fillna(0.0)
        )
        ax.stackplot(
            pivot.index,
            *[pivot[t].values for t in pivot.columns],
            labels=[TECH_LABELS.get(t, t) for t in pivot.columns],
            colors=[TECH_COLORS.get(t, "#bbb") for t in pivot.columns],
        )
        d = demand[
            (demand["zone"] == zone)
            & (demand["hour"] >= hour_start)
            & (demand["hour"] < hour_end)
        ]
        ax.plot(d["hour"], d["MW"], color="black", lw=1.2, label="Demand")
        ax.set_title(ZONE_LABELS.get(zone))
        ax.set_ylabel("MW")
    axes[0, 0].legend(loc="upper right", frameon=False, fontsize=7, ncol=2)
    fig.suptitle(f"Dispatch — {label} (hours {hour_start}–{hour_end - 1})")
    fig.tight_layout()
    _save(fig, out_dir / f"dispatch_{label}.png")


def flow_duration(flow: pd.DataFrame, out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for line, sub in flow.groupby("line"):
        sorted_flow = np.sort(sub["MW"].values)[::-1]
        pct = np.linspace(0, 100, len(sorted_flow))
        ax.plot(pct, sorted_flow, label=f"Line {line}", lw=1.3)
    ax.axhline(0, color="black", lw=0.6, ls=":")
    ax.set_xlabel("Hours of year (%)")
    ax.set_ylabel("Flow (MW)")
    ax.set_title("Snitt flow duration curves")
    ax.legend(frameon=False, fontsize=8)
    _save(fig, out_dir / "snitt_flow_duration.png")


def price_duration(prices: pd.DataFrame, out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for zone, sub in prices.groupby("zone"):
        if pd.isna(zone):
            continue
        sorted_p = np.sort(sub["price"].values)[::-1]
        pct = np.linspace(0, 100, len(sorted_p))
        ax.plot(
            pct,
            sorted_p,
            label=ZONE_LABELS.get(int(zone), str(zone)),
            lw=1.4,
        )
    ax.set_xlabel("Hours of year (%)")
    ax.set_ylabel("Marginal price ($/MWh)")
    ax.set_title("Zonal price duration curves")
    ax.legend(frameon=False, fontsize=8)
    _save(fig, out_dir / "zonal_price_duration.png")

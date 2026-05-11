"""Render the full set of plots from a GenX results directory.

Usage:
    uv run python -m plots.make_plots [--results PATH] [--out PATH]

Reads CSVs from `results/` and writes:
    plots/output/png/*.png  (+ .svg)
    plots/output/html/*.html
"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import interactive_plots as ip
from . import static_plots as sp
from .load_results import (
    load_annual_generation,
    load_capacity,
    load_demand,
    load_flow,
    load_power,
    load_prices,
)

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(REPO / "results"),
                    help="GenX results directory")
    ap.add_argument("--out", default=str(REPO / "plots" / "output"),
                    help="Plot output directory")
    args = ap.parse_args()

    results = Path(args.results)
    out_png = Path(args.out) / "png"
    out_html = Path(args.out) / "html"

    if not results.exists():
        print(f"ERROR: results dir not found: {results}")
        print("Run `julia --project=. Run.jl` first to produce results/.")
        return 1

    print(f"Reading results from {results}")
    print(f"Writing PNG to       {out_png}")
    print(f"Writing HTML to      {out_html}")

    cap = load_capacity(results) if (results / "capacity.csv").exists() else None
    power = load_power(results) if (results / "power.csv").exists() else None
    flow = load_flow(results) if (results / "flow.csv").exists() else None
    prices = load_prices(results) if (results / "prices.csv").exists() else None
    demand = load_demand(REPO)

    if cap is not None:
        sp.capacity_bar(cap, out_png)
        ip.capacity_bar(cap, out_html)
    else:
        print("  skip capacity (no capacity.csv)")

    if power is not None:
        annual = load_annual_generation(results)
        sp.annual_energy_mix(annual, out_png)
        ip.annual_energy_mix(annual, out_html)

        # Winter week (mid-January) and summer week (mid-July) samples.
        # Use clamped windows so this works for both TDR and full 8760h runs.
        max_h = int(power["hour"].max())
        winter_end = min(168 * 3, max_h + 1)
        winter_start = max(0, winter_end - 168)
        summer_end = min(168 * 28, max_h + 1)
        summer_start = max(0, summer_end - 168)
        sp.dispatch_week(power, demand, out_png, winter_start, winter_end, "winter")
        sp.dispatch_week(power, demand, out_png, summer_start, summer_end, "summer")
        ip.dispatch_week(power, demand, out_html, winter_start, winter_end, "winter")
        ip.dispatch_week(power, demand, out_html, summer_start, summer_end, "summer")
    else:
        print("  skip power-based plots (no power.csv)")

    if flow is not None:
        sp.flow_duration(flow, out_png)
        ip.flow_duration(flow, out_html)
    else:
        print("  skip flow plots (no flow.csv)")

    if prices is not None:
        sp.price_duration(prices, out_png)
        ip.price_duration(prices, out_html)
    else:
        print("  skip price plots (no prices.csv)")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# How to run the Sweden 4-zone case

Step-by-step from a clean machine to dispatch results.

---

## 1. Prerequisites

* **Julia 1.9** (recommended). 1.10/1.11 also work but are slower per the
  GenX project's own benchmarks. Get it from <https://julialang.org/downloads/>
  or `brew install --cask julia` on macOS, or use `juliaup`:
  ```bash
  curl -fsSL https://install.julialang.org | sh
  juliaup add 1.9
  juliaup default 1.9
  ```
* **A solver.** The default is HiGHS (open-source, auto-installed by GenX).
  Gurobi/CPLEX work too if you have a license — adjust `settings/`.
* **(Optional) Python 3.9+** if you want to regenerate synthetic data or
  pull real ENTSO-E data.

Check:
```bash
julia --version    # 1.9.x preferred
python3 --version  # 3.9+ for the data scripts
```

---

## 2. First-time setup (install GenX)

From this directory:

```bash
cd Tutorials/example_systems_tutorials/sweden_4_zones/
julia --project=. -e 'using Pkg; Pkg.add("GenX"); Pkg.instantiate()'
```

This creates `Project.toml` + `Manifest.toml` pinned to a GenX version that
matches Julia 1.9. The first install pulls JuMP, HiGHS, MathOptInterface,
etc. — expect a few minutes and ~500 MB of packages.

> **Why `--project=.`?** It isolates this case's dependencies so a future
> GenX upgrade in another project doesn't change the solver under you.

---

## 3. Run the case (synthetic data, out of the box)

```bash
julia --project=. Run.jl
```

What happens:

1. GenX reads `settings/genx_settings.yml` and instantiates HiGHS.
2. Inputs are loaded from `system/`, `resources/`, `policies/`.
3. The capacity-expansion + dispatch LP/MILP is built and solved.
4. Results land in `results/` (created on first run).

**Expected runtime** with default settings (8760 h, UCommit=2 linearized
clustering, HiGHS IPM + crossover):

| Setting                       | Solve time         | What you get                      |
|-------------------------------|--------------------|------------------------------------|
| `TimeDomainReduction: 0` (default) | ~3–10 min on M-series Mac | Full 8760-h dispatch              |
| `TimeDomainReduction: 1`           | ~20–60 s           | 8–11 representative weeks         |
| `UCommit: 0` (no unit commit)       | ~30 s              | Pure LP, less realistic dispatch  |

For first-time exploration, **turn TDR on**: edit
`settings/genx_settings.yml` and set `TimeDomainReduction: 1`.

---

## 4. Read the results

GenX writes ~30 CSVs into `results/`. The ones you most likely want:

| File                            | What it answers                                       |
|---------------------------------|-------------------------------------------------------|
| `capacity.csv`                  | Installed MW per resource after expansion             |
| `costs.csv`                     | Total system cost, broken down by category            |
| `power.csv`                     | Hourly generation per resource (8760 rows)            |
| `emissions.csv`                 | Hourly CO2 per zone (zero unless you enable CO2 cap)  |
| `nse.csv`                       | Non-served energy / load shedding                     |
| `flow.csv`                      | Hourly transmission flow on each snitt                |
| `prices.csv`                    | Marginal zonal prices (shadow prices on demand)       |
| `status.csv`                    | Solver status — first thing to check                  |

Quick look in Julia:
```julia
using CSV, DataFrames
df = CSV.read("results/capacity.csv", DataFrame)
show(df, allrows=true)
```

Or from the shell:
```bash
head results/status.csv
awk -F, 'NR==1 || /SE3|SE4/' results/capacity.csv | column -t -s,
```

---

## 5. Common things to change

Edit `settings/genx_settings.yml`:

| Switch                  | Default | Effect when changed                        |
|-------------------------|---------|--------------------------------------------|
| `TimeDomainReduction`   | 0       | `1` → cluster 8760 h into rep. weeks (fast) |
| `UCommit`               | 2       | `0` = LP, `1` = MILP integer (slow), `2` = linearized (fast & realistic) |
| `CO2Cap`                | 0       | `1` or `2` activates `policies/CO2_cap.csv` |
| `MinCapReq`             | 0       | `1` enforces `policies/Minimum_capacity_requirement.csv` |
| `NetworkExpansion`      | 0       | `1` lets snitt 1/2/4 expand (uses reinforcement-cost columns) |
| `ParameterScale`        | 1       | `0` returns prices in $/MWh instead of $/GWh — leave on |

Edit `resources/*.csv` to:
* **Force a phase-out** (e.g., nuclear): set `Can_Retire: 1` and add a
  separate constraint, or simply set `Max_Cap_MW: 0` to force retirement.
* **Open new-build** (e.g., new nuclear): set `New_Build: 1`, give an
  `Inv_Cost_per_MWyr`, and a positive `Max_Cap_MW`.
* **Block a technology**: set `Existing_Cap_MW: 0` and `Max_Cap_MW: 0`.

---

## 6. Replace synthetic data with real ENTSO-E

```bash
# one-time
python3 -m venv .venv && source .venv/bin/activate
pip install entsoe-py pandas python-dotenv pyarrow

# get a free API token from
#   https://transparency.entsoe.eu/usrm/user/myAccountSettings
# (request the "Restful API" role — manual approval, ~1 day)
echo "ENTSOE_API_TOKEN=your-token-here" > data/.env

# pull one year of SE1-SE4 demand + generation
python3 data/fetch_entsoe.py --start 2024-01-01 --end 2025-01-01
```

This overwrites `system/Demand_data.csv` and
`system/Generators_variability.csv` with hourly observations, caching raw
downloads in `data/raw/`. Re-running the same date range is fast (reads
the parquet cache).

Then re-run:
```bash
julia --project=. Run.jl
```

To go back to synthetic profiles:
```bash
python3 build_timeseries.py
```

---

## 7. Troubleshooting

**`ERROR: ArgumentError: Package GenX not found`**
You didn't activate the project. Use `julia --project=.` (with the dot)
or in the REPL: `julia> ]activate .` then `using GenX`.

**`Infeasible`** in `results/status.csv`
* Most common cause: `MinCapReq` requires more wind/solar than `Max_Cap_MW`
  allows. Either raise the caps in `resources/Vre.csv` or lower the
  `Min_MW` in `policies/Minimum_capacity_requirement.csv`.
* Second most common: demand exceeds the sum of `Existing_Cap_MW` and you
  haven't set `New_Build: 1` on enough resources, and curtailment cost
  (Voll=50000) is making the model prefer infeasibility's barrier.

**Solve hangs at HiGHS IPM**
Switch to simplex: in `settings/highs_settings.yml` set `Method: simplex`.

**`UndefVarError: pyarrow`** in `fetch_entsoe.py`
`pip install pyarrow` — parquet caching needs it.

**ENTSO-E `NoMatchingDataError`** for early dates
SE4 generation per PSR type only became reliable around 2017. Use 2018+
for clean data. For older studies, fall back to total generation only.

**Results look weird (e.g., zero hydro output)**
Check `system/Generators_variability.csv`: the columns
`SE{1,2,3,4}_hydro_reservoir` are **inflow as a fraction of capacity**, not
zero. If `fetch_entsoe.py` ran but couldn't find hydro PSR data for a
zone, it will skip the column — re-run `python3 build_timeseries.py` and
then re-merge only the columns you trust.

---

## 8. What "done" looks like for a Sweden study

A sensible smoke-test acceptance:

* `status.csv` reports `Optimal`
* `capacity.csv` keeps all 6900 MW of existing nuclear (it's cheap)
* `flow.csv` shows mostly north-to-south flow on snitt 2 and snitt 4
  (matches reality: hydro/wind north, demand south)
* `prices.csv` shows SE3 and SE4 prices higher than SE1/SE2 by 5–30 $/MWh
  during winter peak hours (also matches reality)
* Annual hydro output sums to roughly 60–75 TWh across the four zones

If those four hold, you have a credible base case. From there, scenarios
(nuclear retirement, offshore-wind buildout, EU CO2 cap tightening,
electrification of steel in SE1) are just edits to `resources/` and
`policies/` and re-runs.

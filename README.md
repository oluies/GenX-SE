# GenX-SE: Sweden 4-zone (SE1–SE4) energy-system case

[![CI](https://github.com/oluies/GenX-SE/actions/workflows/ci.yml/badge.svg)](https://github.com/oluies/GenX-SE/actions/workflows/ci.yml)
[![Format Check](https://github.com/oluies/GenX-SE/actions/workflows/format-check.yml/badge.svg)](https://github.com/oluies/GenX-SE/actions/workflows/format-check.yml)
[![Validate Data](https://github.com/oluies/GenX-SE/actions/workflows/validate-data.yml/badge.svg)](https://github.com/oluies/GenX-SE/actions/workflows/validate-data.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A [GenX](https://github.com/GenXProject/GenX) capacity-expansion + dispatch
case for the four Swedish electricity bidding zones (Norrbotten,
Mid-Norrland, Mälardalen/Stockholm, Skåne/South), modelled with the three
north–south transfer cuts **snitt 1, snitt 2, snitt 4**.

> **Status:** runnable scaffold with synthetic 8760-hour profiles calibrated
> to plausible Swedish totals (≈145 TWh, peak ≈28 GW). Resource capacities
> reflect roughly 2024-actual fleet sizes. **All time-series data is
> synthetic** — replace with ENTSO-E observations via `data/fetch_entsoe.py`
> before reporting results.

## Topology

| Zone | Region                     | Avg demand | Peak demand |
|------|----------------------------|-----------:|------------:|
| SE1  | Norrbotten (Luleå)         |   2.0 GW   |    3.2 GW   |
| SE2  | Mid-Norrland (Sundsvall)   |   2.5 GW   |    4.0 GW   |
| SE3  | Mälardalen / Stockholm     |   8.5 GW   |   14.0 GW   |
| SE4  | Skåne / South (Malmö)      |   3.0 GW   |    4.8 GW   |

Cross-zone transfer capacities (single-direction NTC, MW):

* **Snitt 1** SE1 ↔ SE2: 3300
* **Snitt 2** SE2 ↔ SE3: 7300
* **Snitt 4** SE3 ↔ SE4: 5400

> These values are **NTC made available to the market** (post-*minRAM*),
> not raw thermal line capacity. Under **EU Regulation 2019/943
> Article 16(8)**, TSOs must make at least 70% of the operationally
> secure cross-zonal capacity available for cross-zonal trade — internal
> grid congestion is not a valid reason to reduce it below that floor.
> The rule (often called *minRAM*, Minimum Remaining Available Margin)
> has been **binding since 31 December 2025**. Svenska Kraftnät has had
> documented compliance shortfalls during high-demand periods, especially
> on snitt 4 (SE3↔SE4) — N-1 contingencies in the SE3 grid drove the 2011
> zonal split and remain the binding constraint. Energimarknadsinspektionen
> (Ei) is currently reviewing SvK's compliance after ACER flagged the
> issue. To model *non-compliant* operating modes or alternative
> trajectories, multiply these values by your assumed fraction
> (0.50 / 0.70 / 1.00) and re-run.

## Generation fleet (existing capacities, MW)

| Resource              | SE1  | SE2  | SE3  | SE4  | Notes                          |
|-----------------------|-----:|-----:|-----:|-----:|--------------------------------|
| Hydro reservoir       | 5300 | 8200 | 2700 |  300 | Energy-to-power ratio 100–2500 h |
| Nuclear               |    – |    – | 6900 |    – | Forsmark + Ringhals + Oskarshamn |
| Biomass CHP           |  200 |  400 | 2000 |  800 | New build enabled              |
| Oil peaker (Karlshamn)|    – |    – |    – | 1700 | Reserve only                   |
| Onshore wind          | 2400 | 5400 | 4500 | 1700 | New build enabled              |
| Offshore wind         |    – |    – |    – |  200 | Lillgrund + expansion          |
| Solar PV              |    – |    – | 1800 |  600 | New build enabled              |
| Battery storage       |    0 |    0 |    0 |    0 | New build only                 |

Nuclear and oil are configured as **no-new-build, can-retire** so the model
chooses whether to keep them economical. All renewables, batteries, and
biomass CHP can expand. Hydro reservoirs are existing-only (limited
expansion potential in Sweden).

## How to run

```bash
make install      # Julia + GenX + Python (uv) — first time only
make run-fast     # solve with TimeDomainReduction=1 (≈30s with HiGHS)
make plot         # PNG + interactive HTML in plots/output/
# or just:
make all
```

Detailed runbook: [HOW_TO_RUN.md](HOW_TO_RUN.md).

### 1-hour vs 15-minute resolution

The Nordic synchronous area moved to a **15-min Imbalance Settlement
Period** in 2023–2024, and the day-ahead market (Nord Pool / SDAC) went
15-min in **October 2025**. The case ships at **1-hour** by default (8760
steps); switch to 15-min with:

```bash
make to-15min     # regenerate timeseries + rescale resource CSVs (8760 -> 35040)
make run          # full-resolution solve
make to-1h        # revert
```

`scripts/rescale_resources.py` is what makes this safe: it multiplies
`Up_Time` / `Down_Time` / `Min_Duration` / `Max_Duration` by 4 and
divides `Ramp_Up_Percentage` / `Ramp_Dn_Percentage` by 4 so the physical
behaviour stays the same (e.g. a 6-hour minimum-up time stays 6 hours,
not 1.5 hours). The round-trip is exact, so flipping back and forth is
lossless.

15-min matters most for **summer pricing**: solar dawn/dusk ramps, battery
intra-hour arbitrage, and wind cloud-front variability that hourly averaging
hides. Winter is dominated by thermal+hydro and an hourly model captures it
fine — so for capacity-expansion studies of the 2035 decarbonisation
question, 1-hour is usually enough.

#### Observed sensitivity on this case (synthetic data, TDR=1)

| Metric                  | 1-h         | 15-min       | Δ           |
|-------------------------|------------:|-------------:|------------:|
| Solve time (HiGHS-IPM)  | 68 s        | 98 s         | +44%        |
| Total cost (objective)  | $3.427 B/yr | $3.429 B/yr  | +0.05%      |
| Capacity-expansion mix  | +5.4 GW wind in SE1, +2.1 GW in SE2 | identical | — |
| Annual energy total     | 144 TWh     | 144 TWh      | 0           |
| **Peak marginal price** | **~$330/MWh** | **~$670/MWh** | **+103%** |

**Takeaway:** Capacity and energy answers are essentially invariant to
resolution — what you'd build to decarbonise Sweden doesn't change. But
prices do: 15-min reveals brief scarcity peaks that 1-h smooths away, and
those peaks are where battery and demand-response revenue lives. If the
research question is "what should we build", run 1-h. If it's "how much do
batteries earn" or "is SE4 price-volatile enough to justify reinforcement",
run 15-min.

## Replacing the synthetic data with real observations

1. Get an ENTSO-E API token (free, see `data/README.md`).
2. `pip install entsoe-py pandas python-dotenv pyarrow`
3. `echo "ENTSOE_API_TOKEN=..." > data/.env`
4. `python3 data/fetch_entsoe.py --start 2024-01-01 --end 2025-01-01`

This overwrites `system/Demand_data.csv` and
`system/Generators_variability.csv` with hourly observations. Keep an eye
on the printed warnings — some PSR types are sparse or missing in early
data years and need backfilling.

## Files

```
sweden_4_zones/
├── Run.jl                                  # entry point
├── build_timeseries.py                     # regenerates synthetic CSVs
├── settings/
│   ├── genx_settings.yml                   # solver + policy switches
│   ├── highs_settings.yml
│   └── time_domain_reduction_settings.yml
├── policies/
│   ├── CO2_cap.csv                         # set CO2Cap>0 to activate
│   └── Minimum_capacity_requirement.csv    # set MinCapReq>0 to activate
├── resources/
│   ├── Thermal.csv     (nuclear, oil, biomass)
│   ├── Vre.csv         (wind on/offshore, solar)
│   ├── Storage.csv     (Li-ion batteries)
│   ├── Hydro.csv       (reservoir hydro)
│   └── policy_assignments/
│       └── Resource_minimum_capacity_requirement.csv
├── system/
│   ├── Network.csv
│   ├── Demand_data.csv               (synthetic)
│   ├── Generators_variability.csv    (synthetic)
│   └── Fuels_data.csv                (synthetic prices + CO2 factors)
└── data/
    ├── README.md           # data-source documentation
    ├── fetch_entsoe.py     # downloader for real data
    └── .gitignore
```

## Known simplifications

* **No district-heating coupling.** Biomass CHP is modelled as electricity-
  only; real Swedish CHP follows heat demand, which affects when it runs.
* **No cross-border to NO/FI/DK/DE.** Sweden imports/exports heavily,
  especially SE3↔FI and SE4↔DE. To extend, add neighbor zones with their
  own demand + generation and connect via `Network.csv`. When you do this,
  respect the **Nordic synchronous area boundary** — it matters for any
  future reserve-sharing or `CapacityReserveMargin` modeling:

  | Neighbor | Coupling to SE | Synchronous area      | Links                                |
  |----------|----------------|------------------------|--------------------------------------|
  | NO       | AC             | Nordic                 | Multiple AC lines from SE2/SE3       |
  | FI       | AC + HVDC      | Nordic                 | AC tie SE1↔FI; Fenno-Skan HVDC SE3↔FI |
  | DK2      | AC             | Nordic                 | Öresund link, SE4↔DK2                |
  | DK1      | HVDC           | Continental Europe     | Konti-Skan, SE3↔DK1                  |
  | DE       | HVDC           | Continental Europe     | Baltic Cable + Hansa PowerBridge, SE4↔DE |
  | PL       | HVDC           | Continental Europe     | SwePol, SE4↔PL                       |
  | LT       | HVDC           | Baltic                 | NordBalt, SE4↔LT                     |

  For a GenX transport model the AC/HVDC distinction is cosmetic at the
  energy-balance level (everything is an NTC line), but **reserves only
  flow within a synchronous area** — DE/DK1/PL/LT cannot back up Swedish
  FCR/aFRR/mFRR. Tag the lines explicitly if you later add reserve
  constraints or operating-reserve-sharing logic.
* **Hydro reservoirs aggregated per bidding zone.** A real Swedish hydro
  model has hundreds of reservoirs with hydraulic coupling (cascades) and
  spillage; here each zone is one bucket.
* **No must-run constraints** on CHP for heat. Add via the GenX `MustRun`
  resource type if needed.
* **CO2 cap and minimum-capacity policies are off by default.** Toggle in
  `settings/genx_settings.yml` to activate the CSVs in `policies/`.

## Calibration targets (for your future runs)

Match annually against published Energimyndigheten / SCB / Svenska
Kraftnät figures, roughly (2023 actuals):

* Total generation ≈ 162 TWh (hydro 70, nuclear 46, wind 34, CHP 9, solar 2)
* Total demand   ≈ 140 TWh (after net exports ~22 TWh)
* Average SE3 day-ahead price ≈ 50–80 €/MWh
* SE4 price premium over SE3 ≈ 10–30 €/MWh (transmission-constrained)

If your dispatch matches the first two and produces a non-zero SE3↔SE4
price spread, you're in the right ballpark.

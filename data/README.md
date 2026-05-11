# Real data for the Sweden 4-zone GenX example

The model ships with **synthetic** 8760-hour profiles so it runs out of the
box. To replace them with observations, use the sources below.

## ENTSO-E Transparency Platform (recommended)

Covers the full European grid including SE1–SE4 separately.

| Field                    | ENTSO-E document         | Used for                          |
|--------------------------|--------------------------|-----------------------------------|
| Total Load Day-ahead     | A65 / 6.1.B              | `Demand_data.csv`                 |
| Generation per PSR type  | A75 / 16.1.B&C           | `Generators_variability.csv`      |
| Installed Capacity       | A68 / 14.1.A             | Sanity check on `Existing_Cap_MW` |
| Cross-border physical    | A11 / 12.1.G             | Snitt 1 / 2 / 4 flow validation   |
| Day-ahead prices         | A44 / 12.1.D             | (Optional) Bidding-zone prices    |

Run `data/fetch_entsoe.py --start 2024-01-01 --end 2025-01-01` after dropping
your API token in `data/.env`:

```
ENTSOE_API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Svenska Kraftnät (Swedish TSO)

The TSO's [Mimer / Driftdata portal](https://mimer.svk.se/) and
[Kontrollrummet API](https://www.svk.se/om-kraftsystemet/kontrollrummet/)
publish:

* hourly demand per SE-zone (same series ENTSO-E redistributes)
* reservoir energy content (week-resolution, very useful for hydro)
* snitt limits per hour (operational transfer capacity, not just NTC)
* frequency reserve activations (mFRR/aFRR)

The reservoir content series is what you'd use to validate the hydro
energy-to-power ratio in `resources/Hydro.csv`.

## SMHI (weather)

[SMHI Open Data API](https://opendata.smhi.se/) has hourly wind speed,
irradiance, and temperature per station. Combine with turbine power curves
and the [pvlib](https://pvlib-python.readthedocs.io/) library to build
synthetic capacity-factor series tied to specific weather years.

## Fingrid (only Finland, but useful)

[Fingrid Open Data](https://data.fingrid.fi/) is the cleanest open API in
the Nordics — useful if you extend the model to include FI as a 5th zone
(SE3↔FI transfer matters for SE3 prices). Their API is much friendlier than
ENTSO-E's: REST/JSON, no token forms.

## Nord Pool (prices)

Day-ahead clearing prices per SE-zone are at
[nordpoolgroup.com/Market-data1](https://www.nordpoolgroup.com/Market-data1/Dayahead/Area-Prices/SE/Hourly/).
Useful for comparing modelled marginal prices against observed prices.

## Renewables.ninja

[renewables.ninja](https://www.renewables.ninja/) provides per-location
hourly wind & solar CFs derived from MERRA-2 reanalysis. Reliable for
counterfactual weather years and free for academic use (5,000 calls/day).

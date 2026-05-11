# GenX-SE: Sweden 4-zone energy-system case
# ─────────────────────────────────────────────────────────────────────────
# Common entry points for local development and CI.
#
#   make install      Install Julia (GenX) + Python (uv) deps
#   make run          Run the case end-to-end → results/
#   make run-fast     Run with TimeDomainReduction=1 (rep weeks, ~30s)
#   make plot         Generate PNGs + interactive HTML from results/
#   make all          install + run-fast + plot
#   make timeseries   Regenerate synthetic 8760h CSVs from build_timeseries.py
#   make fmt          Run JuliaFormatter (SciML style) — writes changes
#   make fmt-check    Same as fmt but fails on diffs (CI mode)
#   make validate     Sanity-check CSV structure (mirrors validate-data CI)
#   make clean        Remove results/ and plot output
#   make distclean    clean + remove Manifest.toml + .venv
# ─────────────────────────────────────────────────────────────────────────

# Configuration ------------------------------------------------------------
JULIA       ?= julia
UV          ?= uv
PYTHON      ?= $(UV) run python
RESULTS_DIR ?= results
PLOTS_DIR   ?= plots/output
SETTINGS    := settings/genx_settings.yml

.DEFAULT_GOAL := help
.PHONY: help install install-julia install-python run run-fast plot timeseries \
        fmt fmt-check validate clean distclean all ci-smoke

help:
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} \
	      /^[a-zA-Z_-]+:.*?##/ {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' \
	      $(MAKEFILE_LIST)

# Installation ------------------------------------------------------------
install: install-julia install-python  ## Install Julia + Python deps

install-julia:  ## Install GenX into the local Julia project
	$(JULIA) --project=. -e 'using Pkg; Pkg.add("GenX"); Pkg.instantiate()'

install-python:  ## Sync Python deps via uv
	$(UV) sync

# Run the model -----------------------------------------------------------
run:  ## Run case (current settings, may be slow at full 8760h)
	$(JULIA) --project=. --color=yes Run.jl

run-fast:  ## Run case with TimeDomainReduction=1 (fast smoke test)
	@cp $(SETTINGS) $(SETTINGS).bak
	@sed -i.tmp 's/^TimeDomainReduction:.*/TimeDomainReduction: 1/' $(SETTINGS)
	@rm -f $(SETTINGS).tmp
	@$(JULIA) --project=. --color=yes Run.jl; status=$$?; \
	  mv $(SETTINGS).bak $(SETTINGS); exit $$status

# Plots -------------------------------------------------------------------
plot:  ## Render PNG + HTML plots from results/
	$(PYTHON) -m plots.make_plots --results $(RESULTS_DIR) --out $(PLOTS_DIR)

# Time-series generation --------------------------------------------------
timeseries:  ## Regenerate synthetic 8760h CSVs
	$(PYTHON) build_timeseries.py

# Formatting --------------------------------------------------------------
fmt:  ## Apply JuliaFormatter (SciML style)
	$(JULIA) -e 'using Pkg; Pkg.add(PackageSpec(name="JuliaFormatter", version="1"))' >/dev/null
	$(JULIA) -e 'using JuliaFormatter; format(".")'

fmt-check:  ## JuliaFormatter check (fail on diff)
	$(JULIA) -e 'using Pkg; Pkg.add(PackageSpec(name="JuliaFormatter", version="1"))' >/dev/null
	$(JULIA) -e 'using JuliaFormatter; \
	             ok = format(".", overwrite=false); \
	             ok ? exit(0) : (println("Formatting differs"); exit(1))'

# Validation --------------------------------------------------------------
validate:  ## Run CSV structure checks
	$(PYTHON) scripts/validate_data.py

# Combined ---------------------------------------------------------------
all: install run-fast plot  ## install + run-fast + plot

ci-smoke: install run-fast plot validate  ## Full CI flow

# Cleanup ----------------------------------------------------------------
clean:  ## Remove results/ and plot output
	rm -rf $(RESULTS_DIR) $(PLOTS_DIR) TDR_results

distclean: clean  ## Also remove Manifest.toml and .venv
	rm -f Manifest.toml
	rm -rf .venv

# Home EMS Optimizer

<details>
<summary>Home Battery</summary>

This section contains the details of the home battery asset.

- Capacity: 10 kWh
- Max charge power: 5 kW
- Max discharge power: 5 kW

</details>

A Streamlit app implementing the layered EMS architecture: an asset
abstraction layer (Source/Storage/Load), a MILP optimizer core (PuLP + CBC),
a Plotly visualization layer, and an optional side-by-side comparison
against the external [EVCC optimizer](https://github.com/evcc-io/optimizer)
service.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (usually `http://localhost:8501`).

## Files

| File | Layer | Purpose |
|---|---|---|
| `assets.py` | Abstraction | `Asset` base class + `Source`, `Storage`, `Load` |
| `simulator.py` | — | Simulated Grid price / PV production / Load demand forecasts (kept modular so it can later be swapped for real data, e.g. Home Assistant) |
| `optimizer.py` | Optimizer core | MILP formulation, solved via PuLP/CBC |
| `evcc_client.py` | — | HTTP client for the external EVCC optimizer service |
| `visualization.py` | Visualization | Plotly chart builders |
| `app.py` | UI | Streamlit app: sidebar config + Inputs/Optimization tabs |

## Scope of this first version

Per the architecture doc's "start with Grid, PV, Battery and Home Load,"
this implementation covers exactly those four assets. EV Battery, DHW Tank
and Building Thermal Mass are **not** wired in yet, but `assets.py`'s
`Storage`/`Load` classes are already generic enough to add them without
touching the optimizer's structure — each new asset just needs its own
constraint set folded into the energy balance and objective in
`optimizer.py`, plus a section in the Inputs tab.

Controllable Loads (ON/OFF, ties into MILP binaries) are likewise scaffolded
in `assets.Load` (`controllable`/`max_power`/`set_on_off`) but not yet
surfaced in the UI or the optimizer's constraints.

## Design choices worth knowing about

- **Soft constraints** are applied to the battery's SoC bounds only (large
  per-unit penalty via slack variables), since that's the natural place for
  "gracefully handle a bad forecast" to show up. Grid import/export limits
  are kept as hard bounds (physical breaker limits). If you want other
  constraints to be soft too, mirror the `soc_low_slack`/`soc_high_slack`
  pattern in `optimizer.py`.
- **Tie-breaking strategies** (peak leveling, charging priority) are added
  to the objective with a tiny weight (`1e-6`) relative to the real cost/
  self-consumption term, so they only break ties between otherwise
  equal-cost solutions rather than compromising the primary objective.
- **`solver_tolerance`** maps to CBC's relative MIP gap (`gapRel`), a
  standard, well-supported PuLP option. **`max_iterations`** is passed
  through as a best-effort CBC option; if your CBC build doesn't accept it,
  the app automatically retries without it (see the `try/except` in
  `Optimizer.solve`).
- **EVCC integration** (`evcc_client.py`) is a best-effort mapping to the
  service's public request/response schema (units: W/Wh/seconds internally,
  converted from this app's kW/kWh/hours). The service is explicitly
  experimental/evolving upstream, so treat this as a starting point — if
  the schema has moved on, adjust `build_payload()`/the response parsing in
  `run_evcc_optimization()`. The app never crashes if the service is
  unreachable; it shows "comparison unavailable" with the error instead.
- **At t=0**, the app uses each asset's *measured* current value (from the
  "Current state" inputs) rather than the simulated forecast, per the
  architecture doc's design note; forecasts drive t>0 only.

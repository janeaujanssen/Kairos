# UI Architecture for Kairos
## Easy, optimized energy scheduling for Home Assistant

**Status:** Draft
## Overview
Streamlit interface for viewing the results of the Kairos energy optimization and also for running optimization scenarios on non-real data.

## Sidebar

**▶ Run optimization button**: Primary action at top for immediate visibility

**Sign Convention Reference** (expandable):
- **Grid Power**: +import, −export
- **PV Power**: +production
- **Battery Power**: +charge, −discharge
- **DHW Battery Power**: +charge, −discharge
- **Building Battery Power**: +charge, −discharge
- **Load Power**: +consumption
- Energy balance: Grid + PV = Load + Storage at every timestep

**Asset Enablement Toggles**:
If assets are added, they will appear in the sidebar list with their respective enablement toggles and icons.
When disabled, the asset will not be considered in the optimization and will also be hidden from the inputs interface.
- ⚡ Grid
- 🔆 PV
- 🔋 Battery 
- 💧 DHW Tank
- 🏢 Building Thermal Mass 
- 🚗 EV Battery 

**Configuration Variables**:
- **Planning Horizon** (hours): 6–48, default 24
- **Time Interval** (minutes): 15, 30, 60; default 15

## Inputs Tab (📥)

**Add new assets**: + button at top to add a new asset
No assets added by default.

### Asset Structure (Each Expandable, by default collapsed)

Two columns layout: Left for physical inputs according to asset type (see `backend_architecture.md` for defaults), right for showing converted generic inputs

Below the two columns: Forecast visualization (time-series charts) spanning the full width of the interface (equal to the combined width of the two columns).
Below the charts: Inputs where the forecast charts are based on (as described below), allowing users to modify the underlying parameters and immediately see the impact on the forecasts.

**Forecast** *(time-series parameters + chart)*:
- **Grid**:
  - `import_price_forecast` and `export_price_forecast` not shown under physical inputs, but are shown in the converted generic inputs section
  - **Import/export price forecast** chart visualized based on:
    - Baseline price
    - Morning peak time
    - Evening peak time
    - Morning peak price
    - Evening peak price
    - Export price as fraction of import price
- **PV**:
  - `power_forecast` not shown under physical inputs, but is shown in the converted generic inputs section
  - **PV power forecast** chart visualized based on:
    - Peak power, resulting in bell curve that peaks at solar noon (midday) and is zero at night
- **Base load**:
  - `power_forecast` not shown under physical inputs, but is shown in the converted generic inputs section
  - **Base load power forecast** chart visualized based on:
    - Baseline consumption
    - Morning peak time
    - Evening peak time
    - Morning peak power
    - Evening peak power
- **Controllable load**: no forecast
- **Home battery**: no forecast
- **EV battery**:
  - `vehicle_efficiency`, `round_trip_distance`, `expected_departure_time`, `expected_arrival_time` not shown under physical inputs, but are shown in the converted generic inputs section
  - **EV energy demandforecast** chart visualized based on:
    - Vehicle efficiency
    - Round trip distance
    - Expected departure time
    - Expected arrival time
- **DHW tank**:
  - `morning_peak_energy_demand`, `evening_peak_energy_demand`, `morning_peak_time`, `evening_peak_time` not shown under physical inputs, but are shown in the converted generic inputs section
  - **DHW energy demand forecast** chart visualized based on:
    - Morning peak energy demand
    - Evening peak energy demand
    - Morning peak time
    - Evening peak time
- **Building thermal mass**: no forecast

## Optimization Tab (📊)

Shows info banner if no result yet.

### Solver Info

**Metrics row**:
- Type, Status, Solve time

### Charts

**Power Flow** — Hybrid chart showing energy balance:
- Supply side (lines): Net Grid Power (+import, −export) and PV Production
- Demand side (stacked bars, barmode="relative"):
  - Home Load (blue)
  - Storage Power per asset (distinct colors, +charge/−discharge)
- Secondary y-axis: Import/Export prices (dashed)

**Cost Analysis** — Dual-axis hybrid chart:
- Bars (stacked): Grid energy cost (red=cost, green=profit)
- Line (secondary y-axis): Cumulative cost

**State of Charge Trajectories** — Multi-asset SoC evolution:
- One line per storage asset (colors: purple, orange, green, red, blue)
- Min/max SoC bounds as horizontal dotted lines (color-coded, labeled on right)
- Hover shows asset name, SoC %, energy (kWh)

## Visualization Details

**Global chart properties**:
- Height: 280–400px
- Width: Responsive ('stretch')
- Legend: Horizontal, top-right
- Hover: x-unified (all traces at a time)
- Colors: Red = grid import/cost, Green = export/profit, Orange = PV, Blue = load/cumulative, Purple = battery, Light Blue = DHW

**Forecast charts** (Inputs):
- Import/export price forecast: lines (import red, export green dashed)
- PV power forecast: filled area (orange)
- Base load power forecast: filled area (blue)
- EV energy demand forecast: bars (energy per timestep, purple)
- DHW energy demand forecast: bars (energy per timestep, light blue)

**Result charts** (Optimization):
- Power flow: energy balance visualization with stacking
- Cost analysis: per-interval + cumulative with dual y-axes
- SoC trajectories: multi-line with min/max bounds
# UI Architecture for Kairos
## Easy, optimized energy scheduling for Home Assistant

> **Status:** Draft
## Overview
Streamlit interface for viewing the results of the Kairos energy optimization and also for running optimization scenarios on non-real data.
The interface consists of two parts: an inputs interface where a user can generate a simulation scenario which then can be send to the api, and an optimization results interface where the outcomes of the optimization are displayed. When the optimization has finished a run (also when called externally from the streamlit ui), the results should be shared with the streamlit app for visualization.

## Sidebar

**Title**: Kairos - Easy, optimized energy scheduling for Home Assistant

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
- 🏠 Base Load
- 🔌 Controllable Load
- 🔋 Battery 
- 💧 DHW Tank
- 🏢 Building Thermal Mass 
- 🚗 EV Battery 

**Configuration Variables**:
- **Planning Horizon** (hours): 6–48, default 24
- **Time Interval** (minutes): 15, 30, 60; default 15
- **Start time** [hh:mm]: default 00:00

## Inputs Tab (📥)

**Add new assets**: Dedicated + buttons per asset type in row at top to add new assets, for grid and base load only 1 instance is allowed and the button will be disabled once an instance is added.
No assets added by default.

### Asset Structure (Each Expandable, by default collapsed)
A repeating structure for each asset, to minimize code repetition.

Three columns layout: Left for physical inputs according to asset type (see `backend_architecture.md` for defaults), middle for showing converted generic inputs in json format, exactly as they will be sent to the optimizer, but everything collapsed except for the top level keys, and right for forecast inputs (if applicable) where the forecast charts are based on (as described below), allowing users to modify the underlying parameters and immediately see the impact on the forecasts.

The Physical inputs should have the same units as requested by the API, with the exception of:
- **Energy prices**: [price/kWh]
- **Vehicle efficiency**: [km/kWh]

Below the three columns: Forecast visualization (time-series charts) spanning the full width of the interface (equal to the combined width of the three columns).

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

## Optimization Results Tab (📊)

Shows info banner if no result yet.
Shows "Optimizing..." banner while the optimization is in progress.

### Solver Info

**Metrics row**:
- Status, Solve time, Objective cost

### Charts
**Power Flow** — Hybrid chart showing power balance:
- Supply side (lines): 
  - Net Grid Power
  - PV Production
- Demand side (stacked bars, barmode="relative"):
  - Home Load
  - Controllable Load
  - Storage Power per asset
- Secondary y-axis: Import/Export prices [price/kWh] (dashed)

**Cost Analysis** — Dual-axis hybrid chart:
- Bars (stacked): Grid energy cost (distinct colors for cost and profit)
- Line (secondary y-axis): Cumulative cost

**State of Charge Trajectories** — Multi-asset SoC evolution:
- One line per storage asset (same color as defined in the power chart)
- Min/max SoC bounds as horizontal dotted lines (same color as defined in the power chart, labeled on right)
- Hover shows asset name, SoC %, energy (kWh)

## Visualization Details

**Chart color scheme**:
Assets cycle through colors when more assets are added beyond the first ones:
- ⚡ Grid: #B03827, #E96651, #FDBAAD
- 🔆 PV: #97540C, #D8790F, #FEBD8A
- 🏠 Base Load: #1B7576, #45A6A6, #A7D7D7
- 🔌 Controllable Load: #5f5ea2, #8987ea, #c5c7ff
- 🔋 Battery: #107959, #15AE81, #81E4BC
- 💧 DHW Tank: #064F71, #00A0E1, #94D6FF
- 🏢 Building Thermal Mass: #4F6B7E, #7E99AB, #BECFDB
- 🚗 EV Battery: #7e5391, #b577d2, #e2bcf5

For costs:
- Grid energy cost: cost = #E96651, profit = #15AE81
- Cumulative cost: #00A0E1

**Global chart properties**:
- Height: 280–400px
- Width: Responsive ('stretch')
- Legend: Horizontal, top-right
- Hover: x-unified (all traces at a time), including units

**Forecast charts** (Inputs):
- Import/export price forecast: lines (import red dashed, export green dashed)
- PV power forecast: filled area
- Base load power forecast: filled area
- EV energy demand forecast: bars (energy per timestep)
- DHW energy demand forecast: bars (energy per timestep)
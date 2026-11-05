# UI Architecture for Kairos
## Easy, optimized energy scheduling for Home Assistant

> **Status:** Final.
> 
> **To Do:**
> - None

## Overview
Streamlit interface for viewing the results of the Kairos energy optimization and also for running optimization scenarios on non-real data.
The interface consists of two parts: an Simulation inputs interface where a user can generate a simulation scenario which then can be send to the api, and an optimization results interface where the outcomes of the optimization are displayed. When the optimization has finished a run (also when called externally from the streamlit ui), the results should be shared with the streamlit app for visualization.

## Sidebar
**Sign Convention Reference** (expandable):
- **Grid Power**: +import, −export
- **Solar Power**: +production
- **Home Battery and EV Battery Power**: +charge, −discharge
- **DHW Tank Power**: +charge, −discharge
- **Building Thermal Mass Power**: +charge, −discharge
- **Base Load and Controllable Load Power**: +consumption
- Energy balance: Grid + Solar = Base Load + Controllable Load + Storage at every timestep

**Simulation mode**: Toggle to enable or disable simulation mode, which shows the simulation inputs and the run button when enabled, and only displays optimization results when disabled.
**▶ Run simulation optimization**: Button to run the simulation optimization

**Asset Enablement Toggles**:
If assets are added, they will appear in the sidebar list with their respective enablement toggles and icons.
When disabled, the asset will not be considered in the optimization and will also be hidden from the inputs interface.
- ⚡ Grid
- 🔆 Solar
- 🏠 Base Load
- 🔌 Controllable Load
- 🔋 Home Battery 
- 🚗 EV Battery 
- 💧 DHW Tank
- 🏢 Building Thermal Mass 

**Configuration Variables**:
- **Planning Horizon** [h]: 6–48, default 24
- **Schedule Time Step** [min]: 15, 30, 60; default 15
- **Start time** [hh:mm]: default 00:00
- **Solver Time Limit** [s]: 1–3600, default 10
- **Relative MIP Gap**: 0–1, default 0
- **Storage Switching Penalty** [cost per mode change]: default 0.01
- **Grid Peak Penalty** [-]: default 0.1

## Simulation inputs Tab (📥)

**Add new assets**: Dedicated + buttons per asset type in row at top to add new assets, for Grid and Base Load only 1 instance is allowed and the button will be disabled once an instance is added.
No assets added by default.

### Asset Structure (Each Expandable, by default collapsed)
A repeating structure for each asset, to minimize code repetition.
Each asset has a **Name** text field at the top (default: asset type and instance number, e.g. "Solar 2").

Three columns layout: Left for physical inputs according to asset type (see `optimizer_architecture.md` for defaults), middle for showing converted generic inputs in json format, exactly as they will be sent to the optimizer, but everything collapsed except for the top level keys, and right for forecast inputs (if applicable) where the forecast charts are based on (as described below), allowing users to modify the underlying parameters and immediately see the impact on the forecasts.

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
- **Solar**:
  - `power_forecast` not shown under physical inputs, but is shown in the converted generic inputs section
  - **Solar power forecast** chart visualized based on:
    - Peak power, resulting in bell curve that peaks at solar noon (midday) and is zero at night
- **Base Load**:
  - `power_forecast` not shown under physical inputs, but is shown in the converted generic inputs section
  - **Base Load power forecast** chart visualized based on:
    - Baseline consumption
    - Morning peak time
    - Evening peak time
    - Morning peak power
    - Evening peak power
- **Controllable Load**: no forecast
- **Home Battery**: no forecast
- **EV Battery**:
  - `energy_demand_forecast` not shown under physical inputs, but is shown in the converted generic inputs section
  - **EV Battery energy demand forecast** chart visualized based on:
    - Vehicle efficiency
    - Round trip distance
    - Expected departure time
    - Expected arrival time
- **DHW Tank**:
  - `energy_demand_forecast` not shown under physical inputs, but is shown in the converted generic inputs section
  - **DHW Tank energy demand forecast** chart visualized based on:
    - Morning peak energy demand
    - Evening peak energy demand
    - Morning peak time
    - Evening peak time
- **Building Thermal Mass**:
  - `passive_discharge_power` and `cop_forecast` not shown under physical inputs, but are shown in the converted generic inputs section
  - **Outdoor temperature forecast** chart visualized based on:
    - Min outdoor temperature (at midnight)
    - Max outdoor temperature (peak at noon)
  - **Passive discharge power** chart visualized based on:
    - Heat Loss Coefficient [W/°C]
    - Current Indoor Temperature
    - Outdoor temperature forecast
  - **COP forecast** chart visualized based on:
    - Reference COP
    - Reference outdoor temperature
    - COP outdoor temperature coefficient [COP/°C]
    - Outdoor temperature forecast

## Optimization Results Tab (📊)

**Refresh latest result**: button to fetch the most recent optimization result from the API. The latest result is also fetched automatically when no result is loaded yet.

Shows info banner if no result yet.
Shows "Optimizing..." spinner while the optimization is in progress.

### Solver Info

**Metrics row**:
- Status, Solve time, Objective cost

**Captions** (below the metrics row):
- Relative MIP gap target [%]
- Termination reason (when available)

### Charts
**Power Flow** — Hybrid chart showing power balance:
- Supply side (steplines middle aligned `line_shape="hvh"`): 
  - Net Grid Power
  - Solar Production
- Demand side (stacked bars, barmode="relative"):
  - Base Load
  - Controllable Load
  - Storage Power per asset. For Building Thermal Mass this is the full heat pump electrical power in each mode (+dT, neutral and -dT), so the bar is never negative. Each BTM bar is split by mode: charge with `/` stripes, discharge in the solid asset color and neutral with `x` stripes, all on the asset color. The stripes are transparent black (`#000000A3`).
- Secondary y-axis: Import/Export prices [price/kWh] (lines dotted `line_shape="hvh"`)

**Cost Analysis** — Dual-axis hybrid chart:
- Metric above the chart: Grid energy cost over planning horizon
- Bars (stacked): Grid energy cost (distinct colors for cost and profit)
- Line (secondary y-axis): Cumulative cost (steplines `line_shape="hv"`)

**State of Charge Trajectories** — Multi-asset SoC evolution:
- One line per storage asset (same color as defined in the power chart, line `line_shape="linear"`)
- Min/max SoC bounds as horizontal dotted lines (same color as defined in the power chart, labeled on right)
- Hover shows asset name, SoC %, energy (kWh). Also shows temperature for DHW Tank and Building Thermal Mass storage.

## Visualization Details

**Chart color scheme**:
Assets cycle through colors when more assets are added beyond the first ones:
https://huetone.ardov.me/?palette=N4IgdghgtgpiBcICiYYCcDmBPABAEwgGcALAIwHsI08QAaEYgVxkIQG1RJYERy0IwGOPQDG5ADZ9W8NiADEAMxgKAnATryFImHlIqNikXgCsAdn31DpPAGYIBhQoAcCgAzD5OgGynXAFgMRJz8nVwBGAwgnACYRV1cDYOiw1y8DYwUwiFdjAxsbMJtXaJAAXQBfWk5oOEQMfiwNMUk0aVlFL2cFe0sYUhhlCMsTXRgh%2BTigvBLLCDsRUh75J3NXFQUDLxWbJ1zLYz9jFS8LeT8ww%2BMZ%2BSKCmxpLLLDSaNyKqvAangAHRjRv8QeZpSdiaFymRwGZQwESQ4ZGPxKQIiOJw%2BSkGwqWEPeQqUimCAKPbLPx%2BbQbSxeERFWHpaLRCAqJZyGykMIKUzXOTRGl%2BezvarcOpoAZgJoSEEyTyIpSmQIuCC0yxOdZrUh5PAwPxeHFyeIiLxXAzxCBeUnG1zBGwBSzxLbROW2nLhXX%2BVlhYl6vz01zqgWfIUgUjiZjilpteR4PCOJGWWFEhRpWbRGDGZQGUzGEwwJzGrx6dNO459Y1mVyai3GYykETG0k7WtOmzRLxc8Jhan8yqC2pBtDkADuYtEEtaoI6CmibgcXj6MEd0rwak9eFMImrFImDJVm7kiqcQQSlhUqQgWYzh2tuf21IUNiTZ29L090TwYVMFzK3YDve%2BAEswAAazDSV2iURMFHVSwtBzIkHGMIx5wcaJSD8CtelMJxFSgyNTFbfFAk5BkbEiYx4icB85FMGBLS8SiszWPwcJZbJijgf0uF7MRCAAFxAscpUURxOhtTQlBUVMHC0LRrzE0gvEVKSD2ohwTDNZlo2SaIj3Rc5khI5U2WSHS5AUy1LQMPx4luL8Pk4n5%2BwUP8%2BJHcNx0nSCOShVwFD8EtLFIfonFsAwVDQuc8hRGAsQtDEnAM%2BR4hPE4LU5I0nWMeLd3ib0UwtFswn0CpSnoHjyFQCMyI0FIdI9HTtJ0oodKsnSyJ0rx4g0XwdNCHSTwSCogA
- ⚡ Grid (black tints):
  - #000000
  - #000000
  - #000000
- 🔆 Solar (orange tints, 300 / 300 / 300):
  - #ff8f0e
  - #ff8f0e
  - #ff8f0e
- 🏠 Base Load (gray tints, 500 / 300 / 150):
  - #687385
  - #a3acba
  - #d5dbe1
- 🔌 Controllable Load (purple tints, 500 / 300 / 150):
  - #844cef
  - #b39cfd
  - #dcd4fe
- 🔋 Home Battery (green tints, 500 / 300 / 150):
  - #008434
  - #00c652
  - #89f09b
- 💧 DHW Tank (blue tints, 500 / 300 / 150):
  - #0570de
  - #06b9ef
  - #a2e5ef
- 🏢 Building Thermal Mass (brown tints, 500 / 300 / 150):
  - #906a5d
  - #c2a89f
  - #e4d9d5
- 🚗 EV Battery (pink tints, 500 / 300 / 150):
  - #c722a3
  - #e78acb
  - #f5cde7

For costs:
- Grid energy cost: cost = #ff8c7e (300), profit = #3cce9c (300)
- Cumulative cost: #0570de (500)

**Global chart properties**:
- Height: 280–400px
- Width: Responsive ('stretch')
- Legend: Horizontal, top-right
- Hover: x-unified (all traces at a time), indicating time window (e.g. 9:00 - 9:15) and y values including units

**Forecast charts** (Inputs):
- Import/export price forecast: steplines left aligned `line_shape="hv"`
- Solar power forecast: filled area
- Base Load power forecast: filled area
- EV Battery energy demand forecast: bars (energy per timestep)
- DHW Tank energy demand forecast: bars (energy per timestep)
- Building Thermal Mass outdoor temperature forecast: steplines `line_shape="hvh"`
- Building Thermal Mass passive discharge power: bars (power per timestep)
- Building Thermal Mass COP forecast: steplines `line_shape="hvh"`

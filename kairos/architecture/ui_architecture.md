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
- **Solver Time Limit** (seconds): 1–3600, default 10

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
- Supply side (steplines middle aligned `line_shape="hvh"`): 
  - Net Grid Power
  - PV Production
- Demand side (stacked bars, barmode="relative"):
  - Home Load
  - Controllable Load
  - Storage Power per asset
- Secondary y-axis: Import/Export prices [price/kWh] (lines solid `line_shape="spline"`)

**Cost Analysis** — Dual-axis hybrid chart:
- Bars (stacked): Grid energy cost (distinct colors for cost and profit)
- Line (secondary y-axis): Cumulative cost (steplines `line_shape="hv"`)

**State of Charge Trajectories** — Multi-asset SoC evolution:
- One line per storage asset (same color as defined in the power chart, line `line_shape="linear"`)
- Min/max SoC bounds as horizontal dotted lines (same color as defined in the power chart, labeled on right)
- Hover shows asset name, SoC %, energy (kWh)

## Visualization Details

**Chart color scheme**:
Assets cycle through colors when more assets are added beyond the first ones:
https://huetone.ardov.me/?palette=N4IgdghgtgpiBcICiYYCcDmBPABAEwgGcALAIwHsI08QAaEYgVxkIQG1RJYEQ0Yb6AY3IAbcmlbw2IAMQAzBQDY5AFjqyFMAJwwArOvlzBRgBwGFpRREHm5JwQHY49eXl2KVEA3jkAmAIy%2BAAwGpCqB-gDMBiakESEuVkEmyQYqQUGRmSAAugC%2BtJzQcIjiEGAYziDCYhLsGjByWgTmgvykWq1uDp0uRqR4kV59dnJBVTL8ig5Bai6CJiop-gYQJr6CGTEqAUGKBrpy-hBB%2Bi6RkVFBvrkFRdyIGGgQWOo14pLS8somcsOyMFIMEaKxcbjwQNBsk2CzwNxcECGglI-xkJh6QS0cgMinRkRMZ1kuhUui0il6snCJN08NkWUukQEsmO-lIvn0%2BUK4GKPAADow0LyRFV3nUpBpfg4FAZGjBjNiwYI8Co5BNBOqgtKXKRIlpjEyZFpSA4IHJCWiVCo2grZIpBFljAdfL4IFpUZE4nIHLSZL4HZ5blyuCUQKQRMw3qIPvUZHgfJoDPLDvsEb49I0DA5dG4YGYXHsOhn85jFICDKcZngJhldLpSDZ85b8Q3ZBlIr5FD6gv5-PavJz7iGnsCwJHap8ASrVQ5E79rDa0VjMaQDIyYCpFAaMoJFDTy0EIB45q3kipIseZBlcb4Z8XdN2t2e4ubZs6giuB9yHqG0OQAO6jkIUZil8cjKL4YzmKWQK3pOeDNOaeAOIIdYLoILomFiqwLAsCSyFoewQNmmYkueeZEvaciRCmlI7Gy5q%2BHg-gOP4aifsGfIAJZgAA1mO0bivIjTKCufRtL85pmkqMCwfIvhhFWMoOCY1iibISGdsaibei60QIveyQ0TITiGUZ2aYioakyEMGRprcOT0AALuQqATve6j%2BFs9D%2BO59DBHhWR4ekeEGeoiheSAMx4SkeEESE%2BRAA

https://huetone.ardov.me/?palette=N4IgdghgtgpiBcICiYYCcDmBPABAEwgGcALAIwHsI08QAaEYgVxkIQG1RJYERy0IwGOPQDG5ADZ9W8NiADEAMxgKAnATryFImHlIqNikXgCsAdn31DpPAGYIBhQoAcCgAzD5OgGynXAFgMRJz8nVwBGAwgnACYRV1cDYOiw1y8DYwUwiFdjAxsbMJtXaJAAXQBfWk5oOEQMfiwNMUk0aVlFL2cFe0sYUhhlCMsTXRgh%2BTigvBLLCDsRUh75J3NXFQUDLxWbJ1zLYz9jFS8LeT8ww%2BMZ%2BSKCmxpLLLDSaNyKqvAangAHRjRv8QeZpSdiaFymRwGZQwESQ4ZGPxKQIiOJw%2BSkGwqWEPeQqUimCAKPbLPx%2BbQbSxeERFWHpaLRCAqJZyGykMIKUzXOTRGl%2BezvarcRCkcTMJoSEEyeR4PCOJGWWFEhRpWbRGDGZQGUzGEwwJwGVJ6TWWeLHPoGsyuPAeOTxYzGUgiA2knZOk2uGzRLxc8Jhan8yqC2ogeoDMDilptTyIpSmQIuCC0yxOdZrUh5a1%2BLw422uEReK4G1wQLykovBGwBd1baJx93GcI5-yssLE21%2BemudMCz5CkCkNDkADu4dEEtaoI6CmibgcXj6MDr0bwajbeFMIgdFImDJT27kiacQQSlhUqQgOq1h0r%2Bv21IUNhVZw7Lzb0TwYVMFzKgd7we%2BACWYAANYRpK7RKMqCjppYWh6kSDjGEYi4ONEpB%2BNaUKmE4iYwdKpjevigScgyNiRA2rhOE%2BcimDAlFeNROprH4eEstkxRwD2XDBmIhAAC5gROUqKI4nRVpoSgqOqDhaFot4SaQXiJjJR60Q4JilsysrJNEJ7oucyRkcmbLJHpchKZRlEGH48S3D%2BHzcT8g4KABAljpGk7TtBHJQq4Ch%2BOalikP0Ti2AYKgYQueQojAWJFhiThGfIpqpKcuacoW9aJfu8QdmqRZemE%2BgVKU9B8eQqBRg2GgpHprZ6bpelFHpNl6RRGhePEGi%2BHpoR6WeCQVEAA
- ⚡ Grid (black tints):
  - #000000
  - #000000
  - #000000
- 🔆 PV (orange tints, 300 / 300 / 300):
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
- 🔋 Battery (green tints, 500 / 300 / 150):
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
- Cumulative cost: #0570de

**Global chart properties**:
- Height: 280–400px
- Width: Responsive ('stretch')
- Legend: Horizontal, top-right
- Hover: x-unified (all traces at a time), indicating time window (e.g. 9:00 - 9:15) and y values including units

**Forecast charts** (Inputs):
- Import/export price forecast: steplines middle aligned `line_shape="hvh"`
- PV power forecast: filled area
- Base load power forecast: filled area
- EV energy demand forecast: bars (energy per timestep)
- DHW energy demand forecast: bars (energy per timestep)
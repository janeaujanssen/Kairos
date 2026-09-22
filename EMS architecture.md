# Physical Model of Components in a Home

## Sources

| Component | State | Constraints | Forecast |
|-----------|-------|-------------|----------|
| **Grid** | Grid Import/Export Power | • Max import power<br>• Max export power | Price forecast |
| **PV** | Solar Production Power | — | Production Power |

## Storage

| Component | State | Constraints | Forecast | Control |
|-----------|-------|-------------|----------|---------|
| **Home Battery** | SoC | • Energy capacity<br>• Min/Max SoC<br>• Max charge/discharge power | — | Battery Charge/Discharge Power |
| **DHW Tank** | Thermal SoC<br>(based on water temp) | • Thermal capacity<br>• Min/Max temperature | Hot water Energy demand | — |
| **Building Thermal Mass** | Thermal SoC<br>(based on indoor temp) | • Thermal capacity<br>• Min/Max comfort temperature | • Outdoor temp<br>• Solar gains | — |
| **EV Battery** | EV SoC | • Energy capacity<br>• Desired SoC at departure<br>• Max charge/discharge power | Arrival/departure time | Battery Charge/Discharge Power |

## Loads

| Component | State | Constraints | Forecast | Control |
|-----------|-------|-------------|----------|---------|
| **Home Consumption** | Current Power (sum of source and storage power) | — | Power forecast | — |
| **Heat Pump*** | — | — | COP based on outdoor temperature | • Heating curve offset<br>• DHW temperature setpoint |
| **Controllable Loads** | — | • Max power<br>• Device-specific constraints (mostly timing) | — | ON/OFF |

\* **Heat Pump** basically controls the DHW and building thermal capacity and is not a traditional load. Equivalent to the inverter attached to a battery.

## Open Points / Not Yet Modeled

### Neglected

- **Efficiencies / losses**: battery round-trip efficiency & self-discharge, EV charger AC/DC efficiency, DHW tank and building heat-loss coefficients.
- **DHW/building thermal mass control**: Controlled via heat pump.

### Not a Concern

- **Heat pump COP accuracy**: heat pump runs in weather-compensation mode, so COP as a function of outdoor temperature only is sufficiently accurate — no separate flow-temp/DHW-setpoint dependency needed.
- **Heat pump hardware limits**: weather-compensation mode means the heat pump self-regulates to heat demand, so no additional power/modulation/cycling constraints are needed in the model.
- **PV curtailment**: not a practical concern currently.
- **Ramp-rate constraints**: minor enough to ignore for now.

# Abstraction Layer

## Optimization Objective

The optimizer operates in one of two selectable modes:

1. **Self-consumption mode**: Maximize use of locally generated PV energy to increase energy independence and reduce grid interaction.
2. **Cost optimization mode**: Minimize total grid energy cost (or maximize profit) over the planning horizon.

Both modes satisfy all asset constraints and maintain energy balance. The choice of mode is a user configuration parameter.

## Abstraction Model

The optimizer operates on logical energy assets rather than physical actuators. This abstraction creates a clean separation between optimization logic and hardware implementation:

- **Sources** (Grid, PV) supply energy to the system
- **Storage** (batteries, thermal masses) store and release energy over time
- **Loads** (home consumption, controllable devices) consume energy

Each asset independently defines its state, constraints, forecasts, and control interface. The optimizer aggregates these constraints and solves for optimal control setpoints across all assets simultaneously.

**Note**: The optimizer outputs logical control setpoints (e.g., "charge thermal battery at 5 kW") without needing to know about the actual hardware implementation. A separate conversion layer (not yet implemented) will translate these setpoints into physical hardware commands.

This separation allows the optimizer to remain hardware-agnostic while providing a clear interface for future control implementation.

## Optimizer Process

The optimizer solves a constrained optimization problem over a planning horizon (typically 24 hours) at a defined time interval (e.g., 1 hour):

**Inputs:**
- **Current state** (at t=0): Measured Grid/PV/Load power and Storage SoC
- **Forecasts** (for t=1...T): Future power and price values
- **Asset constraints**: Operational limits for all assets

**Design note**: Current states serve as the receding-horizon starting point. For single-iteration use, the optimizer computes the full horizon from measured state. For Model Predictive Control (MPC), the optimizer is called every 10-15 min with fresh measurements, and the forecast window shifts forward accordingly.

**Decision variables:**
Control setpoints for each asset at each time step. The control interface is defined at the asset class level, making it independent of the specific component:

| Asset Class | Control Setpoint | Unit |
|---|---|---|
| **Storage** | Power input/output | kW |
| **Load** | ON/OFF command | Boolean |
| **Source** | (no direct control) | — |

**Optimization objectives:**

**Mode 1: Self-consumption** — Minimize grid interaction:
$$\text{Grid Interaction} = \sum_{t=0}^{T} (|\text{Grid Import}_{t}| + |\text{Grid Export}_{t}|)$$
This mode prioritizes using PV locally (charging storage when PV is abundant, discharging to supply load) and minimizes both imports and exports.

**Note on battery oscillation**: If the battery is predicted to reach full capacity at a future timestep, the optimizer should avoid unnecessary charging/discharging cycles and instead keep the battery idle, as any additional charging would be wasted anyway. This is the drawback of Self-consumption optimization.

**Mode 2: Cost optimization** — Minimize total grid energy cost with optional strategies:
$$\text{Cost} = \sum_{t=0}^{T} (\text{Grid Import}_{t} \times \text{Import Price}_{t} - \text{Grid Export}_{t} \times \text{Export Price}_{t})$$
This mode accounts for time-varying electricity prices and export compensation. When multiple solutions have equal cost, tie-breaking strategies smooth grid interaction:
- **Peak leveling**: Penalizes the highest grid power draw to reduce demand charges and grid stress, spreading consumption evenly without increasing cost
- **Charging priority**: Prioritizes charging storage over exporting excess PV to grid

Subject to (both modes):
- Energy balance at each time step: $\sum \text{Source Power} = \sum \text{Load Power} + \sum \text{Storage Power}$
- All asset constraints: SoC limits, power limits, etc.
- Physical feasibility: cannot discharge more energy than stored, etc.

**Output:**
Optimal control setpoints for each asset at each time step over the planning horizon.

## Sign Convention

All power flows follow a **consistent sign convention** to eliminate ambiguity in the energy balance:

| Asset Class | Positive Direction | Negative Direction | Example |
|---|---|---|---|
| **Source Power** | Supply (Grid import, PV production) | Absorb (Grid export) | +5 kW = buying/producing, −3 kW = selling |
| **Storage Power** | Charge (absorbing energy) | Discharge (supplying energy) | +2 kW = charging, −2 kW = discharging |
| **Load Power** | Consumption (drawing energy) | — | Always ≥ 0 (demand is fixed at forecast) |

This leads to the unified energy balance equation:

$$\sum \text{Source Power} = \sum \text{Load Power} + \sum \text{Storage Power}$$

# Code Architecture & Implementation Structure

## Overview
Focus on getting the optimizer running with simulated data first. Real data integration (via Home Assistant or other sources) and control layer implementation come later. Keep the generation of the simulated data modular and separate from the rest of the code.

While the following describes the implementation of the full stack of components, start with Grid, PV, Battery and Home Load.

The EMS Optimizer follows a **modular, layered architecture** with four main components:

1. **Abstraction Layer**: Asset class hierarchy
2. **Optimizer Core**: Constrained optimization engine  
3. **Visualization Layer**: Chart generation (Plotly)
4. **User Interface**: Streamlit web app

## Architecture Layers

### Layer 1: Abstraction Layer - Asset Classes

All energy assets inherit from a common **`Asset`** base class with four abstract methods:
- `get_state()`: Current operational state
- `get_constraints()`: Operational limits
- `get_forecast()`: Time series data
- `get_control()`: Control interface for the optimizer

Three concrete classes inherit from `Asset`:

- **`Source`**: Energy sources (Grid, PV)
  - State: `current_power` (kW)
  - Constraints: `max_import_power`, `max_export_power` (only for Grid) 
  - Forecast: `price_forecast` (Grid) or `power_forecast` (PV)
  - Control: None
  
- **`Storage`**: Energy storage (Battery, thermal masses)
  - State: `current_soc` (State of Charge in % or thermal equivalent)
  - Constraints: `capacity`, `min_soc`/`max_soc`, `max_charge_power`, `max_discharge_power`
  - Forecast: None (behavior determined by optimization)
  - Control: `set_power(kW)`
  
- **`Load`**: Energy consumers (Home Consumption, controllable loads)
  - State: `current_power` (kW)
  - Constraints: `max_power` (only for controllable loads), `controllable` (boolean)
  - Forecast: `power_forecast` (only for Home Consumption, includes all demand)
  - Control: `set_on_off(Boolean)` (only for controllable loads; None for fixed loads)

This design ensures the optimizer can work with any asset type through a uniform interface.

### Layer 2: Optimizer Core - `Optimizer`

Manages all assets and solves the constrained optimization problem.

**What it does**:
- Collects all asset states, constraints, and forecasts
- Sets up optimization problem: minimize energy cost or maximize self-consumption subject to energy balance and asset constraints
- Solves using a Mixed Integer Linear Program (MILP) solver via CBC and PuLP. This approach is more robust than continuous solvers for discrete battery/EV charging decisions.
- Handles constraint violations gracefully using soft constraints: constraints can be violated with penalties; optimizer always returns best-achievable schedule and flags any violations
- Returns optimal control setpoints

**How it uses states and forecasts**:
- **At t=0** (current time): Uses measured/actual current states (Grid power, PV production, Load demand, Battery SoC)
- **At t>0** (future): Uses forecasts (PV production forecast, Load demand forecast, price forecast)
- This design enables two modes:
  - **Single iteration**: Optimize once with current measured state and 24-hour forecast
  - **Receding horizon (MPC)**: Re-optimize every 10-15 min with fresh measurements, forecast window shifts forward

**Key constraint**: Energy must balance at all times: 
$$\sum \text{Source Power} = \sum \text{Load Power} + \sum \text{Storage Power}$$

### Layer 3: Visualization Layer

Plotting functions generate interactive charts using Plotly, both to visualize input forecasts and also output results.

### Layer 4: User Interface - Streamlit
**In the sidebar**: 

- **▶ Run optimization button**: Primary action button at the top for immediate visibility and easy access to trigger the optimization

- **Sign Convention Reference**: Displays the standardized sign convention for all power flows for the active assets:
  - **Grid Power** (+import, −export)
  - **PV Power** (+production)
  - **Battery Power** (+charge, −discharge)
  - **DHW Battery Power** (+charge, −discharge) 
  - **Building Battery Power** (+charge, −discharge)   
  - **Load Power** (+consumption)

- **Strategy selection**: Optional strategies to apply during cost optimization
  - **Peak leveling**: Reduce demand charges and grid stress by penalizing power peaks
  - **Charging priority**: Prefer self-consumption over grid export

- **Configuration variables for the optimization:**
  - **Optimization mode**: Selection of the optimization target.
  - **Planning Horizon** (hours): How far into the future to optimize (e.g., 6–48 hours)
  - **Time Interval** (minutes): Timestep resolution for optimization (e.g., 60 min = 1-hour intervals)
  - **Solver Tolerance**: Numerical precision for convergence (default: 1e-9)
  - **Max Iterations**: Upper limit on solver iterations (default: 500)

**Two tabs**:

- **Inputs Tab**: System configuration
  - Show three sections, one for each asset type: Sources, Storage, Loads.
  - In each section lists the assets that exist for each asset type in a subsection.
  - For each asset shows 4 sections:
    - **Current state**: Measured/actual values at t=0 (inputs to optimizer as starting point)
    - **Constraints**: Operational limits from the asset class (editable)
    - **Forecast**: Time-series forecast chart(s) for t>0 (with editable forecast parameters)
      - **Grid price forecast**: Dynamic tariffs with baseline price + morning peak (e.g., 8am) + evening peak (e.g., 7pm), export price as fraction of import price
      - **PV production forecast**: Bell curve peaking at solar noon (midday), zero at night
      - **Load demand forecast**: Baseline consumption + morning peak (e.g., 7am) + evening peak (e.g., 7pm)
    - **Control parameter**: Indication of what the optimizer will set for the asset (no user input)
  - Make sure that sections and subsections can be clearly identified.

- **Optimization Tab**: Results and solver diagnostics
  - **Solver info**: Type (MILP via CBC), status (Optimal/Feasible), solve time, violation count
  - **Constraint violations** (if any): Asset, type, max violation, total penalty cost
  - **Cost metrics**: Energy cost, violation penalties, total cost
  - **Current control commands (t=0)**: Hardware setpoints for next interval
  - **Charts**: 
    - **Power flow**: Hybrid chart showing energy balance equation over time
      - Supply side (lines): Net Grid Power (positive = import, negative = export) and PV Power shown as separate line traces for trend visibility
      - Demand side (bars with relative stacking): Load Power and Storage Power (battery) as separate bar traces
        - Positive bars stack together (e.g., Load + Battery charging) using `barmode="relative"`
        - Negative bars (Battery discharging) stack separately below zero, never mixing with Load
      - Visualization makes clear: $\text{Grid} + \text{PV} = \text{Load} + \text{Storage}$ at each timestep
      - Electricity import and export prices on secondary y-axis (optional, shown as dashed lines)
    - **Cost analysis**: Dual-axis hybrid chart with profit/loss indication
      - Bar chart: Cost per interval (kW × €/kWh) at each timestep
        - Red bars: Cost intervals (importing more than exporting)
        - Green bars: Profit intervals (exporting more than importing)
      - Blue line chart (secondary y-axis): Cumulative cost over time
    - **State of charge trajectories**: Multi-asset SoC evolution plot
      - Each storage asset shown as separate line with markers
      - Min/max SoC limits displayed as horizontal dashed lines per asset (color-coded)
      - Supports multiple storage assets (battery, thermal masses, EV) simultaneously

# EVCC Optimizer Integration

## Overview

Additionally the **EVCC optimizer** `https://github.com/evcc-io/optimizer`, a specialized external service for electric vehicle (EV) battery charging optimization is implemented alongside the local optimizer. The EVCC optimizer runs as a separate HTTP service (default: `http://localhost:7050/optimize/charge-schedule`) and handles complex EV charging constraints and strategies.

As in the current state only a single battery is implemented together with PV this can be used as a comparison to the local optimizer.

## Architecture

### Integration Pattern

The EVCC optimizer operates as a **standalone decision module** called alongside (not instead of) the local optimizer:

Both optimizers receive the **same forecasts** and operate independently. Results can be compared or combined by the user.

### API Request Structure

The EMS app sends a JSON payload to the EVCC optimizer, example payload from API docs:

```json
{
  "strategy": {
    "charging_strategy": "none",
    "discharging_strategy": "none"
  },
  "grid": {
    "p_max_imp": 0,
    "p_max_exp": 0,
    "prc_p_exc_imp": 0
  },
  "batteries": [
    {
      "charge_from_grid": true,
      "discharge_to_grid": true,
      "s_capacity": 0,
      "s_min": 0,
      "s_max": 0,
      "s_initial": 0,
      "p_demand": [
        0
      ],
      "s_goal": [
        0
      ],
      "c_min": 0,
      "c_max": 0,
      "d_max": 0,
      "p_a": 0,
      "c_priority": 0
    }
  ],
  "time_series": {
    "dt": [
      0
    ],
    "gt": [
      0
    ],
    "ft": [
      0
    ],
    "p_N": [
      0
    ],
    "p_E": [
      0
    ]
  },
  "eta_c": 0.95,
  "eta_d": 0.95
}
```

### API Response Structure

The EVCC service returns an optimized charging schedule, example response from APi docs:

```json
{
  "status": "string",
  "objective_value": 0,
  "limit_violations": {
    "grid_import_limit_exceeded": true,
    "grid_export_limit_hit": true
  },
  "batteries": [
    {
      "charging_power": [
        0
      ],
      "discharging_power": [
        0
      ],
      "state_of_charge": [
        0
      ]
    }
  ],
  "grid_import": [
    0
  ],
  "grid_export": [
    0
  ],
  "flow_direction": [
    0
  ],
  "grid_import_overshoot": [
    0
  ],
  "grid_export_overshoot": [
    0
  ]
}
```

### Results Display
On the optimization tab, the EVCC optimizer shows the same results (for as much as is possible) to the local optimizer but in a second column such that results can be easily compared.

In essence the only relevant output regarding scheduling from the EVCC optimizer is the battery charge and discharge power schedule, which in turn drives the resulting grid import/export. The remainder of the postprocessing should be the same as for the local optimizer, only the battery power schedule should be used (with the exception of the optimizer solver diagnostics).




# Physical Model of Components in a Home

## Sources

| Component | State | Constraints | Forecast |
|-----------|-------|-------------|----------|
| **Grid** | Grid Import/Export Power | • Max import power<br>• Max export power | Price forecast |
| **PV** | Solar Production Power | — | Production Power |

## Storage

| Component | State | Constraints | Forecast | Control |
|-----------|-------|-------------|----------|---------|
| **Home Battery** | SoC | • Energy capacity<br>• Min/Max SoC<br>• Max charge/discharge power<br>• Charge/discharge efficiency | — | Battery Charge/Discharge Power |
| **DHW Tank** | Thermal SoC<br>(based on water temp) | • Thermal capacity<br>• Min/Max temperature<br>• Max charge/discharge power<br>• Passive discharge power | Hot water demand forecast | Thermal Power<br>(via heat pump setpoint) |
| **Building Thermal Mass** | Thermal SoC<br>(based on indoor temp) | • Thermal capacity<br>• Min/Max comfort temperature<br>• Max charge/discharge power<br>• No passive discharge* | • Outdoor temp<br>• Solar gains | Thermal Power<br>(via heat pump offset) |
| **EV Battery** | EV SoC | • Energy capacity<br>• Desired SoC at departure<br>• Max charge/discharge power<br>• Charge/discharge efficiency | Arrival/departure time | Battery Charge/Discharge Power |

*Building thermal mass has zero passive discharge because baseline weather-compensation heating curve already offsets outdoor heat loss. Stored energy above baseline naturally decays as building cools—this is intentional discharge, not loss.

## Loads

| Component | State | Constraints | Forecast | Control |
|-----------|-------|-------------|----------|---------|
| **Home Consumption** | Current Power (sum of source and storage power) | — | Power forecast | — |
| **Heat Pump*** | — | — | COP based on outdoor temperature | • Heating curve offset<br>• DHW temperature setpoint |
| **Controllable Loads** | — | • Max power<br>• Device-specific constraints (mostly timing) | — | ON/OFF |

\* **Heat Pump** basically controls the DHW and building thermal capacity and is not a traditional load. Equivalent to the inverter attached to a battery.

## Open Points / Not Yet Modeled

### Neglected

- **EV charger efficiency**: AC/DC conversion losses at the wall charger.
- **Thermal storage losses**: DHW tank and building thermal mass heat-loss coefficients (currently estimated as passive_discharge_power by conversion layer).

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
- Storage SoC dynamics with passive loss: $\text{SoC}_{t+1} = \text{SoC}_t + (\text{Storage Power}_t - \text{Passive Discharge}_t) \times \Delta t / \text{Capacity}$
- All asset constraints: SoC limits, power limits, etc.
- SoC dynamics with demand: $\text{SoC}_{t+1} = \text{SoC}_t + \frac{(P_{\text{charge}} \cdot \eta_c - P_{\text{discharge}} - P_{\text{passive}}) \cdot \Delta t - D_t}{\text{Capacity}}$
  - Where $D_t$ is energy demand from storage at timestep $t$ (kWh), if forecast provided
  - Demand directly reduces SoC, creating visible drops in trajectories at demand times
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
  - Constraints: `capacity`, `min_soc`/`max_soc`, `max_charge_power`, `max_discharge_power`, `passive_discharge_power` (only for DHW storage; power loss due to heat loss)
  - Forecast: `demand_forecast` (optional; energy demand at each timestep that withdraws from storage, e.g., hot water usage, EV driving)
  - Control: `set_power(kW)`
  
- **`Load`**: Energy consumers (Home Consumption, controllable loads)
  - State: `current_power` (kW)
  - Constraints: `max_power` (only for controllable loads), `controllable` (boolean)
  - Forecast: `power_forecast` (only for Home Consumption, includes all demand)
  - Control: `set_on_off(Boolean)` (only for controllable loads; None for fixed loads)

This design ensures the optimizer can work with any asset type through a uniform interface.

#### Storage Asset Concrete Examples

All storage types use the same `Storage` class interface. Here are concrete examples showing how physical parameters translate to Storage asset values:

**1. Home Battery (Electrical Energy Storage)**
```python
home_battery = Storage(
    name="Home Battery",
    current_soc=0.50,              # 50% charge
    capacity=10.0,                 # 10 kWh usable
    min_soc=0.10,                  # Health protection: don't go below 10%
    max_soc=0.95,                  # Health protection: don't exceed 95%
    max_charge_power=5.0,          # 5 kW charger limit
    max_discharge_power=5.0,       # 5 kW inverter limit
    passive_discharge_power=0.0,   # Negligible self-discharge over 24h
)
```

**2. DHW Tank (Thermal Energy Storage)**
```python
# Physical parameters:
# • 300-liter tank, 20°C to 60°C range (40°C ΔT)
# • Current water temp: 50°C
# • Heat loss coeff: 0.004 kW/K (modern insulation; range: 0.003-0.008)
# • Min comfort temp for showers: 40°C

dhw_tank = Storage(
    name="DHW Tank",
    current_soc=0.75,              # SoC = (50-20) / (60-20) = 0.75
    capacity=13.96,                # 300L × 1.163 Wh/(L·K) × 40K / 1000
    min_soc=0.50,                  # Comfort constraint: (40-20) / (60-20) = 0.50
    max_soc=1,                     # Up to max temperature
    max_charge_power=3.0,          # Heat pump thermal output (kW)
    max_discharge_power=0.0,       # No active discharge (passive loss only)
    passive_discharge_power=0.16,  # Heat loss at max temp: HLC × ΔT = 0.004 × 40 = 0.16 kW
)
```

The DHW tank is abstracted as **virtual thermal energy storage** using the same `Storage` interface:

- **State of Charge (SoC)**: Derived from measured water temperature: $\text{SoC} = \frac{T_{\text{water}} - T_{\text{min}}}{T_{\text{max}} - T_{\text{min}}}$
  - Measured directly from tank temperature sensor
  - Example: If T_min = 20°C (ambient temperature around the tank), T_max = 60°C (maximum safe), and current = 50°C → SoC = 0.75
- **Capacity**: Calculated directly from tank volume: $E_{\text{max}} = V_{\text{tank}} \cdot 1.163 \cdot (T_{\text{max}} - T_{\text{min}}) / 1000$
  - $V_{\text{tank}}$ = water volume in liters
  - 1.163 Wh/(liter·K) = specific heat of water
  - Example: 300-liter tank, 40°C temperature range (20–60°C) → ~13.8 kWh capacity
- **Self-discharge (Heat Loss)**: Heat naturally flows out via tank insulation: $Q_{\text{loss}} = \text{HLC}_{\text{tank}} \cdot (T_{\text{water}} - 20°C)$
  - HLC_tank = tank heat loss coefficient (kW/K)
  - Ambient temperature fixed at 20°C (room temperature inside house)
- **Hot Water Demand Forecast**: Optional forecast of hot water usage patterns (e.g., showers expected at 7 AM and 9 PM)
  - Provides demand at each timestep (kWh), e.g., "0.8 kWh needed at 7 AM"
  - **Integrated into SoC dynamics**: Demand energy is subtracted directly from storage, causing actual SoC drops at demand times
  - Optimizer automatically schedules pre-charging before high-demand periods to ensure sufficient energy is available
  - Helps optimize charging timing based on prices and solar availability
  - Without this forecast, only the min_soc comfort constraint drives charging (reactive)
  - With forecast, charging becomes proactive—the optimizer schedules pre-heating during cheap electricity or high solar production
  - **Benefit**: SoC trajectory now shows natural drops at demand times, making it clear when energy is being withdrawn
- **Control**: Optimizer sets thermal power (kW) via `set_power()`, which maps to a DHW temperature setpoint:
  - Positive power (e.g., +3 kW): Charge the tank (pre-heating water)
  - Zero power: Maintain current temperature (offset losses only)
  - The translation layer converts requested power to DHW setpoint: $T_{\text{setpoint}} = T_{\text{baseline}} + K_{\text{dhw}} \cdot P_{\text{thermal}}$, where $K_{\text{dhw}}$ is the temperature gain factor

Like the building, the optimizer is completely hardware-agnostic; the heat pump's actual DHW control (setpoint adjustment, three-way valve routing) is handled by the translation layer.

**3. Building Thermal Mass (Space Heating Storage)**
```python
# Physical parameters:
# • Thermal capacitance: 25 kWh/K (larger residential building; range: 5-30 depending on size/mass)
# • Thermal time constant: ~8 hours (time to cooldown 1°C when heating is off)
# • Baseline temp: 20°C (maintained by weather compensation)
# • Max comfort temp: 21°C
# • Current indoor temp: 20.5°C

building_thermal = Storage(
    name="Building Thermal Mass",
    current_soc=0.50,              # SoC = (20.5-20) / (21-20) = 0.50
    capacity=25.0,                 # 25 kWh/K × (21-20)K = 25 kWh
    min_soc=0.0,                   # Allow full discharge to baseline
    max_soc=1.0,                   # Allow full charge to comfort limit
    max_charge_power=5.0,          # Heat pump active pre-heating (kW)
    max_discharge_power=3.1,       # Passive cooling with heat pump off: capacity / time_constant = 25 kWh / 8h = 3.1 kW
    passive_discharge_power=0.0,   # Weather curve handles baseline losses
)
```

The building thermal mass is abstracted as **virtual energy storage** using the same `Storage` interface.

- **State of Charge (SoC)**: Derived from measured temperature: $\text{SoC} = \frac{T_{\text{indoor}} - T_{\text{baseline}}}{T_{\text{max}} - T_{\text{baseline}}}$
  - Measured directly, eliminating accumulated estimation error
  - **Baseline temperature** (typically 20°C) is maintained passively by weather compensation heating curve
  - Example: If baseline = 20°C, max comfort = 21°C, and current = 20.5°C → SoC = 0.5
- **Capacity**: Thermal energy storage within comfort band: $E_{\text{max}} = C_{\text{building}} \cdot (T_{\text{max}} - T_{\text{baseline}})$
  - $C_{\text{building}}$ = thermal capacitance (kWh/K): energy needed to raise building temperature by 1°C
- **Passive Discharge**: Zero (no true losses)
  - The baseline heating curve (weather compensation mode) already offsets outdoor heat loss, maintaining 20°C
  - Any stored energy above baseline naturally decays as the building cools back toward 20°C
  - This is intentional **discharge** (using stored energy), not a **loss** (energy escaping to environment)
- **Charging (Active)**: Optimizer sets thermal power (kW) via `set_power()`:
  - Positive power (e.g., +2 kW): Raise weather compensation curve by offset +ΔT
  - Heat pump delivers more power than needed for baseline, pre-heating building
  - Relationship: $P_{\text{charge}} = K_{\text{charge}} \cdot \Delta T_{\text{curve}}$ (to be calibrated)
  - Fast, controlled by heat pump (up to max charge power, typically 5 kW)
  
- **Discharging (Active cooling)**: Optimizer sets negative thermal power (kW) via `set_power()`:
  - Negative power (e.g., -1 kW): Lower weather compensation curve by offset -ΔT below baseline
  - Heat pump reduces active heating, allowing building to cool faster toward lower setpoint
  - Discharge power from temperature difference: $P_{\text{discharge}} = K_{\text{discharge}} \times (T_{\text{indoor}} - T_{\text{setpoint,lowered}})$
  - Even with baseline curve, if building is above 20°C, passive discharge occurs: $P_{\text{passive}} = K_{\text{discharge}} \times (T_{\text{indoor}} - 20°C)$
  - $K_{\text{discharge}}$ relates temperature difference between indoor temperature and curve setpoint to available discharge power (to be calibrated empirically)
  - Not independently controllable at fixed rate—discharge rate depends on indoor temperature and setpoint difference
  - Slower than charging due to thermal inertia and being limited by how much you can lower the setpoint
  
- **Control Strategy**: Optimizer orchestrates charging/discharging around prices and renewable availability:
  - **During cheap electricity or high solar**: Raise curve offset (+ΔT) to actively pre-heat
  - **During expensive periods or low solar**: Lower curve offset (-ΔT) to reduce active heating, letting stored thermal energy offset the load
  - Translation layer calibrates the relationship between curve offset (ΔT) and actual power

**4. EV Battery (Vehicle Energy Storage)**
```python
ev_battery = Storage(
    name="EV Battery",
    current_soc=0.50,              # 30 kWh / 60 kWh = 50%
    capacity=60.0,                 # 60 kWh usable
    min_soc=0.10,                  # Health protection: 10% minimum
    max_soc=0.90,                  # Health protection: 90% maximum
    max_charge_power=7.0,          # AC charger limit (kW)
    max_discharge_power=3.0,       # V2G capability (kW)
    passive_discharge_power=0.0,   # Negligible self-discharge
)
# Note: Departure time SoC goal (e.g., 80% by 08:00) is enforced as separate constraint
```

The EV battery is abstracted as **virtual energy storage** using the same `Storage` interface.

- **State of Charge (SoC)**: Energy stored as a fraction of capacity: $\text{SoC} = \frac{E_{\text{stored}}}{E_{\text{capacity}}}$
  - Measured directly from vehicle battery management system
  - Example: If capacity = 60 kWh and stored = 30 kWh → SoC = 0.5
- **Capacity**: Total usable energy in the battery: $E_{\text{capacity}}$ (kWh)
  - Vehicle-specific parameter, typically provided by manufacturer
  - Example: 60 kWh usable capacity
- **Charge/Discharge Power Limits**: Set by charger hardware and vehicle battery management
  - $P_{\text{charge, max}}$ (kW): Maximum AC power accepted by on-board charger
  - $P_{\text{discharge, max}}$ (kW): Maximum power for vehicle-to-grid (V2G) if supported; zero if V2G not available
- **Time-Dependent Constraint**: Vehicle departure time creates a hard deadline for SoC:
  - Desired SoC at departure: $\text{SoC}_{\text{goal}}$ at time $t_{\text{departure}}$
  - Optimizer must ensure: $\text{SoC}(t_{\text{departure}}) \geq \text{SoC}_{\text{goal}}$
  - Example: Vehicle departs at 8:00 AM with goal SoC = 0.8 (48 kWh for 60 kWh battery)
- **Min/Max SoC Constraints**: Health and usability limits
  - min_soc: Minimum allowed state (e.g., 0.1 to preserve battery health)
  - max_soc: Maximum allowed state (e.g., 0.9 to avoid overcharging)
- **Control**: Optimizer sets electrical power (kW) via `set_power()`:
  - Positive power (e.g., +7 kW): Charge the vehicle (draw power from grid)
  - Zero power: No charging (vehicle idle or charging paused)
  - Negative power (if V2G supported, e.g., −3 kW): Discharge to grid (vehicle supplies power)
  - The translation layer converts requested power into charger commands (start/stop, set current limit)

Unlike thermal storage, the EV battery has no passive discharge (no self-discharge over the optimization horizon) and does not depend on ambient conditions. The key challenge is meeting the departure-time SoC goal while optimizing energy cost or self-consumption.

**Baseline approach (Reactive):** When vehicle connects, re-optimize to charge by next known departure. The optimizer finds the cheapest or most self-consumptive charging window within that constrained time interval. This is the primary mode: **active control only occurs when the vehicle is connected and charging.**

**With arrival/departure forecast (Limited benefit):** Using GPS data and historic patterns, predict today's arrival and next departure times. The main benefit is **preparatory multi-asset coordination**: knowing the EV will arrive at 5 PM, the optimizer can pre-stage other assets (home battery, DHW) to complete their charging before arrival, freeing up grid capacity for the EV.

However, for typical single-vehicle scenarios with adequate grid capacity, this benefit is marginal—reactive optimization upon connection is usually sufficient and simpler. Predictive arrival becomes more valuable only in constrained scenarios:
- **Tight grid import limits** (≤10 kW): Must coordinate asset charging windows to avoid simultaneous peaks
- **Multiple vehicles**: Stagger charging across several EVs
- **Complex competing demands**: DHW heating + building thermal charging + EV all competing for limited power

For initial implementation, **start with reactive approach** (simpler, sufficient for most cases).

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
  - **Soft constraint penalty values**: Values used to manage the impact of constraint violations.

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
    - For the storage assets that need a conversion from physical parameters to standard battery parameters, there is a separate top section where these physical parameters can be edited. The dependent battery parameters should be locked for editing.
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

The EMS app sends a JSON payload with the following structure (all fields in **SI base units: W, Wh, seconds**):

```json
{
  "strategy": {
    "charging_strategy": "charge_before_export",
    "discharging_strategy": "discharge_before_import"
  },
  "grid": {
    "p_max_imp": 10000,          // W (10 kW)
    "p_max_exp": 8000,           // W (8 kW)
    "prc_p_exc_imp": 0           // EUR/W (penalty for exceeding import limit)
  },
  "batteries": [
    {
      "charge_from_grid": true,
      "discharge_to_grid": true,
      "s_capacity": 10000,        // Wh (10 kWh)
      "s_min": 1000,              // Wh (min SoC)
      "s_max": 9500,              // Wh (max SoC)
      "s_initial": 5000,          // Wh (starting state, 50%)
      "p_demand": [0, 0, ...],    // Wh/timestep (min charge demand)
      "s_goal": [0, 0, ...],      // Wh/timestep (goal SoC per timestep)
      "c_min": 0,                 // W
      "c_max": 5000,              // W (5 kW)
      "d_max": 5000,              // W (5 kW)
      "p_a": 0,                   // EUR/Wh (residual battery value)
      "c_priority": 1
    }
  ],
  "time_series": {
    "dt": [3600, 3600, ...],      // seconds (1-hour intervals)
    "gt": [500, 400, ...],        // Wh/timestep (home load: 0.5 kW × 1h = 0.5 kWh)
    "ft": [5000, 4500, ...],      // Wh/timestep (PV yield: 5 kW × 1h = 5 kWh)
    "p_N": [0.20, 0.20, ...],     // EUR/kWh (grid import price)
    "p_E": [0.14, 0.14, ...]      // EUR/kWh (grid export price, 70% of import)
  },
  "eta_c": 0.95,                  // charging efficiency (95%)
  "eta_d": 0.95                   // discharging efficiency (95%)
}
```

**Key point on input units**: EVCC expects energy per timestep (Wh), not instantaneous power. For example, a 5 kW load over 1 hour becomes 5,000 Wh.

## Output JSON Structure

The EVCC service returns an optimized schedule with the same unit convention (W, Wh, seconds):

```json
{
  "status": "optimal",
  "objective_value": 12.50,       // EUR (total cost)
  "limit_violations": {
    "grid_import_limit_exceeded": false,
    "grid_export_limit_hit": false
  },
  "batteries": [
    {
      "charging_power": [5000, 4000, ...],      // Wh/timestep
      "discharging_power": [0, 1000, ...],      // Wh/timestep
      "state_of_charge": [5000, 8000, ...]      // Wh (energy at end of each timestep)
    }
  ],
  "grid_import": [2000, 1500, ...],             // Wh/timestep
  "grid_export": [0, 500, ...],                 // Wh/timestep
  "flow_direction": [0, 1, ...],                // binary (0=import, 1=export)
  "grid_import_overshoot": [0, 0, ...],         // Wh/timestep (above limit)
  "grid_export_overshoot": [0, 0, ...]          // Wh/timestep (below limit due to export cap)
}
```
**Key point on output units**: All energy flows are per timestep (Wh), not power. To align with the local optimizer's power-based interface (kW), the results must be converted by dividing by timestep duration.
## Results Display

On the optimization tab, the EVCC optimizer results appear in a second column parallel to the local optimizer, it follows identical structure and contents (as much as is possible).

All charts and metrics use the converted units (kW, kWh, %) matching the local optimizer for direct visual comparison.

### Configuration Options in Sidebar

- **EVCC service URL**: Endpoint for the external optimizer (default: `http://localhost:7050/optimize/charge-schedule`)
- **EVCC import limit penalty (EUR/W)**: Penalty cost for exceeding grid import limit. Set to 0 for hard constraint (violations reported), or > 0 for soft constraint allowing violations at a cost (default: 0).






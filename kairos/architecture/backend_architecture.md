# Backend Architecture for Kairos
###  Easy, optimized energy scheduling for Home Assistant

> **Status:** Final. This document describes the backend architecture of Kairos, including the energy device abstraction, the optimizer, and the storage classes.
> **To Do:**
> - PV curtailment: PV is a decision variable that allows reducing PV output when necessary, not to be implemented yet.
> - Not super happy with Building Thermal Mass implementation:
>   - Building thermal mass heat pump: Handle subtracting delta power (only the charging/discharging delta based on mode, not full heat pump consumption) from household consumption in Home Assistant
# Contents

- [Sign Convention](#sign-convention)
- [Energy Devices Abstraction](#energy-devices-abstraction)
  - [Overview](#overview)
  - [Sources](#sources)
  - [Loads](#loads)
  - [Storage](#storage)
  - [Storage Classes](#storage-classes)
- [Optimizer](#optimizer)
  - [High Level Process](#high-level-process)
  - [Optimization Objective](#optimization-objective)
  - [Optimizer Constraints](#optimizer-constraints)
  - [Optimizer Output](#optimizer-output)


# Sign Convention

All power flows follow a **consistent sign convention** to eliminate ambiguity in the energy balance:

| Asset Class | Positive Direction | Negative Direction | Example |
|---|---|---|---|
| **Source Power** | Supply (Grid import, PV production) | Absorb (Grid export) | +5 kW = buying/producing, −3 kW = selling |
| **Storage Power** | Charge (absorbing energy) | Discharge (supplying energy) | +2 kW = charging, −2 kW = discharging |
| **Load Power** | Consumption (drawing energy) | — | Always ≥ 0 (demand is fixed at forecast) |

This leads to the unified energy balance equation:

$$\sum \text{Source Power} = \sum \text{Load Power} + \sum \text{Storage Power}$$

# Energy Devices Abstraction
## Overview

A typical residential energy system contains a mix of devices that produce, consume, and store energy.

To allow Kairos to work independently of specific hardware, all physical devices are mapped onto three generic asset classes:

- Source
- Load
- Storage

Example:

| Sources   | Loads             | Storage        |
|-----------|-------------------|----------------|
| Grid      | Household Demand  | Home Battery   |
| Solar PV  | Dishwasher        | EV Battery     |
|           | Washing Machine   | DHW Tank       |
|           | Pool Pump         | Building Mass  |

This abstraction allows the optimizer to reason about energy flows without requiring knowledge of the underlying technology.
Each asset class has attributes that either describe its current state, act as a constraint or contain forecasts.

## Sources

Sources provide energy to the household energy system.

Typical examples:

- Grid connection
- Solar PV system

### Attributes

Every source shares a general attribute. Attributes that depend on the source type are defined per source class.

#### General attributes

##### State
- Current Power [W]

#### Class specific attributes

| Source class | Class specific attributes |
|---|---|
| `Grid` | Max Import Power [W]<br>Max Export Power [W]<br>Import Price Forecast [price/Wh per time step]<br>Export Price Forecast [price/Wh per time step] |
| `PV` | Power Forecast [W per time step] |

## Loads

Loads consume energy within the household. There are two types of loads:

1. **Base Load**: The household's electrical power draw excluding every device modelled in Kairos (battery and EV charging, DHW and building heat pumps, controllable loads). For the heat pump, only the power offsets w.r.t. the default weather compensation power need to be excluded. This is not controllable and is fixed at its forecast.
2. **Controllable Loads**: Appliances that can be scheduled within operating windows (e.g., washing machine, dishwasher, pool pump).

Typical examples:

- Base Load (residual household demand)
- Controllable loads (e.g., washing machine, dishwasher, pool pump)

### Attributes

Every load shares a set of general attributes. Attributes that depend on the load type are defined per load class.

#### General attributes

##### State
- Current Power [W]

##### Constraints
- Controllable [-] *(yes/no, fixed per class: no for `BaseLoad`, yes for `ControllableLoad`)*

#### Class specific attributes

| Load class | Class specific attributes |
|---|---|
| `BaseLoad` (household demand) | Power Forecast [W per time step] |
| `ControllableLoad` (washing machine, dishwasher, pool pump) | Average Power [W]<br>Energy Demand [Wh]<br>Earliest Start Time [timestamp]<br>Latest Finish Time [timestamp] |

## Storage

Storage assets shift energy through time.

Typical examples:

- Home Battery
- EV Battery
- Domestic Hot Water (DHW) Tank
- Building Thermal Mass

### Attributes

Every storage asset shares a set of general attributes. Attributes that depend on the storage type are defined per storage class (see [Storage Classes](#storage-classes)).

#### General attributes

##### State
- Current State of Charge [-] (SoC)

##### Constraints
- Energy Capacity [Wh]
- Max SoC [-]
- Min SoC [-]
- Charge Efficiency [-]
- Discharge Efficiency [-]
- Passive Discharge Power [W] *(typically DHW storage)*
- Discharge to Electrical Network [-] *(yes/no, yes for electrical storage, no for thermal storage)*

##### Forecasts (value per time step)
- Energy Demand Forecast [Wh] *(typically EV battery or DHW storage)*
- Availability Window [-] *(1/0 for available/unavailable, typically EV)*

#### Class specific attributes

| Storage class | Class specific attributes |
|---|---|
| `Battery` (home battery, EV battery) | Max Charge Power [W]<br>Max Discharge Power [W] |
| `DHW` (DHW tank) | Charge Power [W] *(discrete, electric power of the heat pump)* |
| `BTM` (building thermal mass) | Charge Power [W] *(discrete, electric power in +dT mode)*<br>Discharge Power [W] *(discrete, thermal power in -dT mode)*<br>Default Efficiency [-] *(heat pump COP in default curve mode)* |

## Storage Classes

The storage classes provide a representation for all types of storage assets, allowing the optimizer to handle them in a consistent manner regardless of their physical implementation.
All classes share the general storage attributes. Each class adds the attributes that are specific to its physical behaviour.
The attributes might make sense for a normal battery, but less for thermal storage like DHW tanks or building thermal mass. Therefore, a conversion layer is required to map the physical input characteristics of each storage type to the class attributes.

### Conversion Layer for Home Battery
For a normal home battery, the conversion layer is straightforward as the physical parameters directly map to the `Battery` class attributes.

```python
# Physical input parameters:

# Current SoC: 50%
# Energy capacity: 10000 Wh
# Min SoC: 10%
# Max SoC: 90%
# Max charge power: 5000 W
# Max discharge power: 5000 W
# Charge efficiency: 0.95
# Discharge efficiency: 0.95
# Passive discharge power: 0 W (no passive discharge for the battery)

# Resulting storage object:
home_battery = Battery(
    # General storage attributes
    name="Home Battery",
    current_soc=0.5,                                # 50%
    energy_capacity=10000,                          # 10000 Wh
    max_soc=0.9,                                    # Health protection: 90% maximum
    min_soc=0.1,                                    # Health protection: 10% minimum
    charge_efficiency=0.95,                         # One-way efficiency
    discharge_efficiency=0.95,                      # One-way efficiency
    passive_discharge_power=0,                      # No passive discharge for battery
    discharge_to_electrical_network=True,           # Battery can discharge to the electrical network
    energy_demand_forecast=[0, 0, ... 0, 0],        # No specific energy demand forecast for the battery
    availability_window=[1, 1, ... 1, 1],           # Always connected and available

    # Class specific attributes
    max_charge_power=5000,                          # Charger limit
    max_discharge_power=5000,                       # Discharger limit
)
```

### Conversion Layer for EV Battery
For an EV battery, the conversion layer maps the physical parameters of the EV battery to the `Battery` class attributes. The main difference compared to a home battery is that it has additional physical input parameters to define the energy demand forecast and the availability window.

```python
# Physical input parameters:

# Current SoC: 50%
# Energy capacity: 60000 Wh
# Min SoC: 10%
# Max SoC: 90%
# Max charge power: 7400 W
# Max discharge power: 0 W
# Charge efficiency: 0.95
# Discharge efficiency: 0.95
# Passive discharge power: 0 W (no passive discharge for the battery)
# Vehicle efficiency: 0.005 km/wh
# Round trip distance: 100 km
# Expected departure time: 09:00 h
# Expected arrival time: 18:00 h

# Resulting storage object:
ev_battery = Battery(
    # General storage attributes
    name="EV Battery",
    current_soc=0.5,                                # 50%
    energy_capacity=60000,                          # 60000 Wh
    max_soc=0.9,                                    # Health protection: 90% maximum
    min_soc=0.1,                                    # Health protection: 10% minimum
    charge_efficiency=0.95,                         # One-way efficiency
    discharge_efficiency=0.95,                      # One-way efficiency
    passive_discharge_power=0,                      # No passive discharge for battery
    discharge_to_electrical_network=True,           # Battery can discharge to the electrical network
    energy_demand_forecast=[0, 20000, ... 0, 0],    # (Wh) per time step. Set based on vehicle efficiency, round trip distance, and expected departure time
    availability_window=[1, 0, ... 0, 1],           # Set based on expected departure and arrival times

    # Class specific attributes
    max_charge_power=7400,                          # Charger limit
    max_discharge_power=0,                          # Vehicle to grid capability
)
```

### Conversion Layer for DHW Storage
The optimal charging of the DHW tank is driven by the energy demand forecast. This can be a proper forecast but a simple typical estimate like a morning and evening energy demand can be sufficient for most cases.

```python
# Physical input parameters:

# Tank volume: 300 liters
# Min water temperature: 20°C
# Max water temperature: 60°C
# Current water temperature: 50°C
# Min comfort temperature: 40°C
# Heat loss coefficient: 4 W/°C (modern insulation)
# Heat pump electric power: 3000 W
# Heat pump COP: 3
# Morning peak energy demand: 150 Wh
# Evening peak energy demand: 180 Wh
# Morning peak time: 7:00
# Evening peak time: 19:00

# Resulting storage object:
dhw_tank = DHW(
    # General storage attributes
    name="DHW Tank",
    current_soc=0.75,                               # (50-20) / (60-20) = 0.75
    energy_capacity=13960,                          # Thermal energy: 300L × 1.163 Wh/(L·K) × (60-20) = 13960 Wh
    max_soc=1,                                      # Up to max temperature    
    min_soc=0.5,                                    # Down to comfort temperature: (40-20) / (60-20) = 0.5
    charge_efficiency=3,                            # Heat pump COP
    discharge_efficiency=1.0,                       # Assuming ideal efficiency for simplicity
    passive_discharge_power=160,                    # Heat loss at max temp: HLC × ΔT = 4 × (60-20) = 160 W
    discharge_to_electrical_network=False,          # Thermal storage does not discharge to the electrical network
    energy_demand_forecast=[150, 140, ... 180, 0],  # (Wh) per time step. Set based on morning and evening peak energy demand and time.
    availability_window=[1, 1, ... 1, 1],           # Always connected and available

    # Class specific attributes
    charge_power=3000,                              # Electric power: Heat pump electric power (W), this is not a max power value but a discretely defined power
)
```

### Conversion Layer for Building Thermal Mass
As a simple approach to controlling the building thermal mass using a heat pump, we use a temperature offset on the weather compensation curve. The default curve is for example set to achieve a consistent indoor temperature of 20°C. By adjusting the curve up or down, we can effectively charge or discharge the building's thermal mass. Shifting energy usage from peak to off-peak periods. So the heat pump is controlled by setting it in one of three modes: +dT (charging), -dT (discharging), and 0 (neutral). The heating rate and cooldown rate of the +dT and -dT modes are empirically determined by the user. The thermal mass coefficient doesn't need to be accurately known for this control strategy as it is only used by the optimizer to estimate the amount of energy that can be shifted through preheating. The actual control behavior is determined by the empirically measured heating and cooldown rates.

```python
# Physical input parameters:

# Floor area: 100 m²
# Thermal mass coefficient: 200 Wh/m²/°C
# Default weather compensation temperature: 20°C
# Current indoor temperature: 20.5°C
# Max comfort temperature: 21°C
# Heating rate: 0.1 °C/hour (heat pump set +dT w.r.t. default curve)
# Cooldown rate: 0.1 °C/hour (heat pump set -dT w.r.t. default curve)
# Heat pump COP for +dT mode: 2.5
# Heat pump COP for default curve mode: 3

# Resulting storage object:
building_thermal_mass = BTM(
    # General storage attributes
    name="Building Thermal Mass",
    current_soc=0.5,                                # (20.5 - 20) / (21 - 20) = 0.5
    energy_capacity=20000,                          # Thermal energy: 100 m² × 200 Wh/m²/°C × (21 - 20)°C = 20000 Wh
    max_soc=1,                                      # Up to max comfort temperature
    min_soc=0,                                      # Down to default weather compensation temperature
    charge_efficiency=2.5,                          # Heat pump COP for +dT mode
    discharge_efficiency=1,                         # Assuming ideal efficiency for simplicity
    passive_discharge_power=0,                      # Not relevant for building thermal mass
    discharge_to_electrical_network=False,          # Thermal storage does not discharge to the electrical network
    energy_demand_forecast=[0, 0, ... 0, 0],        # Not relevant for building thermal mass
    availability_window=[1, 1, ... 1, 1],           # Always connected and available

    # Class specific attributes
    charge_power=4800,                              # Electric power: 20000 Wh / (21 - 20)°C * 0.6 °C/hour / 2.5 = 4800 W, this is not a max power value but a discretely defined power
    discharge_power=2000,                           # Thermal power: 20000 Wh / (21 - 20)°C * 0.1 °C/hour = 2000 W, this is not a max power value but a discretely defined power
    default_efficiency=3,                           # Heat pump COP for default curve mode
)
```
# Optimizer
## High Level Process

The optimizer determines the optimal operating strategy for all controllable assets over a planning horizon. It takes as input the current states, constraints and forecasts of all assets. For each time step, the optimizer then determines:
- The optimal power setpoints for each controllable asset (e.g., battery, EV, DHW, building thermal mass, controllable loads)

These are the decision variables. Decision variables represent the quantities the optimizer is allowed to change in order to achieve the optimization objective.

The optimizer solves the optimization problem using a Mixed Integer Linear Programming (MILP) solver via CBC and PuLP. This approach is more robust than continuous solvers for discrete battery/EV charging decisions.

The power setpoints at t=0 can then be immediately applied to the assets, making sure that the physical devices follow the setpoints accurately. For continuous operation, this process is repeated at regular intervals to adapt to changing conditions and updated forecasts. This is known as a receding horizon or model predictive control approach. To give the actual commands to the assets, the optimizer's output must be translated into device-specific control signals. This is done through a control interface, e.g. Home Assistant.

## Optimization Objective

The optimizer basically optimizes for a minimum or maximum of a certain objective function. In our case this is a minimization of the total energy cost over the planning horizon. Typically the following objective function is used:

$$\text{Cost} = \sum_{t=0}^{T} (\text{Grid Import Energy}_{t} \times \text{Import Price}_{t} - \text{Grid Export Energy}_{t} \times \text{Export Price}_{t})$$

### Building Thermal Mass Discharge Benefit
But because of our way of implementing the building thermal mass this objective function is not yet complete.

- When the building thermal mass is charged, extra energy is used, and this is represented in the objective function with: Grid Import Energy x Import Price
- When the building thermal mass is discharged, it allows the building to cool down, which does not directly translate into economic benefits in the objective function as there is no electrical energy exported. The economic benefit comes from avoiding the normally required Grid Import Energy at that time.

So by pre-charging the building thermal mass when electricity prices are low, the optimizer can reduce grid import costs during periods of high electricity prices, during discharge of the thermal mass.
This is in contrast with the DHW thermal storage, where the energy demand forecast dictates how much the storage should be charged, the economic benefit is then defined in the objective function by minimizing Grid Import Energy x Import Price.

To capture this benefit in the objective function, an additional term is introduced: Building Thermal Discharge Benefit (note that this term only applies to building thermal storage).

$$\text{Cost} = \sum_{t=0}^{T} (\text{Grid Import Energy}_{t} \times \text{Import Price}_{t} - \text{Grid Export Energy}_{t} \times \text{Export Price}_{t} - \text{Building Thermal Discharge Benefit}_{t})$$

With the building thermal discharge benefit being:

$$\text{Building Thermal Discharge Benefit}_{t} = \text{Building Discharged Thermal Energy}_{t} \times \frac{\eta_{\mathrm{discharge}}}{\eta_{\mathrm{default}}} \times \text{Import Price}_{t}$$

where:

- $\eta_{\mathrm{discharge}}$ is the building thermal storage discharging efficiency (`discharge_efficiency`), thermal to thermal conversion, which is 1.
- $\eta_{\mathrm{default}}$ is the heat pump COP during operation in default weather compensation curve mode (`default_efficiency` of the `BTM` class), electrical to thermal conversion.

This term represents the avoided electricity cost obtained by using previously stored thermal energy instead of producing the same heat at the current electricity price.

### End-of-Horizon Value

Because the optimization horizon is finite, energy remaining in storage at the end of the horizon may still have value beyond the optimization period.

To prevent the optimizer from unnecessarily depleting storage assets near the end of the horizon, a terminal value can be assigned to the remaining stored energy. This rewards schedules that retain useful energy for future operation outside the optimization horizon.

The objective function will then be:
$$\text{Cost} = \sum_{t=0}^{T} (\text{Grid Import Energy}_{t} \times \text{Import Price}_{t} - \text{Grid Export Energy}_{t} \times \text{Export Price}_{t} - \text{Building Thermal Discharge Benefit}_{t}) - \text{Remaining Storage Value}_{T}$$

With the remaining storage value being:

$$\text{Remaining Storage Value}_{T} = \text{Remaining Stored Energy}_{T} \times \eta_{\mathrm{value}} \times \text{Future Import Price}$$

With

- $\text{Future Import Price}$ being a conservative estimate of the electricity import price beyond the optimization horizon, calculated as the average of the cheapest 25% of forecast intervals (rounding the interval count up, with at least one interval). The average forecast price remains the scale used by the grid-peak tie-breaker.
- $\eta_{\mathrm{value}}$ being the amount of grid electricity [Wh] that one stored Wh is worth, which depends on the storage type:

| Storage type | $\eta_{\mathrm{value}}$ | Reasoning |
|---|---|---|
| Thermal, DHW tank | $\eta_{\mathrm{discharge}} / \eta_{\mathrm{charge}}$ | Useful energy is equivalent to the stored energy $\times\ \eta_{\mathrm{discharge}}$. Producing that same amount of useful energy directly would require that amount $/\ \eta_{\mathrm{charge}}$ of electric energy, where $\eta_{\mathrm{charge}}$ is the COP (`charge_efficiency` of the `DHW` class). |
| Thermal, building thermal mass | $\eta_{\mathrm{discharge}} / \eta_{\mathrm{default}}$ | Same reasoning as the DHW tank, but the COP that applies is the one of the default weather compensation curve ($\eta_{\mathrm{default}}$: `default_efficiency` of the `BTM` class), as that is the mode in which the heat would otherwise be produced. |
| Electrical (home battery, EV battery) | $\eta_{\mathrm{discharge}}$ | Useful energy is equivalent to the stored energy $\times\ \eta_{\mathrm{discharge}}$. Obtaining that same amount of useful energy directly would require importing exactly that amount from the grid (1:1), so $\eta_{\mathrm{charge}}$ does not appear. |
---
### Storage Mode Switching Penalty

To favor longer continuous operating runs, the optimizer uses binary mode variables $c_t$ and $d_t$ for each storage device at each timestep $t$, representing charge and discharge modes respectively. 

$$c_t, d_t \in \{0, 1\}$$

These binaries are shared with the mutual exclusivity constraints (see below). The switching penalty discourages mode changes by penalizing transitions:

$$\text{Switching Penalty} \times \sum_t \text{switch}_t$$

where $\text{switch}_t$ captures any mode transition. Define $\text{switch}_t$ as:

$$\text{switch}_t \geq \max(|c_t - c_{t+1}|, |d_t - d_{t+1}|)$$

Linearized as:

$$\text{switch}_t \geq c_t - c_{t+1}, \quad \text{switch}_t \geq c_{t+1} - c_t$$
$$\text{switch}_t \geq d_t - d_{t+1}, \quad \text{switch}_t \geq d_{t+1} - d_t$$

This ensures a direct transition from charge to discharge (c: 1→0, d: 0→1) is penalized once, not twice.

The parameter $\text{Switching Penalty}$ is the cost-equivalent penalty per mode change [currency units]. It trades a potentially small increase in energy cost for fewer switches; unlike [secondary objectives](#secondary-objectives), it can change which schedule is optimal. This is a soft preference, not a guaranteed minimum run length—the optimizer will accept switches if the energy cost savings justify them.

When BTM shares a heat pump with DHW (see [Mutual Exclusivity of Charging the DHW Tank and Building Thermal Mass](#mutual-exclusivity-of-charging-the-dhw-tank-and-building-thermal-mass)), the shared resource constraint forces unavoidable alternation between DHW and BTM charging; the switching penalty then discourages unnecessary additional switches within a charging or idle phase.

### Secondary Objectives

In some situations, multiple schedules result in the same total energy cost. For example, when electricity prices are identical over several timesteps, charging a battery now or later may lead to exactly the same objective value.

To avoid arbitrary solutions, the optimizer applies secondary objectives as tie-breakers. Examples include:

- Minimizing the maximum grid import/export power (peak leveling).
- Preferring local storage charging over grid export.

These objectives are assigned a much smaller weight than the main cost objective and therefore only influence the solution when multiple schedules have equivalent cost.

The grid peak tie-breaker is computed as `grid_peak_penalty * average_import_price * time_step_duration * grid_peak`. Since the energy-cost term also multiplies power by price per Wh and timestep hours, `grid_peak_penalty` is dimensionless. A value of zero disables this tie-breaker.

## Optimizer Constraints

The objective function must be optimized while satisfying all constraints.

### Energy Balance Constraint

The most important system-level constraint is the energy balance constraint. This constraint ensures that energy is conserved at every timestep and that total power supply always equals total power demand.

In mathematical terms:

$$\sum \text{Source Power}=\sum \text{Load Power}+\sum \text{Storage Power}$$

Note: The Base Load is defined as the residual of total household consumption after subtracting all explicitly modelled devices. This residual definition automatically avoids double counting in the energy balance.

**Reference point.** Storage charge and discharge are separate non-negative decision variables, each measured where the energy leaves its origin: $P_{\text{charge}}$ on the electrical side (the power drawn from the house) and $P_{\text{discharge}}$ on the storage side (the power drawn from the stored energy). The energy balance is on the electrical side, so the Storage Power in the balance is defined as:

$${\text{Storage Power}} = P_{\text{charge}} - \eta_{\mathrm{discharge}} \, P_{\text{discharge}}$$

For thermal storage (DHW tank, building thermal mass), discharge does not return electrical energy to the house, so only $P_{\text{charge}}$ enters the balance.

### Asset Constraints

In addition to the system-level energy balance constraint, each asset contributes its own physical and operational constraints.

Examples include:

- Maximum or discrete charging power
- Maximum or discrete discharging power
- Energy capacity
- Availability windows (charging and discharging are only allowed when the availability window is 1)
- State-of-charge limits
- Minimum active mode power, $P_{\min}^{\mathrm{mode}} = 100\,\mathrm{W}$, for every storage asset

For storage assets, the state of charge must evolve according to the storage dynamics:

$$SOC_{t+1}=
SOC_t+
\frac{\left(P_{\mathrm{charge},t}\eta_{\mathrm{charge}}-P_{\mathrm{discharge},t}-P_{\mathrm{loss},t}\right)\Delta t-\frac{E_{\mathrm{demand},t}}{\eta_{\mathrm{discharge}}}}{C}$$

where:

- $P_{\mathrm{charge}}$ represents charging power [W].
- $P_{\mathrm{discharge}}$ represents discharge power [W] which is controlled by the optimization algorithm.
- $E_{\mathrm{demand}}$ represents the forecasted useful energy demand [Wh] per time step that must be supplied by the storage.
- $\eta_{\mathrm{charge}}$ represents the charging efficiency [-].
- $\eta_{\mathrm{discharge}}$ represents the discharging efficiency [-].
- $P_{\mathrm{loss}}$ represents passive storage losses [W].
- $C$ represents the storage capacity [Wh].
- $\Delta t$ represents the time step duration [h].

This ensures that energy stored in an asset remains physically consistent over time and cannot be created or destroyed.

### Mutual Exclusivity of Charge and Discharge for Storage

Storage assets cannot simultaneously charge and discharge, enforced via the binary variables $c_t, d_t \in \{0, 1\}$ (defined in [Storage Mode Switching Penalty](#storage-mode-switching-penalty)) for charging and discharging respectively, with $c_t + d_t \leq 1$. When both are 0 the storage is idle.

For any modeled charge or discharge mode, the active power must meet the universal minimum, this helps mapping the binary variables correctly:

$$P_{\mathrm{charge},t} \geq P_{\min}^{\mathrm{mode}} c_t, \quad P_{\mathrm{discharge},t} \geq P_{\min}^{\mathrm{mode}} d_t$$

For a `Battery`, the power is continuous:

$$P_{\min}^{\mathrm{mode}} c_t \leq P_{\text{charge},t} \leq P_{\text{charge}}^{\max} c_t, \quad P_{\min}^{\mathrm{mode}} d_t \leq P_{\text{discharge},t} \leq P_{\text{discharge}}^{\max} d_t, \quad c_t + d_t \leq 1$$

where $P_{\text{charge}}^{\max}$ and $P_{\text{discharge}}^{\max}$ are `max_charge_power` and `max_discharge_power`. This reflects the physical constraint of single-direction power converters.

For a `BTM`, the power is discrete (the heat pump is in +dT, -dT or neutral mode). With binary $c_{\text{BTM},t}$ for +dT mode and binary $d_{\text{BTM},t}$ for -dT mode:

$$P_{\text{charge,BTM},t} = P_{\text{charge,BTM}} \cdot c_{\text{BTM},t}, \quad P_{\text{discharge,BTM},t} = P_{\text{discharge,BTM}} \cdot d_{\text{BTM},t}, \quad c_{\text{BTM},t} + d_{\text{BTM},t} \leq 1$$

where $P_{\text{charge,BTM}}$ and $P_{\text{discharge,BTM}}$ are `charge_power` and `discharge_power`; each configured mode power must meet $P_{\min}^{\mathrm{mode}}$. When both binaries are 0 the heat pump runs in neutral mode (default curve).

**Exceptions**:
- Energy demand forecast: Discharging through the energy demand forecast is allowed simultaneously with charging or discharging. 

- Passive discharge (losses): Passive discharge is always allowed simultaneously with charging or discharging.

### Mutual Exclusivity of Charging the DHW Tank and Building Thermal Mass

DHW tank and building thermal mass typically share a single heat pump and cannot both charge simultaneously. This shared resource constraint creates unavoidable mode switches: the optimizer must alternate between charging DHW and precharging BTM based on cost and demand forecasts. The [Storage Mode Switching Penalty](#storage-mode-switching-penalty) can then be tuned to smooth these forced transitions, discouraging unnecessary additional switches within a charging or idle phase.

Binary variables $c_{\text{DHW},t}$ and $c_{\text{BTM},t}$ (the charge binaries from their respective Mutual Exclusivity of Charge and Discharge constraints) enforce:

$$c_{\text{DHW},t} + c_{\text{BTM},t} \leq 1$$

with the discrete charging power defined by:

$$P_{\text{charge,DHW},t} = P_{\text{charge,DHW}} \cdot c_{\text{DHW},t}, \quad P_{\text{charge,BTM},t} = P_{\text{charge,BTM}} \cdot c_{\text{BTM},t}$$

where $P_{\text{charge,DHW}}$ and $P_{\text{charge,BTM}}$ are the `charge_power` attributes of the `DHW` and `BTM` classes.

This models the shared heat pump resource bottleneck and forces the optimizer to prioritize between immediate DHW demand and precharging thermal mass for cost optimization. SoC constraints for both DHW and building thermal mass make sure that additional priority is given to the one that has SoC below minimum. When both DHW and building thermal mass SoC fall below their comfort thresholds simultaneously, DHW priority is enforced by assigning a higher penalty weight to DHW SoC violations than to building thermal mass SoC violations. This reflects how heat pumps typically enforce DHW priority in their firmware.

### Soft Constraints

Some constraints, like minimum and maximum state-of-charge limits, are implemented as soft constraints. Rather than making the optimization problem infeasible, violations are allowed but receive a large penalty cost in the objective function.

This ensures the optimizer always returns the best achievable solution while strongly discouraging constraint violations.

## Optimizer Output

The optimizer returns the optimization result containing the following information:

### Status
The solver status indicating whether an optimal solution was found:
- **Optimal**: A globally optimal solution was found.
- **Feasible**: A feasible solution was found, but optimality was not proven (e.g., time limit reached).
- **Infeasible**: No feasible solution exists for the given constraints.

### Objective Cost
The total cost of the optimal or best-found schedule [price units], representing:

$$\text{Cost} = \sum_{t=0}^{T} (\text{Grid Import Energy}_{t} \times \text{Import Price}_{t} - \text{Grid Export Energy}_{t} \times \text{Export Price}_{t} - \text{Building Thermal Discharge Benefit}_{t}) - \text{Remaining Storage Value}_{T}$$

### Asset Schedules

The optimizer returns a dictionary of assets keyed by asset ID. Each asset contains:

- `setpoint`: The power setpoint for the first time step [W]. This is the value that can be applied immediately and exposed as the Home Assistant entity state.
- `unit`: The unit of the power values, currently `W`.
- `schedule`: The scheduled power for each time step as timestamped `{time, value}` objects, with `time` marking the start of the time step. Timestamps use ISO 8601 with a timezone offset. Values use the sign convention defined for the asset class: grid import is positive and export is negative; storage charging is positive and discharging is negative; controllable load consumption is non-negative.
- `soc_schedule`: For storage assets, timestamped SoC values normalized from 0.0 (empty) to 1.0 (full). Each `time` marks the end of the time step at which the SoC is reached. The current SoC is not included, so the series has one point per time step.

The `setpoint` equals the first value in `schedule`. Home Assistant can expose it as the entity state and copy the schedule data to entity attributes, making it directly usable by chart cards that consume timestamped series.

For each storage asset $s$ at each time step $t$:



Example response:
```json
{
  "status": "Optimal",
  "objective_cost": 0.42,
  "time_step_minutes": 15,
  "assets": {
    "grid_1": {
      "setpoint": 1200.0,
      "unit": "W",
      "schedule": [
        { "time": "2026-10-05T14:00:00+02:00", "value": 1200.0 },
        { "time": "2026-10-05T14:15:00+02:00", "value": 3900.0 },
        { "time": "2026-10-05T14:30:00+02:00", "value": 7400.0 },
        { "time": "2026-10-05T14:45:00+02:00", "value": -300.0 }
      ]
    },
    "home_battery": {
      "setpoint": 2500.0,
      "unit": "W",
      "schedule": [
        { "time": "2026-10-05T14:00:00+02:00", "value": 2500.0 },
        { "time": "2026-10-05T14:15:00+02:00", "value": 2500.0 },
        { "time": "2026-10-05T14:30:00+02:00", "value": 0.0 },
        { "time": "2026-10-05T14:45:00+02:00", "value": -1500.0 }
      ],
      "soc_schedule": [
        { "time": "2026-10-05T14:15:00+02:00", "value": 0.50 },
        { "time": "2026-10-05T14:30:00+02:00", "value": 0.65 },
        { "time": "2026-10-05T14:45:00+02:00", "value": 0.65 },
        { "time": "2026-10-05T15:00:00+02:00", "value": 0.45 }
      ]
    },
    "dishwasher": {
      "setpoint": 1500.0,
      "unit": "W",
      "schedule": [
        { "time": "2026-10-05T14:00:00+02:00", "value": 1500.0 },
        { "time": "2026-10-05T14:15:00+02:00", "value": 1500.0 },
        { "time": "2026-10-05T14:30:00+02:00", "value": 0.0 },
        { "time": "2026-10-05T14:45:00+02:00", "value": 0.0 }
      ]
    }
  }
}
```








# Contents

- [Sign Convention](#sign-convention)
- [Energy Devices Abstraction](#energy-devices-abstraction)
  - [Overview](#overview)
  - [Sources](#sources)
  - [Loads](#loads)
  - [Storage](#storage)
  - [Unified Storage Model](#unified-storage-model)
- [Optimizer](#optimizer)
  - [High Level Process](#high-level-process)
  - [Optimization Objective](#optimization-objective)
  - [Constraints](#constraints)


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

To allow the Energy Management System (EMS) to work independently of specific hardware, all physical devices are mapped onto three generic asset classes:

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

#### State
- Current Power [W]

#### Constraints
- Max Import Power [W] *(Grid only)*
- Max Export Power [W] *(Grid only)*

#### Forecasts (value per time step)
- Power Forecast [W] *(PV only)*
- Import Price Forecast [price/Wh] *(Grid only)*
- Export Price Forecast [price/Wh] *(Grid only)*

## Loads

Loads consume energy within the household.

Typical examples:

- Household electrical demand (total of all devices in home)
- Controllable loads (e.g., washing machine, dishwasher, pool pump)

### Attributes

#### State
- Current Power [W]

#### Constraints
- Controllable [-] *(yes/no)*
- Average Power [W] *(controllable loads only)*
- Energy Demand [Wh] *(controllable loads only)*
- Earliest Start Time [timestamp] *(controllable loads only)*
- Latest Finish Time [timestamp] *(controllable loads only)*

#### Forecasts (value per time step)
- Power Forecast [W] *(household demand only)*

## Storage

Storage assets shift energy through time.

Typical examples:

- Home Battery
- EV Battery
- Domestic Hot Water (DHW) Tank
- Building Thermal Mass

### Attributes

#### State
- Current State of Charge [-] (SoC)

#### Constraints
- Energy Capacity [Wh]
- Max SoC [-]
- Min SoC [-]
- Max Charge Power [W]
- Max Discharge Power [W]
- Charge Efficiency [-]
- Discharge Efficiency [-]
- Passive Discharge Power [W] *(typically DHW storage)*
- Discharge to Electrical Network [-] *(yes/no, yes for electrical storage, no for thermal storage)*

#### Forecasts (value per time step)
- Energy Demand Forecast [Wh] *(typically DHW storage)*
- Charging Window [-] *(1/0 for available/unavailable, typically EV)*

## Unified Storage Model

The storage class aims to provide a unified representation for all types of storage assets, allowing the optimizer to handle them in a consistent manner regardless of their physical implementation.
The attributes of the storage class might make sense for a normal battery, but maybe a bit less for thermal storage like DHW tanks or building thermal mass. Therefore, a conversion layer is required to map the physical input characteristics of thermal storage to the unified storage class attributes.

### Conversion Layer for Home Battery
For a normal home battery, the conversion layer is straightforward as the physical parameters directly map to the unified storage model attributes.

```python
# Physical input parameters:

# Current SoC: 50%
# Battery capacity: 10000 Wh
# Min SoC: 10%
# Max SoC: 90%
# Max charge power: 5000 W
# Max discharge power: 5000 W
# Charge efficiency: 0.95
# Discharge efficiency: 0.95
# Passive discharge power: 0 W (no passive discharge for the battery)

# Resulting storage object:
home_battery = Storage(
    name="Home Battery",
    current_soc=0.5,                                # 50%
    energy_capacity=10000,                          # 10000 Wh
    max_soc=0.9,                                    # Health protection: 90% maximum
    min_soc=0.1,                                    # Health protection: 10% minimum
    max_charge_power=5000,                          # Charger limit
    max_discharge_power=5000,                       # Discharger limit
    charge_efficiency=0.95,                         # One-way efficiency
    discharge_efficiency=0.95,                      # One-way efficiency
    passive_discharge_power=0,                      # No passive discharge for battery
    discharge_to_electrical_network=True,           # Battery can discharge to the electrical network
    energy_demand_forecast=[0, 0, ... 0, 0],        # No specific energy demand forecast for the battery
    charging_window=[1, 1, ... 1, 1],               # Always connected and available
)
```

### Conversion Layer for EV Battery
For an EV battery, the conversion layer maps the physical parameters of the EV battery to the unified storage model attributes. The main difference compared to a home battery is that it has additional physical input parameters to define the energy demand forecast and the charging window.

```python
# Physical input parameters:

# Current SoC: 50%
# Battery capacity: 60000 Wh
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
ev_battery = Storage(
    name="EV Battery",
    current_soc=0.5,                                # 50%
    energy_capacity=60000,                          # 60000 Wh
    max_soc=0.9,                                    # Health protection: 90% maximum
    min_soc=0.1,                                    # Health protection: 10% minimum
    max_charge_power=7400,                          # Charger limit
    max_discharge_power=0,                          # Vehicle to grid capability
    charge_efficiency=0.95,                         # One-way efficiency
    discharge_efficiency=0.95,                      # One-way efficiency
    passive_discharge_power=0,                      # No passive discharge for battery
    discharge_to_electrical_network=True,           # Battery can discharge to the electrical network
    energy_demand_forecast=[0, 20000, ... 0, 0],    # Set based on vehicle efficiency, round trip distance, and expected departure time
    charging_window=[1, 0, ... 0, 1]                # Set based on expected departure and arrival times
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

# Resulting storage object:
dhw_tank = Storage(
    name="DHW Tank",
    current_soc=0.75,                               # (50-20) / (60-20) = 0.75
    energy_capacity=13960,                          # Thermal energy: 300L × 1.163 Wh/(L·K) × (60-20) = 13960 Wh
    max_soc=1,                                      # Up to max temperature    
    min_soc=0.5,                                    # Down to comfort temperature: (40-20) / (60-20) = 0.5
    max_charge_power=3000,                          # Electric power: Heat pump electric power (W)
    max_discharge_power=0,                          # No active discharge (passive loss only)
    charge_efficiency=3,                            # Heat pump COP
    discharge_efficiency=1.0,                       # Assuming ideal efficiency for simplicity
    passive_discharge_power=160,                    # Heat loss at max temp: HLC × ΔT = 4 × (60-20) = 160 W
    discharge_to_electrical_network=False,          # Thermal storage does not discharge to the electrical network
    energy_demand_forecast=[150, 140, ... 180, 0],  # DHW demand forecast (Wh) per time step
    charging_window=[1, 1, ... 1, 1]                # Always connected and available
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
# Heating rate: 0.6 °C/hour (heat pump set +dT w.r.t. default curve)
# Cooldown rate: 0.1 °C/hour (heat pump set -dT w.r.t. default curve)
# Heat pump COP for +dT mode: 2.5
# Heat pump COP for default curve mode: 3

# Resulting storage object:
building_thermal_mass = Storage(
    name="Building Thermal Mass",
    current_soc=0.5,                                # (20.5 - 20) / (21 - 20) = 0.5
    energy_capacity=20000,                          # Thermal energy: 100 m² × 200 Wh/m²/°C × (21 - 20)°C = 20000 Wh
    max_soc=1,                                      # Up to max comfort temperature
    min_soc=0,                                      # Down to default weather compensation temperature
    max_charge_power=4000,                          # Electric power: 20000 Wh / (21 - 20)°C * 0.6 °C/hour / 3 = 4000 W
    max_discharge_power=2000,                       # Thermal power: 20000 Wh / (21 - 20)°C * 0.1 °C/hour = 2000 W
    charge_efficiency=2.5,                          # Heat pump COP for +dT mode
    discharge_efficiency=3,                         # Heat pump COP for default mode
    passive_discharge_power=0,                      # Not relevant for building thermal mass
    discharge_to_electrical_network=False,          # Thermal storage does not discharge to the electrical network
    energy_demand_forecast=[0, 0, ... 0, 0],        # Not relevant for building thermal mass
    charging_window=[1, 1, ... 1, 1]                # Always connected and available
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


But because of our way of implementing the building thermal mass this objective function is not yet complete.

- When the building thermal mass is charged, extra energy is used and thus this is represented in the objective function with: Grid Import Energy x Import Price
- When the building thermal mass is discharged, it allows the building to cool down, which does not directly translate into economic benefits in the objective function as there is no extra energy exported. The economic benefit comes from avoiding the normally required Grid Import Energy at that time.

So by pre-charging the building thermal mass when electricity prices are low, the optimizer can reduce grid import costs during periods of high electricity prices, during discharge of the thermal mass.

To capture this benefit in the objective function, an additional term is introduced: Thermal Storage Benefit.

$$\text{Cost} = \sum_{t=0}^{T} (\text{Grid Import Energy}_{t} \times \text{Import Price}_{t} - \text{Grid Export Energy}_{t} \times \text{Export Price}_{t} - \text{Thermal Storage Benefit}_{t})$$

With the thermal storage benefit being:

$$\text{Thermal Storage Benefit}_{t} = \text{Discharged Thermal Energy}_{t} \times \frac{\eta_{\mathrm{discharge}}}{\eta_{\mathrm{charge}}} \times \text{Import Price}_{t}$$

where:

- $\eta_{\mathrm{discharge}}$ is the thermal storage discharging efficiency, thermal to thermal conversion, which is 1.
- $\eta_{\mathrm{charge}}$ is the thermal storage charging efficiency for the default weather compensation curve (defined by `discharge_efficiency` in the above class example), electrical to thermal conversion.

This term represents the avoided electricity cost obtained by using previously stored thermal energy instead of producing the same heat at the current electricity price.

## Constraints

The objective function must be optimized while satisfying all constraints.

### Energy Balance Constraint

The most important system-level constraint is the energy balance constraint. This constraint ensures that energy is conserved at every timestep and that total power supply always equals total power demand.

In mathematical terms:

$$\sum \text{Source Power}=\sum \text{Load Power}+\sum \text{Storage Power}$$

### Asset Constraints

In addition to the system-level energy balance constraint, each asset contributes its own physical and operational constraints.

Examples include:

- Maximum charging power
- Maximum discharging power
- Energy capacity
- Availability windows
- State-of-charge limits

For storage assets, the state of charge must evolve according to the storage dynamics:

$$
SOC_{t+1}
=
SOC_t
+
\frac{
\left(
P_{\mathrm{charge},t}\eta_{\mathrm{charge}}
-
P_{\mathrm{discharge},t}
-
\frac{P_{\mathrm{demand},t}}{\eta_{\mathrm{discharge}}}
-
P_{\mathrm{loss},t}
\right)\Delta t
}
{C}
$$

where:

- $P_{\mathrm{charge}}$ represents charging power.
- $P_{\mathrm{discharge}}$ represents controlled discharge power.
- $P_{\mathrm{demand}}$ represents the forecasted useful energy demand served by the storage.
- $\eta_{\mathrm{charge}}$ represents the charging efficiency.
- $\eta_{\mathrm{discharge}}$ represents the discharging efficiency.
- $P_{\mathrm{loss}}$ represents passive storage losses.
- $C$ represents the storage capacity.

This ensures that energy stored in an asset remains physically consistent over time and cannot be created or destroyed.

### Soft Constraints

Some constraints, like minimum and maximum state-of-charge limits, are implemented as soft constraints. Rather than making the optimization problem infeasible, violations are allowed but receive a large penalty cost in the objective function.

This ensures the optimizer always returns the best achievable solution while strongly discouraging constraint violations.








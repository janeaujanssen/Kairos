"""Manually checked: Kairos optimizer (see backend_architecture.md, section "Optimizer").

The module follows the structure of the architecture document:

1. Decision variables    - "High Level Process": power setpoints of all controllable assets
2. Objective             - "Optimization Objective": cost, BTM discharge benefit,
                           end-of-horizon value, secondary objectives
3. Constraints           - "Optimizer Constraints": energy balance (+ per-asset constraints)
4. optimize()            - ties the above together and solves the MILP with CBC/PuLP

Sign convention: source power + supply, storage power + charge / - discharge, load power >= 0.
Power is in W, energy in Wh, prices in price/Wh. Energy per step = power * dt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import pulp

from classes import (
    BTM,
    DHW,
    PV,
    BaseLoad,
    Battery,
    ControllableLoad,
    Grid,
    Load,
    Source,
    Storage,
)

# Weight of the peak-leveling tie-breaker relative to the average import price.
PEAK_WEIGHT = 1e-6

Expr = pulp.LpAffineExpression | float


@dataclass
class OptimizationResult:
    """Solver status, total cost and the power schedule per asset, plus SoC for storages."""

    status: str
    objective_cost: float
    schedule: dict[str, list[float]]  # asset id -> power setpoint [W] per step
    storage_soc: dict[str, list[float]]  # asset id -> SoC (State of Charge) [-] per step


# ---------------------------------------------------------------------------
# 1. Decision variables
# ---------------------------------------------------------------------------
@dataclass
class GridModel:
    """Grid import/export variables of the optimization problem."""

    grid: Grid
    import_power: dict[int, pulp.LpVariable]  # W, >= 0
    export_power: dict[int, pulp.LpVariable]  # W, >= 0
    peak: pulp.LpVariable  # max(import, export) over the horizon, for the tie-breaker


@dataclass
class StorageFlows:
    """Per-step flows of one storage asset, defined by its storage class."""

    gain: list[Expr]  # energy added to the store [Wh]
    loss: list[Expr]  # energy removed from the store by discharging [Wh]
    electrical_power: list[Expr]  # + charge / - discharge seen by the electrical network [W]
    setpoint: list[Expr]  # power setpoint reported in the schedule [W]
    discharged_energy: list[Expr] | None = None  # BTM only, for the discharge benefit [Wh]


@dataclass
class StorageModel:
    """A storage asset together with its flows and end-of-horizon energy."""

    storage: Storage
    flows: StorageFlows
    remaining_energy: pulp.LpVariable  # stored energy at the end of the horizon [Wh]
    eta_value: float  # grid Wh that one stored Wh is worth at the end of the horizon
    discharge_benefit: Expr = 0.0  # BTM only: avoided cost of discharging
    stored_energy_per_step: list[pulp.LpVariable] = None  # stored energy [Wh] at end of each step


def add_grid(prob: pulp.LpProblem, grid: Grid, n_steps: int) -> GridModel:
    """Add import/export variables limited by the grid connection, never both in one step."""
    steps = range(n_steps)
    imp = pulp.LpVariable.dicts("grid_import", steps, 0, grid.max_import_power)
    exp = pulp.LpVariable.dicts("grid_export", steps, 0, grid.max_export_power)
    importing = pulp.LpVariable.dicts("grid_importing", steps, cat=pulp.LpBinary)
    peak = pulp.LpVariable("grid_peak", 0)
    for t in steps:
        # No simultaneous import and export.
        prob += imp[t] <= grid.max_import_power * importing[t]
        prob += exp[t] <= grid.max_export_power * (1 - importing[t])
        prob += peak >= imp[t]
        prob += peak >= exp[t]
    return GridModel(grid, imp, exp, peak)


def add_controllable_load(
    prob: pulp.LpProblem, load: ControllableLoad, idx: int, start: datetime, dt: float, n_steps: int
) -> list[Expr]:
    """Run once, uninterrupted, at average power, inside the allowed window."""
    run_steps = math.ceil(load.energy_demand / (load.average_power * dt) - 1e-9)
    first = 0
    if load.earliest_start_time is not None:
        first = max(0, math.ceil(_steps_since(start, load.earliest_start_time, dt) - 1e-9))
    end = n_steps
    if load.latest_finish_time is not None:
        end = min(n_steps, math.floor(_steps_since(start, load.latest_finish_time, dt) + 1e-9))
    start_steps = range(first, end - run_steps + 1)
    if len(start_steps) == 0:
        raise ValueError(f"Load {load.id!r} does not fit in its operating window")

    starts = pulp.LpVariable.dicts(f"load{idx}_start", start_steps, cat=pulp.LpBinary)
    prob += pulp.lpSum(starts.values()) == 1
    return [
        load.average_power * pulp.lpSum(starts[s] for s in start_steps if s <= t < s + run_steps)
        for t in range(n_steps)
    ]


def add_battery(
    prob: pulp.LpProblem, s: Battery, idx: int, avail: list[int], dt: float, n_steps: int
) -> StorageFlows:
    """Continuous charge/discharge, limited by max powers and availability."""
    steps = range(n_steps)
    charge = pulp.LpVariable.dicts(f"s{idx}_charge", steps, 0)
    discharge = pulp.LpVariable.dicts(f"s{idx}_discharge", steps, 0)
    charging = pulp.LpVariable.dicts(f"s{idx}_charging", steps, cat=pulp.LpBinary)
    for t in steps:
        prob += charge[t] <= s.max_charge_power * avail[t] * charging[t]
        prob += discharge[t] <= s.max_discharge_power * avail[t] * (1 - charging[t])
    electrical = [charge[t] - discharge[t] for t in steps]
    return StorageFlows(
        gain=[charge[t] * s.charge_efficiency * dt for t in steps],
        loss=[discharge[t] * dt / s.discharge_efficiency for t in steps],
        electrical_power=electrical,
        setpoint=electrical,
    )


def add_dhw(
    prob: pulp.LpProblem, s: DHW, idx: int, avail: list[int], dt: float, n_steps: int
) -> StorageFlows:
    """Heat pump on/off at a discrete electric power; thermal output only via demand."""
    steps = range(n_steps)
    on = pulp.LpVariable.dicts(f"s{idx}_on", steps, cat=pulp.LpBinary)
    for t in steps:
        prob += on[t] <= avail[t]
    electrical = [s.charge_power * on[t] for t in steps]
    return StorageFlows(
        gain=[s.charge_power * s.charge_efficiency * dt * on[t] for t in steps],
        loss=[0.0] * n_steps,
        electrical_power=electrical,
        setpoint=electrical,
    )


def add_btm(
    prob: pulp.LpProblem, s: BTM, idx: int, avail: list[int], dt: float, n_steps: int
) -> StorageFlows:
    """Three modes per step: +dT (charge), -dT (discharge), neutral. Only +dT draws extra power."""
    steps = range(n_steps)
    plus = pulp.LpVariable.dicts(f"s{idx}_plus_dT", steps, cat=pulp.LpBinary)
    minus = pulp.LpVariable.dicts(f"s{idx}_minus_dT", steps, cat=pulp.LpBinary)
    for t in steps:
        prob += plus[t] + minus[t] <= avail[t]
    return StorageFlows(
        gain=[s.charge_power * s.charge_efficiency * dt * plus[t] for t in steps],
        loss=[s.discharge_power * dt / s.discharge_efficiency * minus[t] for t in steps],
        electrical_power=[s.charge_power * plus[t] for t in steps],
        setpoint=[s.charge_power * plus[t] - s.discharge_power * minus[t] for t in steps],
        discharged_energy=[s.discharge_power * dt * minus[t] for t in steps],
    )


def add_storage(
    prob: pulp.LpProblem, s: Storage, idx: int, dt: float, n_steps: int, import_price: list[float]
) -> StorageModel:
    """Class-specific flows from the add_* functions, shared state-of-charge dynamics here."""
    steps = range(n_steps)
    demand = s.energy_demand_forecast or [0.0] * n_steps
    avail = s.availability_window or [1] * n_steps
    _check_len(f"{s.id} energy_demand_forecast", demand, n_steps)
    _check_len(f"{s.id} availability_window", avail, n_steps)

    discharge_benefit: Expr = 0.0
    if isinstance(s, Battery):
        flows = add_battery(prob, s, idx, avail, dt, n_steps)
        eta_value = s.discharge_efficiency
    elif isinstance(s, DHW):
        flows = add_dhw(prob, s, idx, avail, dt, n_steps)
        eta_value = s.discharge_efficiency / s.charge_efficiency
    elif isinstance(s, BTM):
        flows = add_btm(prob, s, idx, avail, dt, n_steps)
        eta_value = s.discharge_efficiency / s.default_efficiency
        discharge_benefit = building_thermal_discharge_benefit(
            s, flows.discharged_energy, import_price
        )
    else:
        raise TypeError(f"Unsupported storage type: {type(s).__name__}")

    # energy[t+1] = energy[t] + charged - discharged - demand - passive loss
    energy = pulp.LpVariable.dicts(f"s{idx}_energy", range(n_steps + 1), 0, s.energy_capacity)
    prob += energy[0] == s.current_soc * s.energy_capacity
    for t in steps:
        prob += energy[t + 1] == (
            energy[t] + flows.gain[t] - flows.loss[t] - demand[t] - s.passive_discharge_power * dt
        )
        prob += energy[t + 1] >= s.min_soc * s.energy_capacity
        prob += energy[t + 1] <= s.max_soc * s.energy_capacity

    stored_energy_per_step = [energy[t] for t in range(n_steps + 1)]
    return StorageModel(s, flows, energy[n_steps], eta_value, discharge_benefit, stored_energy_per_step)


# ---------------------------------------------------------------------------
# 2. Objective
# ---------------------------------------------------------------------------
def energy_cost(model: GridModel, dt: float) -> Expr:
    """Sum over t of: import energy * import price - export energy * export price."""
    g = model.grid
    return pulp.lpSum(
        model.import_power[t] * dt * g.import_price_forecast[t]
        - model.export_power[t] * dt * g.export_price_forecast[t]
        for t in model.import_power
    )


def building_thermal_discharge_benefit(
    s: BTM, discharged_energy: list[Expr], import_price: list[float]
) -> Expr:
    """Discharged energy * (eta_discharge / eta_default) * import price, summed over t."""
    factor = s.discharge_efficiency / s.default_efficiency
    return pulp.lpSum(e * factor * p for e, p in zip(discharged_energy, import_price))


def remaining_storage_value(models: list[StorageModel], future_price: float) -> Expr:
    """Remaining stored energy * eta_value * future import price."""
    return pulp.lpSum(m.remaining_energy * m.eta_value * future_price for m in models)


def peak_leveling(model: GridModel, future_price: float) -> Expr:
    """Secondary objective: tiny weight, only breaks ties between equal-cost schedules."""
    return PEAK_WEIGHT * max(abs(future_price), 1e-9) * model.peak


# ---------------------------------------------------------------------------
# 3. Constraints
# ---------------------------------------------------------------------------
def add_energy_balance(
    prob: pulp.LpProblem,
    grid: GridModel,
    pv_power: list[float],
    base_load_power: list[float],
    controllable_power: list[Expr],
    storage_power: list[Expr],
) -> None:
    """Sum of source power = sum of load power + sum of storage power, every step."""
    for t in grid.import_power:
        source_power = grid.import_power[t] - grid.export_power[t] + pv_power[t]
        prob += source_power == base_load_power[t] + controllable_power[t] + storage_power[t]


# ---------------------------------------------------------------------------
# 4. Optimizer
# ---------------------------------------------------------------------------
def optimize(
    sources: list[Source],
    loads: list[Load],
    storage: list[Storage],
    start: datetime,
    step_hours: float,
    n_steps: int,
    time_limit_s: int = 60,
) -> OptimizationResult:
    """Build and solve the MILP, returning the cheapest schedule over the horizon."""
    dt = step_hours
    prob = pulp.LpProblem("kairos", pulp.LpMinimize)

    # Fixed inputs: forecasts of grid prices, PV and base load.
    grid = _single_grid(sources)
    _check_len("import_price_forecast", grid.import_price_forecast, n_steps)
    _check_len("export_price_forecast", grid.export_price_forecast, n_steps)
    pv_power = _sum_forecasts([s for s in sources if isinstance(s, PV)], n_steps)
    base_load_power = _sum_forecasts([l for l in loads if isinstance(l, BaseLoad)], n_steps)

    # Decision variables: grid, controllable loads, storage.
    grid_model = add_grid(prob, grid, n_steps)

    schedule: dict[str, list[Expr]] = {
        grid.id: [grid_model.import_power[t] - grid_model.export_power[t] for t in range(n_steps)]
    }
    controllable_power: list[Expr] = [0.0] * n_steps
    controllable = [l for l in loads if isinstance(l, ControllableLoad) and l.energy_demand > 0]
    for i, load in enumerate(controllable):
        power = add_controllable_load(prob, load, i, start, dt, n_steps)
        schedule[load.id] = power
        controllable_power = [a + b for a, b in zip(controllable_power, power)]

    storage_models = [
        add_storage(prob, s, i, dt, n_steps, grid.import_price_forecast)
        for i, s in enumerate(storage)
    ]
    storage_power: list[Expr] = [0.0] * n_steps
    for m in storage_models:
        schedule[m.storage.id] = m.flows.setpoint
        storage_power = [a + b for a, b in zip(storage_power, m.flows.electrical_power)]

    # Constraints.
    add_energy_balance(
        prob, grid_model, pv_power, base_load_power, controllable_power, storage_power
    )

    # Objective: cost - BTM discharge benefit - remaining storage value, plus tie-breaker.
    future_price = sum(grid.import_price_forecast) / n_steps
    cost = (
        energy_cost(grid_model, dt)
        - pulp.lpSum(m.discharge_benefit for m in storage_models)
        - remaining_storage_value(storage_models, future_price)
    )
    prob += cost + peak_leveling(grid_model, future_price)

    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_s))

    status = pulp.LpStatus[prob.status]
    if status == "Infeasible":
        return OptimizationResult("Infeasible", float("nan"), {}, {})
    if status != "Optimal":
        raise RuntimeError(f"Solver ended with status {status!r}")

    storage_soc = {
        m.storage.id: [float(pulp.value(e)) / m.storage.energy_capacity for e in m.stored_energy_per_step]
        for m in storage_models
    }
    return OptimizationResult(
        status="Optimal",
        objective_cost=float(pulp.value(cost)),
        schedule={k: [float(pulp.value(x)) for x in v] for k, v in schedule.items()},
        storage_soc=storage_soc,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _check_len(name: str, values: list, n_steps: int) -> None:
    """Raise if a forecast does not have one value per time step."""
    if len(values) != n_steps:
        raise ValueError(f"{name} has {len(values)} entries, expected {n_steps}")


def _steps_since(start: datetime, t: datetime, dt: float) -> float:
    """Time from start to t, expressed in time steps."""
    return (t - start).total_seconds() / (dt * 3600)


def _single_grid(sources: list[Source]) -> Grid:
    """Return the one Grid source, raising if there is not exactly one."""
    grids = [s for s in sources if isinstance(s, Grid)]
    if len(grids) != 1:
        raise ValueError("Exactly one Grid source is required")
    return grids[0]


def _sum_forecasts(assets: list[PV] | list[BaseLoad], n_steps: int) -> list[float]:
    """Sum the power forecasts of several assets per time step."""
    total = [0.0] * n_steps
    for a in assets:
        _check_len(f"{a.id} power_forecast", a.power_forecast, n_steps)
        total = [x + y for x, y in zip(total, a.power_forecast)]
    return total

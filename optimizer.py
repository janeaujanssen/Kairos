"""
Layer 2: Optimizer Core.

Solves the constrained optimization problem (self-consumption or cost
minimization) over the planning horizon using a Mixed Integer Linear Program,
via PuLP + the CBC solver.

Scope (per architecture doc "start with Grid, PV, Battery and Home Load"):
    Sources : Grid, PV
    Storage : Home Battery
    Loads   : Home Consumption (fixed, uncontrollable)

Energy balance enforced at every timestep t:
    Grid_t + PV_t = Load_t + Battery_t
(with the project's sign convention: Grid/PV positive = supply, Battery
positive = charging, Load always >= 0)

Passive losses (e.g., battery self-discharge, thermal storage heat loss) are
accounted for internally in the SoC dynamics: they reduce the effective
charging/discharging power but do not appear as external demands in the
energy balance.

Soft constraints: the Home Battery's SoC bounds may be violated at a
(large) per-kWh penalty cost rather than making the problem infeasible --
this lets the optimizer always return a best-achievable schedule (e.g. under
a bad forecast) while flagging the violation instead of failing outright.
Grid import/export limits remain hard bounds (physical breaker limits).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pulp

from assets import Source, Storage, Load

VIOLATION_EPS = 1e-6


@dataclass
class Violation:
    asset: str
    type: str
    max_violation: float
    penalty_cost: float


@dataclass
class OptimizationResult:
    status: str = "Not Solved"
    solve_time: float = 0.0
    objective_value: Optional[float] = None

    hours: np.ndarray = field(default_factory=lambda: np.array([]))
    dt_hours: float = 1.0

    grid_import: np.ndarray = field(default_factory=lambda: np.array([]))
    grid_export: np.ndarray = field(default_factory=lambda: np.array([]))
    pv_power: np.ndarray = field(default_factory=lambda: np.array([]))
    load_power: np.ndarray = field(default_factory=lambda: np.array([]))
    
    # Multi-storage support: storages dict {asset_name: {"power": array, "soc": array, "passive_discharge": array}}
    storages: dict = field(default_factory=dict)

    price_import: np.ndarray = field(default_factory=lambda: np.array([]))
    price_export: np.ndarray = field(default_factory=lambda: np.array([]))

    cost_energy: float = 0.0
    cost_penalty: float = 0.0
    cost_total: float = 0.0

    violations: List[Violation] = field(default_factory=list)

    @property
    def is_optimal(self) -> bool:
        return self.status == "Optimal"

    def control_at_t0(self) -> dict:
        """Hardware setpoints to apply for the *next* interval."""
        if not self.storages or len(self.grid_import) == 0:
            return {}
        ctrl = {"grid_import_kw": float(self.grid_import[0]), "grid_export_kw": float(self.grid_export[0])}
        for storage_name, storage_data in self.storages.items():
            ctrl[f"{storage_name.lower().replace(' ', '_')}_power_kw"] = float(storage_data["power"][0])
        return ctrl


class Optimizer:
    """Manages all assets and solves the constrained optimization problem."""

    def __init__(
        self,
        grid: Source,
        pv: Source,
        storages: List[Storage],
        load: Load,
        hours: np.ndarray,
        dt_hours: float,
        mode: str = "cost",  # "cost" | "self_consumption"
        peak_leveling: bool = False,
        charging_priority: bool = False,
        solver_tolerance: float = 1e-9,
        max_iterations: int = 500,
        soft_penalty: float = 1000.0,
    ):
        self.grid = grid
        self.pv = pv
        self.storages = storages  # List of Storage objects
        self.load = load
        self.hours = hours
        self.dt = dt_hours
        self.mode = mode
        self.peak_leveling = peak_leveling
        self.charging_priority = charging_priority
        self.solver_tolerance = solver_tolerance
        self.max_iterations = max_iterations
        self.soft_penalty = soft_penalty

    def solve(self) -> OptimizationResult:
        pv_forecast = np.asarray(self.pv.power_forecast, dtype=float)
        load_forecast = np.asarray(self.load.power_forecast, dtype=float)
        price_import = np.asarray(self.grid.price_forecast, dtype=float)
        price_export = price_import * (self.grid.export_price_fraction or 0.0)
        n = len(load_forecast)
        dt = self.dt

        result = OptimizationResult(hours=self.hours, dt_hours=dt)
        result.pv_power = pv_forecast
        result.load_power = load_forecast
        result.price_import = price_import
        result.price_export = price_export

        prob = pulp.LpProblem("EMS_Optimization", pulp.LpMinimize)

        max_imp = self.grid.max_import_power if self.grid.max_import_power is not None else 1e6
        max_exp = self.grid.max_export_power if self.grid.max_export_power is not None else 1e6

        p_import = [pulp.LpVariable(f"p_import_{t}", lowBound=0, upBound=max_imp) for t in range(n)]
        p_export = [pulp.LpVariable(f"p_export_{t}", lowBound=0, upBound=max_exp) for t in range(n)]
        
        # Multi-storage: power and SoC variables for each storage
        storage_power_dict = {}  # {storage_name: [power_vars]}
        storage_soc_dict = {}    # {storage_name: [soc_vars]}
        storage_slack_low_dict = {}  # {storage_name: [slack_vars]}
        storage_slack_high_dict = {}  # {storage_name: [slack_vars]}
        storage_passive_discharge_dict = {}  # {storage_name: passive_loss_kW}
        
        for storage in self.storages:
            name = storage.name
            storage_power_dict[name] = [
                pulp.LpVariable(
                    f"{name}_power_{t}",
                    lowBound=-storage.max_discharge_power,
                    upBound=storage.max_charge_power,
                )
                for t in range(n)
            ]
            storage_soc_dict[name] = [pulp.LpVariable(f"{name}_soc_{t}", lowBound=0, upBound=1) for t in range(n + 1)]
            storage_slack_low_dict[name] = [pulp.LpVariable(f"{name}_soc_low_slack_{t}", lowBound=0) for t in range(n + 1)]
            storage_slack_high_dict[name] = [pulp.LpVariable(f"{name}_soc_high_slack_{t}", lowBound=0) for t in range(n + 1)]
            
            constraints = storage.get_constraints()
            storage_passive_discharge_dict[name] = constraints.get("passive_discharge_power", 0.0)
            
            # Initial SoC = measured current state
            prob += storage_soc_dict[name][0] == storage.current_soc, f"{name}_initial_soc"
            
            # SoC dynamics for this storage
            passive_loss = storage_passive_discharge_dict[name]
            for t in range(n):
                prob += (
                    storage_soc_dict[name][t + 1] == storage_soc_dict[name][t] + 
                    (storage_power_dict[name][t] - passive_loss) * dt / storage.capacity,
                    f"{name}_soc_dynamics_{t}",
                )
            
            # Soft SoC bounds
            for t in range(n + 1):
                prob += storage_soc_dict[name][t] >= storage.min_soc - storage_slack_low_dict[name][t], f"{name}_soc_min_{t}"
                prob += storage_soc_dict[name][t] <= storage.max_soc + storage_slack_high_dict[name][t], f"{name}_soc_max_{t}"

        # Energy balance: Grid + PV = Load + sum(all storages), at every t
        for t in range(n):
            total_storage_power = pulp.lpSum(storage_power_dict[s.name][t] for s in self.storages)
            prob += (
                (p_import[t] - p_export[t]) + pv_forecast[t] == load_forecast[t] + total_storage_power,
                f"energy_balance_{t}",
            )

        # --- Objective ---
        if self.mode == "self_consumption":
            energy_term = dt * pulp.lpSum(p_import[t] + p_export[t] for t in range(n))
        else:
            energy_term = dt * pulp.lpSum(
                p_import[t] * price_import[t] - p_export[t] * price_export[t] for t in range(n)
            )

        penalty_term = self.soft_penalty * pulp.lpSum(
            storage_slack_low_dict[s.name][t] + storage_slack_high_dict[s.name][t]
            for s in self.storages for t in range(n + 1)
        )

        # Tie-breaking strategies: tiny weight so they never override the primary objective
        eps = 1e-6
        tie_break_term = 0
        peak_var = None
        if self.peak_leveling:
            peak_var = pulp.LpVariable("grid_peak", lowBound=0)
            for t in range(n):
                prob += peak_var >= p_import[t], f"peak_ge_import_{t}"
                prob += peak_var >= p_export[t], f"peak_ge_export_{t}"
            tie_break_term += eps * peak_var
        if self.charging_priority:
            # Small penalty on exporting PV to grid -> optimizer prefers charging storage first
            tie_break_term += eps * dt * pulp.lpSum(p_export[t] for t in range(n))

        prob += energy_term + penalty_term + tie_break_term, "objective"

        solver_options = ["maxN", str(int(self.max_iterations))] if self.max_iterations else []
        try:
            solver = pulp.PULP_CBC_CMD(msg=False, gapRel=self.solver_tolerance, options=solver_options)
            start = time.time()
            prob.solve(solver)
        except Exception:
            # Fall back to default CBC options if the max-iterations flag isn't accepted
            # by this CBC build; gapRel (solver tolerance) is a standard, reliable option.
            solver = pulp.PULP_CBC_CMD(msg=False, gapRel=self.solver_tolerance)
            start = time.time()
            prob.solve(solver)
        result.solve_time = time.time() - start
        result.status = pulp.LpStatus[prob.status]

        def val(var):
            v = var.value()
            return 0.0 if v is None else v

        result.grid_import = np.array([val(v) for v in p_import])
        result.grid_export = np.array([val(v) for v in p_export])
        
        # Multi-storage results
        for storage in self.storages:
            name = storage.name
            result.storages[name] = {
                "power": np.array([val(v) for v in storage_power_dict[name]]),
                "soc": np.array([val(v) for v in storage_soc_dict[name]]),
                "passive_discharge": np.full(n, storage_passive_discharge_dict[name], dtype=float),
            }

        cost_energy = float(
            np.sum(result.grid_import * price_import - result.grid_export * price_export) * dt
        )
        
        total_slack_low = 0.0
        total_slack_high = 0.0
        for storage in self.storages:
            name = storage.name
            slack_low = np.array([val(v) for v in storage_slack_low_dict[name]])
            slack_high = np.array([val(v) for v in storage_slack_high_dict[name]])
            total_slack_low += slack_low.sum()
            total_slack_high += slack_high.sum()
        
        penalty_cost = float(self.soft_penalty * (total_slack_low + total_slack_high))

        result.cost_energy = cost_energy
        result.cost_penalty = penalty_cost
        result.cost_total = cost_energy + penalty_cost
        obj_val = pulp.value(prob.objective)
        result.objective_value = float(obj_val) if obj_val is not None else None

        violations: List[Violation] = []
        for storage in self.storages:
            name = storage.name
            slack_low = np.array([val(v) for v in storage_slack_low_dict[name]])
            slack_high = np.array([val(v) for v in storage_slack_high_dict[name]])
            
            if slack_low.max(initial=0.0) > VIOLATION_EPS:
                violations.append(
                    Violation(
                        asset=name,
                        type="SoC below minimum",
                        max_violation=float(slack_low.max()),
                        penalty_cost=float(self.soft_penalty * slack_low.sum()),
                    )
                )
            if slack_high.max(initial=0.0) > VIOLATION_EPS:
                violations.append(
                    Violation(
                        asset=name,
                        type="SoC above maximum",
                        max_violation=float(slack_high.max()),
                        penalty_cost=float(self.soft_penalty * slack_high.sum()),
                    )
                )
        result.violations = violations

        return result

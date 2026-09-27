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

# Tolerance threshold for detecting constraint violations
# Violations below this threshold are considered negligible numerical noise
VIOLATION_EPS = 1e-6


@dataclass
class Violation:
    """Records when a soft constraint is violated (e.g., SoC exceeds bounds).
    
    Attributes:
        asset: Name of the asset where violation occurred
        type: Description of violation type (e.g., "SoC below minimum")
        max_violation: Maximum violation magnitude across all timesteps
        penalty_cost: Total cost incurred due to this violation
    """
    asset: str
    type: str
    max_violation: float
    penalty_cost: float


@dataclass
class OptimizationResult:
    """Stores the complete optimization solution and metadata.
    
    Attributes:
        status: Solver status ("Optimal", "Not Solved", etc.)
        solve_time: CPU time spent solving the optimization problem (seconds)
        objective_value: The minimized objective value
        
        hours: Time indices for each timestep
        dt_hours: Length of each timestep (hours)
        
        grid_import/export: Power schedule for grid import and export (kW per timestep)
        pv_power: PV generation forecast used in optimization (kW per timestep)
        load_power: Load forecast used in optimization (kW per timestep)
        
        storages: Multi-storage results dict {name: {"power": array (positive=charge),
                                                      "soc": array (0-1),
                                                      "passive_discharge": array}}
        
        price_import/export: Energy prices used in cost calculation (€/kWh)
        
        cost_energy: Total grid energy cost (€)
        cost_penalty: Total cost from constraint violations (€)
        non_electrical_discharge_benefit: Benefit from discharging thermal storage (€)
        cost_total: Total cost = cost_energy + cost_penalty - benefit
        
        *_per_interval: Cost breakdowns for each timestep (for visualization/debugging)
        violations: List of constraint violations that occurred
    """
    status: str = "Not Solved"
    solve_time: float = 0.0
    objective_value: Optional[float] = None

    # Time and timestep information
    hours: np.ndarray = field(default_factory=lambda: np.array([]))
    dt_hours: float = 1.0

    # Power schedules and forecasts
    grid_import: np.ndarray = field(default_factory=lambda: np.array([]))
    grid_export: np.ndarray = field(default_factory=lambda: np.array([]))
    pv_power: np.ndarray = field(default_factory=lambda: np.array([]))
    load_power: np.ndarray = field(default_factory=lambda: np.array([]))
    
    # Multi-storage support: storages dict {asset_name: {"power": array, "soc": array, "passive_discharge": array}}
    storages: dict = field(default_factory=dict)

    # Pricing information
    price_import: np.ndarray = field(default_factory=lambda: np.array([]))
    price_export: np.ndarray = field(default_factory=lambda: np.array([]))

    # Cost components
    cost_energy: float = 0.0
    cost_penalty: float = 0.0
    non_electrical_discharge_benefit: float = 0.0  # Benefit from non-electrical storage discharge (reduces grid heating cost)
    cost_total: float = 0.0
    
    # Per-interval cost breakdowns for visualization and debugging
    cost_energy_per_interval: np.ndarray = field(default_factory=lambda: np.array([]))
    non_electrical_discharge_benefit_per_interval: np.ndarray = field(default_factory=lambda: np.array([]))
    cost_penalty_per_interval: np.ndarray = field(default_factory=lambda: np.array([]))

    # Constraint violations
    violations: List[Violation] = field(default_factory=list)

    @property
    def is_optimal(self) -> bool:
        """Returns True if the solver found an optimal solution."""
        return self.status == "Optimal"

    def control_at_t0(self) -> dict:
        """Extracts hardware setpoints from the first timestep to apply immediately.
        
        Returns:
            Dictionary with keys like 'grid_import_kw', 'grid_export_kw', 
            '{storage_name}_power_kw' containing the power setpoint for the next interval.
        """
        if not self.storages or len(self.grid_import) == 0:
            return {}
        ctrl = {"grid_import_kw": float(self.grid_import[0]), "grid_export_kw": float(self.grid_export[0])}
        for storage_name, storage_data in self.storages.items():
            ctrl[f"{storage_name.lower().replace(' ', '_')}_power_kw"] = float(storage_data["power"][0])
        return ctrl


class Optimizer:
    """Sets up and solves the constrained Mixed Integer Linear Program (MILP) optimization.
    
    The optimizer minimizes total cost (or self-consumption) while respecting:
    - Energy balance (generation = demand + storage changes)
    - Asset power and energy limits
    - Storage state-of-charge (SoC) constraints (soft, with penalty for violations)
    - Grid import/export limits (hard constraints, physical limits)
    
    Multi-storage support: can optimize across battery, EV, building thermal, DHW, etc.
    """

    def __init__(
        self,
        grid: Source,  # Grid asset with import/export prices and limits
        pv: Source,  # PV asset with power forecast
        storages: List[Storage],  # All storage assets (battery, EV, thermal, etc.)
        load: Load,  # Load asset with consumption forecast
        hours: np.ndarray,  # Time index for each timestep
        dt_hours: float,  # Duration of each timestep (hours)
        mode: str = "cost",  # "cost" (minimize €) | "self_consumption" (minimize imports)
        peak_leveling: bool = False,  # Secondary objective: minimize grid peak power
        charging_priority: bool = False,  # Secondary objective: prefer charging storage over exporting PV
        solver_tolerance: float = 1e-9,  # MIP gap tolerance for solver (relative)
        max_iterations: int = 500,  # Maximum solver iterations
        soft_penalty: float = 1000.0,  # Cost penalty per kWh of SoC constraint violation
    ):
        # Store all assets and problem parameters
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
        """Builds and solves the optimization problem.
        
        Returns:
            OptimizationResult with the optimal power schedules, costs, and constraint violations.
        """
        # Extract forecasts and prepare data
        pv_forecast = np.asarray(self.pv.power_forecast, dtype=float)
        load_forecast = np.asarray(self.load.power_forecast, dtype=float)
        price_import = np.asarray(self.grid.price_forecast, dtype=float)
        price_export = price_import * (self.grid.export_price_fraction or 0.0)
        n = len(load_forecast)  # Number of timesteps
        dt = self.dt  # Timestep duration (hours)

        # Initialize result object
        result = OptimizationResult(hours=self.hours, dt_hours=dt)
        result.pv_power = pv_forecast
        result.load_power = load_forecast
        result.price_import = price_import
        result.price_export = price_export

        # Create the MILP problem object (PuLP + CBC solver)
        prob = pulp.LpProblem("EMS_Optimization", pulp.LpMinimize)

        # === DECISION VARIABLES ===
        # Grid power (kW at each timestep)
        max_imp = self.grid.max_import_power if self.grid.max_import_power is not None else 1e6
        max_exp = self.grid.max_export_power if self.grid.max_export_power is not None else 1e6

        # Grid import power for each timestep (non-negative, hard upper bound)
        p_import = [pulp.LpVariable(f"p_import_{t}", lowBound=0, upBound=max_imp) for t in range(n)]
        # Grid export power for each timestep (non-negative, hard upper bound)
        p_export = [pulp.LpVariable(f"p_export_{t}", lowBound=0, upBound=max_exp) for t in range(n)]
        
        # === MULTI-STORAGE DECISION VARIABLES ===
        # For each storage: power (split into separate charge/discharge variables),
        # state-of-charge (SoC), and slack variables for soft constraint violation.
        # Power split: Net power = p_c - p_d where p_c=charge (>=0), p_d=discharge (>=0)
        # Energy stored changes by: p_c * eta_c - p_d (with efficiency losses)
        storage_power_charge_dict = {}  # {storage_name: [p_c_vars]} - charging power for each timestep
        storage_power_discharge_dict = {}  # {storage_name: [p_d_vars]} - discharging power for each timestep
        storage_soc_dict = {}    # {storage_name: [soc_vars]} - state of charge 0-1 (n+1 time points)
        storage_slack_low_dict = {}  # {storage_name: [slack_vars]} - violation of minimum SoC
        storage_slack_high_dict = {}  # {storage_name: [slack_vars]} - violation of maximum SoC
        storage_passive_discharge_dict = {}  # {storage_name: passive_loss_kW} - self-discharge rate
        storage_charge_efficiency_dict = {}  # {storage_name: eta_c} - charging efficiency 0-1
        storage_discharge_efficiency_dict = {}  # {storage_name: eta_d} - discharging efficiency 0-1
        storage_discharge_to_network_dict = {}  # {storage_name: bool} - whether discharge can supply electrical load
        
        # Create variables and constraints for each storage asset
        for storage in self.storages:
            name = storage.name
            constraints = storage.get_constraints()
            
            # Separate charging and discharging power variables (mutual exclusion enforced below)
            # Both are non-negative; net power = charge - discharge
            storage_power_charge_dict[name] = [
                pulp.LpVariable(f"{name}_p_charge_{t}", lowBound=0, upBound=storage.max_charge_power)
                for t in range(n)
            ]
            storage_power_discharge_dict[name] = [
                pulp.LpVariable(f"{name}_p_discharge_{t}", lowBound=0, upBound=storage.max_discharge_power)
                for t in range(n)
            ]
            
            # State of charge variables (normalized 0-1) at each time point (n+1 points)
            storage_soc_dict[name] = [pulp.LpVariable(f"{name}_soc_{t}", lowBound=0, upBound=1) for t in range(n + 1)]
            # Slack variables for soft constraint violations (allow SoC to deviate from bounds with penalty)
            storage_slack_low_dict[name] = [pulp.LpVariable(f"{name}_soc_low_slack_{t}", lowBound=0) for t in range(n + 1)]
            storage_slack_high_dict[name] = [pulp.LpVariable(f"{name}_soc_high_slack_{t}", lowBound=0) for t in range(n + 1)]
            
            # Extract efficiency and constraint parameters for this storage
            storage_passive_discharge_dict[name] = constraints.get("passive_discharge_power", 0.0)
            storage_charge_efficiency_dict[name] = constraints.get("charge_efficiency", 0.95)
            storage_discharge_efficiency_dict[name] = constraints.get("discharge_efficiency", 0.95)
            storage_discharge_to_network_dict[name] = constraints.get("discharge_to_electrical_network", True)
            storage_charging_window = constraints.get("charging_window", None)  # e.g., for EV with charging window
            
            # === MUTUAL EXCLUSIVITY: Charge OR Discharge, not both ===
            # Prevents unphysical energy arbitrage when efficiencies have asymmetry.
            # For each timestep, one of two binary modes holds:
            #   mode=0: charging allowed (p_discharge=0)
            #   mode=1: discharging allowed (p_charge=0)
            storage_mode_vars = [pulp.LpVariable(f"{name}_mode_{t}", cat='Binary') for t in range(n)]
            for t in range(n):
                # If mode=0 (charging): discharge power must be 0
                prob += storage_power_charge_dict[name][t] <= storage.max_charge_power * (1 - storage_mode_vars[t]), f"{name}_charge_if_charging_mode_{t}"
                # If mode=1 (discharging): charge power must be 0 (mode multiplied forces this when mode=0)
                prob += storage_power_discharge_dict[name][t] <= storage.max_discharge_power * storage_mode_vars[t], f"{name}_discharge_if_discharging_mode_{t}"
            
            # === SoC DYNAMICS ===
            # Initial condition: SoC at t=0 equals measured current state
            prob += storage_soc_dict[name][0] == storage.current_soc, f"{name}_initial_soc"
            
            # SoC evolution with efficiency, passive loss, and demand effects:
            # SoC_t+1 = SoC_t + [(p_charge*eta_c - p_discharge - passive_loss - demand) * dt] / capacity
            passive_loss = storage_passive_discharge_dict[name]  # kW (self-discharge rate)
            eta_c = storage_charge_efficiency_dict[name]  # Charging efficiency (0-1)
            demand_power = storage.demand_forecast if storage.demand_forecast is not None else np.zeros(n)  # kW (e.g., DHW demand)
            
            # SoC evolution equation for each timestep
            for t in range(n):
                prob += (
                    storage_soc_dict[name][t + 1] == storage_soc_dict[name][t] + 
                    ((storage_power_charge_dict[name][t] * eta_c - storage_power_discharge_dict[name][t] - passive_loss - demand_power[t]) * dt) / storage.capacity,
                    f"{name}_soc_dynamics_{t}",
                )
            
            # === HARD CONSTRAINT: Demand satisfaction ===
            # Ensure SoC is sufficient to meet demand at each timestep.
            # Prevents optimizer from "overdrawing" storage (demand must have energy available).
            for t in range(n):
                if demand_power[t] > VIOLATION_EPS:  # Only enforce if demand is non-negligible
                    prob += storage_soc_dict[name][t] >= (demand_power[t] * dt / storage.capacity), f"{name}_demand_requirement_{t}"
            
            # === SOFT SoC BOUNDS ===
            # Allow SoC to violate min/max bounds with penalty instead of making problem infeasible.
            # This enables the optimizer to find a feasible solution even under adverse conditions.
            for t in range(n + 1):
                # SoC can drop below min_soc by amount slack_low (violation)
                prob += storage_soc_dict[name][t] >= storage.min_soc - storage_slack_low_dict[name][t], f"{name}_soc_min_{t}"
                # SoC can exceed max_soc by amount slack_high (violation)
                prob += storage_soc_dict[name][t] <= storage.max_soc + storage_slack_high_dict[name][t], f"{name}_soc_max_{t}"
            
            # === TIME-DEPENDENT CONSTRAINTS ===
            # EV charging window: if the EV is not available (plugged in) at this timestep, no power transfer allowed
            if storage_charging_window is not None:
                for t in range(n):
                    if storage_charging_window[t] < 0.5:  # EV not available at this timestep
                        # Force both charge and discharge to zero
                        prob += storage_power_charge_dict[name][t] == 0, f"{name}_window_charge_{t}"
                        prob += storage_power_discharge_dict[name][t] == 0, f"{name}_window_discharge_{t}"
            
            # Note: One-way charger for EV has max_discharge_power=0 (already set in Storage init)


        # === ENERGY BALANCE CONSTRAINT ===
        # At each timestep: Grid Supply + PV Generation = Load Consumption + Storage Charging/Discharging
        # Grid power (p_import - p_export) + PV = Load + Storage net power
        #
        # For storage:
        #   - System supplies p_charge power (charging)
        #   - System receives p_discharge * discharge_efficiency (only if "discharge_to_electrical_network")
        # 
        # Note: Thermal storage (building thermal, DHW) has discharge_to_electrical_network=False,
        #       so its discharge doesn't contribute to energy balance (it's used internally, not exported)
        for t in range(n):
            # Total storage power demand (from system perspective)
            # Positive = system supplies energy (charging), negative = system receives energy (discharging)
            total_storage_system_power = pulp.lpSum(
                storage_power_charge_dict[s.name][t] - (
                    # Only include discharge power for electrical storages (battery, EV)
                    storage_power_discharge_dict[s.name][t] * storage_discharge_efficiency_dict[s.name]
                    if storage_discharge_to_network_dict[s.name]
                    else 0
                )
                for s in self.storages
            )
            # Energy balance equation
            prob += (
                (p_import[t] - p_export[t]) + pv_forecast[t] == load_forecast[t] + total_storage_system_power,
                f"energy_balance_{t}",
            )

        # === OBJECTIVE FUNCTION ===
        # Primary objective: minimize energy cost or self-consumption
        if self.mode == "self_consumption":
            # Minimize total grid import + export (maximize self-consumption)
            energy_term = dt * pulp.lpSum(p_import[t] + p_export[t] for t in range(n))
        else:
            # Minimize total energy cost: import cost - export revenue
            energy_term = dt * pulp.lpSum(
                p_import[t] * price_import[t] - p_export[t] * price_export[t] for t in range(n)
            )

        # Penalty term: cost of soft constraint violations (SoC bound violations)
        penalty_term = self.soft_penalty * pulp.lpSum(
            storage_slack_low_dict[s.name][t] + storage_slack_high_dict[s.name][t]
            for s in self.storages for t in range(n + 1)
        )

        # Secondary objectives (tie-breaking): very small weights so they don't override primary objective
        # These help select between equally-good solutions
        eps = 1e-6
        tie_break_term = 0
        peak_var = None
        if self.peak_leveling:
            # Secondary: minimize grid peak power (smaller bills, less grid stress)
            peak_var = pulp.LpVariable("grid_peak", lowBound=0)
            for t in range(n):
                prob += peak_var >= p_import[t], f"peak_ge_import_{t}"
                prob += peak_var >= p_export[t], f"peak_ge_export_{t}"
            tie_break_term += eps * peak_var
        if self.charging_priority:
            # Secondary: prefer charging storage over exporting PV (reduces grid stress, keeps battery charged)
            tie_break_term += eps * dt * pulp.lpSum(p_export[t] for t in range(n))

        # Non-electrical discharge benefit: cost avoidance from thermal storages
        # When discharging building thermal or DHW (discharge_to_electrical_network=False),
        # the stored heat replaces grid-supplied heating (e.g., via heat pump at high price).
        # Benefit (negative cost) = (discharge_power * efficiency / charge_efficiency) * grid_price
        # This benefit is subtracted from total cost to reward discharging thermal storage at high prices.
        non_electrical_discharge_benefit = dt * pulp.lpSum(
            storage_power_discharge_dict[s.name][t] * storage_discharge_efficiency_dict[s.name] / storage_charge_efficiency_dict[s.name] * price_import[t]
            for s in self.storages if not storage_discharge_to_network_dict[s.name]
            for t in range(n)
        )

        # Total objective to minimize
        prob += energy_term + penalty_term + tie_break_term - non_electrical_discharge_benefit, "objective"

        # === SOLVE THE OPTIMIZATION PROBLEM ===
        # Use CBC (Coin Branch-and-Cut) solver via PuLP, with optional iteration limit
        solver_options = ["maxN", str(int(self.max_iterations))] if self.max_iterations else []
        try:
            solver = pulp.PULP_CBC_CMD(msg=False, gapRel=self.solver_tolerance, options=solver_options)
            start = time.time()
            prob.solve(solver)
        except Exception:
            # Fallback: if max-iterations flag is not recognized, use default CBC (just gapRel tolerance)
            solver = pulp.PULP_CBC_CMD(msg=False, gapRel=self.solver_tolerance)
            start = time.time()
            prob.solve(solver)
        result.solve_time = time.time() - start
        result.status = pulp.LpStatus[prob.status]  # Extract status: "Optimal", "Not Solved", etc.

        # === EXTRACT SOLUTION ===
        # Helper to safely extract variable values (handle None from infeasible/unsolved)
        def val(var):
            v = var.value()
            return 0.0 if v is None else v

        # Extract grid power schedules
        result.grid_import = np.array([val(v) for v in p_import])
        result.grid_export = np.array([val(v) for v in p_export])
        
        # Extract multi-storage results: combine charge/discharge power into net power
        for storage in self.storages:
            name = storage.name
            p_c = np.array([val(v) for v in storage_power_charge_dict[name]])
            p_d = np.array([val(v) for v in storage_power_discharge_dict[name]])
            net_power = p_c - p_d  # positive = charging, negative = discharging
            result.storages[name] = {
                "power": net_power,
                "soc": np.array([val(v) for v in storage_soc_dict[name]]),  # SoC at each time point
                "passive_discharge": np.full(n, storage_passive_discharge_dict[name], dtype=float),  # Constant per interval
            }

        # === COST CALCULATION ===
        # Grid energy cost per interval (€/interval)
        cost_energy_per_interval = (result.grid_import * price_import - result.grid_export * price_export) * dt
        cost_energy = float(np.sum(cost_energy_per_interval))
        
        # Non-electrical discharge benefit: cost avoidance from thermal storage discharge
        # For building thermal and DHW, discharging replaces grid heating, providing benefit at high prices.
        non_electrical_discharge_benefit_per_interval = np.zeros(n, dtype=float)
        non_electrical_discharge_benefit = 0.0
        for storage in self.storages:
            name = storage.name
            if not storage_discharge_to_network_dict[name]:  # Only for thermal storages
                p_d = np.array([val(v) for v in storage_power_discharge_dict[name]])
                eta_d = storage_discharge_efficiency_dict[name]
                eta_c = storage_charge_efficiency_dict[name]
                # Benefit = discharge_power * (efficiency ratio) * grid_price * timestep
                benefit_per_interval = p_d * eta_d / eta_c * price_import * dt
                non_electrical_discharge_benefit_per_interval += benefit_per_interval
                non_electrical_discharge_benefit += np.sum(benefit_per_interval)
        
        # Penalty cost from SoC constraint violations
        total_slack_low = 0.0
        total_slack_high = 0.0
        cost_penalty_per_interval = np.zeros(n, dtype=float)
        for storage in self.storages:
            name = storage.name
            slack_low = np.array([val(v) for v in storage_slack_low_dict[name]])
            slack_high = np.array([val(v) for v in storage_slack_high_dict[name]])
            total_slack_low += slack_low.sum()
            total_slack_high += slack_high.sum()
            # For per-interval penalty, use only the first n elements (one per interval, excluding final SoC point)
            cost_penalty_per_interval += self.soft_penalty * (slack_low[:n] + slack_high[:n])
        
        penalty_cost = float(self.soft_penalty * (total_slack_low + total_slack_high))

        # Store all costs in result
        result.cost_energy = cost_energy
        result.cost_penalty = penalty_cost
        result.non_electrical_discharge_benefit = float(non_electrical_discharge_benefit)
        result.cost_total = cost_energy + penalty_cost - non_electrical_discharge_benefit
        result.cost_energy_per_interval = cost_energy_per_interval
        result.non_electrical_discharge_benefit_per_interval = non_electrical_discharge_benefit_per_interval
        result.cost_penalty_per_interval = cost_penalty_per_interval
        # Extract the objective value from the solver
        obj_val = pulp.value(prob.objective)
        result.objective_value = float(obj_val) if obj_val is not None else None

        # === DETECT CONSTRAINT VIOLATIONS ===
        # Collect all soft constraint violations for reporting and debugging
        violations: List[Violation] = []
        for storage in self.storages:
            name = storage.name
            slack_low = np.array([val(v) for v in storage_slack_low_dict[name]])
            slack_high = np.array([val(v) for v in storage_slack_high_dict[name]])
            
            # Report if SoC dropped below minimum
            if slack_low.max(initial=0.0) > VIOLATION_EPS:
                violations.append(
                    Violation(
                        asset=name,
                        type="SoC below minimum",
                        max_violation=float(slack_low.max()),
                        penalty_cost=float(self.soft_penalty * slack_low.sum()),
                    )
                )
            # Report if SoC exceeded maximum
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

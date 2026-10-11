import inspect
from datetime import datetime, timedelta, timezone

import pulp
import optimizer
from classes import BTM, DHW, BaseLoad, Battery, ControllableLoad, Grid

print(f"optimizer import: OK ({optimizer.__file__})")

assert optimizer._cbc_termination_reason("Stopped on time - objective value 0") == "Time limit reached"
assert optimizer._cbc_termination_reason("Stopped on nodes - objective value 0") == "Node limit reached"
assert optimizer._cbc_termination_reason("Optimal - objective value 0") == "Optimality proven"
assert optimizer._cbc_termination_reason("Optimal (within gap tolerance) - objective value 0") == "Relative MIP gap target reached"
print("CBC termination reasons are recognized: OK")

run_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
started_load = ControllableLoad(
    "started-load",
    "Started load",
    average_power=1000.0,
    energy_demand=3000.0,
    run_started_at=run_start - timedelta(hours=1),
)
continued_run = optimizer.add_controllable_load(
    None,
    started_load,
    0,
    run_start,
    1.0,
    4,
)
assert continued_run == [1000.0, 1000.0, 0.0, 0.0], "an in-progress load run was interrupted"
completed_load = ControllableLoad(
    "completed-load",
    "Completed load",
    average_power=1000.0,
    energy_demand=3000.0,
    run_started_at=run_start - timedelta(hours=4),
)
completed_run = optimizer.add_controllable_load(
    None,
    completed_load,
    0,
    run_start,
    1.0,
    4,
)
assert completed_run == [0.0, 0.0, 0.0, 0.0], "a completed run was scheduled again"
print("Started controllable loads run to completion without restarting: OK")

optimize = getattr(optimizer, "optimize", None)
if optimize is None:
    raise AssertionError("optimize function is missing")
params = inspect.signature(optimize).parameters
print("optimize parameters:", ", ".join(params))
assert "switching_penalty" in params, "switching_penalty parameter is missing from optimize()"
assert params["relative_mip_gap"].default == 0.0, "relative_mip_gap must default to zero"
print("1. switching_penalty: OK")

for name in ("add_battery", "add_dhw", "add_btm"):
    fn = getattr(optimizer, name, None)
    assert fn is not None, f"{name} is missing"
    result_annotation = inspect.signature(fn).return_annotation
    annotation_text = str(result_annotation)
    print(f"{name} return annotation: {annotation_text}")
    assert "StorageFlows" in annotation_text, f"{name} does not return StorageFlows"
    assert hasattr(optimizer, "StorageFlows"), "StorageFlows is missing"
    fields = getattr(optimizer.StorageFlows, "__annotations__", {})
    assert "c_t" in fields and "d_t" in fields, "StorageFlows lacks c_t and/or d_t"
    print(f"{name}: StorageFlows with c_t and d_t: OK")

assert callable(getattr(optimizer, "storage_mode_switching_penalty", None)), "storage_mode_switching_penalty is missing"
print("3. storage_mode_switching_penalty: OK")
assert optimizer._terminal_storage_price(list(range(8, 0, -1))) == 1.5
assert optimizer._terminal_storage_price([3.0, 1.0, 2.0]) == 1.0
print("terminal storage price averages the cheapest quarter: OK")

prob = pulp.LpProblem("minimum_charge_power", pulp.LpMinimize)
battery = Battery(
    id="test-battery",
    name="Test battery",
    current_soc=0.5,
    energy_capacity=1000.0,
    max_charge_power=1000.0,
    max_discharge_power=1000.0,
)
flows = optimizer.add_battery(prob, battery, 0, [1], 1.0, 1)
prob += flows.c_t[0] == 1
prob += flows.gain[0]
prob.solve(pulp.PULP_CBC_CMD(msg=False))
assert pulp.value(flows.gain[0]) >= 100.0, "active charging can fall below 100 W"
print("4. active battery charging has a 100 W minimum: OK")

prob = pulp.LpProblem("minimum_discharge_power", pulp.LpMinimize)
flows = optimizer.add_battery(prob, battery, 0, [1], 1.0, 1)
prob += flows.d_t[0] == 1
prob += flows.loss[0]
prob.solve(pulp.PULP_CBC_CMD(msg=False))
assert pulp.value(flows.loss[0]) >= 100.0, "active discharging can fall below 100 W"
print("5. active battery discharging has a 100 W minimum: OK")

discrete_modes = (
    ("DHW charge", optimizer.add_dhw, DHW("dhw", "DHW", 0.5, 1000.0, charge_power=50.0), "c_t"),
    ("BTM charge", optimizer.add_btm, BTM("btm", "BTM", 0.5, 1000.0, charge_power=50.0, discharge_power=500.0), "c_t"),
    ("BTM discharge", optimizer.add_btm, BTM("btm", "BTM", 0.5, 1000.0, charge_power=500.0, discharge_power=50.0), "d_t"),
)
for name, add_flows, storage, mode_name in discrete_modes:
    prob = pulp.LpProblem(name.replace(" ", "_"), pulp.LpMinimize)
    flows = add_flows(prob, storage, 0, [1], 1.0, 1)
    prob += getattr(flows, mode_name)[0] == 1
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[prob.status] == "Infeasible", f"{name} below 100 W was allowed"
    print(f"{name} below 100 W is rejected: OK")

grid = Grid(
    "grid",
    "Grid",
    max_import_power=10000.0,
    max_export_power=10000.0,
    import_price_forecast=[0.2],
    export_price_forecast=[0.05],
)
base_load = BaseLoad("base", "Base", power_forecast=[0.0])
peak_result = optimizer.optimize(
    [grid],
    [BaseLoad("peak-base", "Peak base", power_forecast=[100.0])],
    [],
    datetime(2026, 1, 1, tzinfo=timezone.utc),
    1.0,
    1,
    relative_mip_gap=0.0,
    switching_penalty=0.0,
    grid_peak_penalty=0.1,
)
assert abs(peak_result.objective_cost - 22.0) < 1e-8, (
    "objective_cost does not include the grid peak tie-breaker"
)
print("objective_cost includes the full optimized objective: OK")

for name, current_soc, minimum, maximum, demand, expected_soc, min_cost in (
    ("below minimum", 0.5, 0.2, 0.9, 400.0, 0.1, 10000.0),
    ("above maximum", 0.8, 0.1, 0.5, 0.0, 0.8, 50000.0),
):
    battery = Battery(
        "soc-test-battery",
        "SoC test battery",
        current_soc=current_soc,
        energy_capacity=1000.0,
        min_soc=minimum,
        max_soc=maximum,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        energy_demand_forecast=[demand],
        availability_window=[0],
        max_charge_power=1000.0,
        max_discharge_power=1000.0,
    )
    result = optimizer.optimize(
        [grid],
        [base_load],
        [battery],
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        1.0,
        1,
        relative_mip_gap=0.0,
        switching_penalty=0.0,
        grid_peak_penalty=0.0,
    )
    assert result.status == "Optimal", f"{name} made the problem infeasible"
    assert result.relative_mip_gap == 0.0
    assert result.termination_reason == "Optimality proven"
    assert abs(result.assets[battery.id]["soc_schedule"][0]["value"] - expected_soc) < 1e-8
    assert result.objective_cost > min_cost, f"{name} was not strongly penalized"
    print(f"SoC {name} is allowed with a strong penalty: OK")

impossible_battery = Battery(
    "impossible-battery",
    "Impossible battery",
    current_soc=0.5,
    energy_capacity=1000.0,
    min_soc=0.2,
    max_soc=0.9,
    energy_demand_forecast=[2000.0],
    availability_window=[0],
    max_charge_power=1000.0,
    max_discharge_power=1000.0,
)
impossible = optimizer.optimize(
    [grid],
    [base_load],
    [impossible_battery],
    datetime(2026, 1, 1, tzinfo=timezone.utc),
    1.0,
    1,
    switching_penalty=0.0,
    grid_peak_penalty=0.0,
)
assert impossible.status == "Infeasible", "physical energy bounds were softened"
print("Physical storage capacity remains a hard bound: OK")

priority_grid = Grid(
    "priority-grid",
    "Priority grid",
    max_import_power=10000.0,
    max_export_power=10000.0,
    import_price_forecast=[0.2],
    export_price_forecast=[0.05],
)
dhw = DHW(
    "priority-dhw",
    "Priority DHW",
    current_soc=0.0,
    energy_capacity=1000.0,
    min_soc=0.5,
    charge_efficiency=1.0,
    discharge_efficiency=1.0,
    charge_power=300.0,
)
btm = BTM(
    "priority-btm",
    "Priority BTM",
    current_soc=0.0,
    energy_capacity=1000.0,
    min_soc=0.5,
    charge_efficiency=1.0,
    discharge_efficiency=1.0,
    charge_power=300.0,
    discharge_power=300.0,
    default_efficiency=1.0,
)
priority = optimizer.optimize(
    [priority_grid],
    [base_load],
    [dhw, btm],
    datetime(2026, 1, 1, tzinfo=timezone.utc),
    1.0,
    1,
    switching_penalty=0.0,
    grid_peak_penalty=0.0,
)
assert priority.assets[dhw.id]["setpoint"] == 300.0
assert priority.assets[btm.id]["setpoint"] == 0.0
print("DHW and BTM charging is mutually exclusive, with DHW priority: OK")

print("All requested checks passed.")

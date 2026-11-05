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
    run_started_at=run_start,
)
completed_run = optimizer.add_controllable_load(
    None,
    completed_load,
    0,
    run_start + timedelta(hours=10),
    1.0,
    4,
)
assert completed_run == [0.0, 0.0, 0.0, 0.0], "a run completed earlier today was scheduled again"
previous_day_load = ControllableLoad(
    "previous-day-load",
    "Previous day load",
    average_power=1000.0,
    energy_demand=3000.0,
    run_started_at=run_start - timedelta(hours=4),
)
previous_day_prob = pulp.LpProblem("previous_day", pulp.LpMinimize)
optimizer.add_controllable_load(previous_day_prob, previous_day_load, 0, run_start, 1.0, 4)
assert len(previous_day_prob.constraints) == 1, "a run that ended on an earlier day was not rescheduled"
crossing_load = ControllableLoad(
    "crossing-load",
    "Crossing load",
    average_power=1000.0,
    energy_demand=3000.0,
    run_started_at=run_start - timedelta(hours=2),
)
crossing_run = optimizer.add_controllable_load(None, crossing_load, 0, run_start, 1.0, 4)
assert crossing_run == [1000.0, 0.0, 0.0, 0.0], "a run from an earlier day still in progress was interrupted"
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
assert pulp.value(flows.loss[0]) >= optimizer.MIN_STORAGE_MODE_POWER, "active discharging can fall below the minimum mode power"
print("5. active battery discharging has the minimum mode power (storage side): OK")

lossy_battery = Battery(
    "lossy-battery",
    "Lossy battery",
    current_soc=0.5,
    energy_capacity=1000.0,
    max_charge_power=1000.0,
    max_discharge_power=1000.0,
    discharge_efficiency=0.9,
)
prob = pulp.LpProblem("discharge_efficiency_split", pulp.LpMinimize)
flows = optimizer.add_battery(prob, lossy_battery, 0, [1], 1.0, 1)
prob += flows.d_t[0] == 1
prob += flows.loss[0]
prob.solve(pulp.PULP_CBC_CMD(msg=False))
assert abs(pulp.value(flows.electrical_power[0]) + 0.9 * optimizer.MIN_STORAGE_MODE_POWER) < 1e-6, "network side must see discharge * discharge_efficiency"
assert abs(pulp.value(flows.loss[0]) - optimizer.MIN_STORAGE_MODE_POWER) < 1e-6, "stored energy must drop by the full discharge"
print("5b. battery discharge: network gets eta * discharge, storage loses full discharge: OK")

discrete_modes = (
    ("DHW charge", optimizer.add_dhw, DHW("dhw", "DHW", 0.5, 1000.0, charge_power=50.0), "c_t"),
    ("BTM charge", optimizer.add_btm, BTM("btm", "BTM", 0.5, 1000.0, charge_power=50.0, discharge_power=500.0, cop_forecast=[3.0]), "c_t"),
    ("BTM discharge", optimizer.add_btm, BTM("btm", "BTM", 0.5, 1000.0, charge_power=500.0, discharge_power=50.0, cop_forecast=[3.0]), "d_t"),
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

assert peak_result.forecasts["grid"]["import_price"][0]["value"] == 200.0
assert abs(peak_result.forecasts["grid"]["export_price"][0]["value"] - 50.0) < 1e-8
assert peak_result.forecasts["peak-base"]["power"][0]["value"] == 100.0
assert peak_result.forecasts["grid"]["import_price"][0]["time"] == "2026-01-01T00:00:00+00:00"
print("forecasts are returned in price/kWh and W: OK")

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
    charge_efficiency=0.0,
    discharge_efficiency=1.0,
    charge_power=300.0,
    discharge_power=300.0,
    cop_forecast=[3.0],
    plus_dt=0.0,
    minus_dt=0.0,
    cop_flow_sensitivity=0.0,
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
assert priority.assets[dhw.id]["power_setpoint"] == 300.0
assert priority.assets[btm.id]["power_setpoint"] == 0.0
print("DHW and BTM charging is mutually exclusive, with DHW priority: OK")

from converter import convert_building_thermal_mass

btm_physical = convert_building_thermal_mass(
    {
        "id": "btm", "name": "BTM", "storage_type": "building_thermal_mass",
        "floor_area": 100.0, "thermal_mass_coefficient": 200.0,
        "min_room_temperature": 15.0, "max_room_temperature": 23.0,
        "indoor_temperature": 20.5, "min_comfort_temperature": 19.0, "max_comfort_temperature": 21.0,
        "heating_rate": 0.03, "cooldown_rate": -0.03,
        "heat_loss_coefficient": 367.0, "outdoor_temperature_forecast": [7.0, 2.0],
        "reference_cop": 3.0, "reference_outdoor_temperature": 7.0, "cop_outdoor_temperature_coefficient": 0.1,
        "plus_dt_flow_offset": 5.0, "minus_dt_flow_offset": -5.0, "cop_flow_temperature_sensitivity": -0.02,
    },
    2,
)
assert btm_physical.energy_capacity == 160000.0
assert btm_physical.charge_power == 600.0 and btm_physical.discharge_power == 600.0
assert btm_physical.passive_discharge_power == [367.0 * 13.5, 367.0 * 18.5]
assert [round(c, 6) for c in btm_physical.cop_forecast] == [3.0, 2.5]
print("BTM physical conversion matches the doc example: OK")

prob = pulp.LpProblem("btm_plus_dt_electrical", pulp.LpMinimize)
btm_flows = optimizer.add_btm(prob, btm_physical, 0, [1, 1], 1.0, 2)
prob += btm_flows.c_t[0] == 1
prob += btm_flows.c_t[1] == 0
prob.solve(pulp.PULP_CBC_CMD(msg=False))
assert abs(pulp.value(btm_flows.electrical_power[0]) - (367.0 * 13.5 + 600.0) / 2.7) < 1e-6, "+dT electric power must be (passive loss + charge) / COP(+dT)"
assert abs(pulp.value(btm_flows.gain[0]) - (367.0 * 13.5 + 600.0)) < 1e-6, "+dT gain must be heat pump thermal output (passive loss + charge)"
print("BTM +dT electric power = (passive loss + thermal charge) / COP_+dT and gain is heat pump thermal output: OK")

prob = pulp.LpProblem("btm_discharge_setpoint", pulp.LpMinimize)
btm_flows = optimizer.add_btm(prob, btm_physical, 0, [1, 1], 1.0, 2)
prob += btm_flows.d_t[0] == 1
prob += btm_flows.d_t[1] == 0
prob.solve(pulp.PULP_CBC_CMD(msg=False))
assert abs(pulp.value(btm_flows.setpoint[0]) - (367.0 * 13.5 - btm_physical.discharge_power) / (3.0 * 1.1)) < 1e-6, "BTM -dT setpoint must be (passive loss - cooldown) / COP(-dT)"
print("BTM -dT setpoint is full heat pump electric power: OK")

prob = pulp.LpProblem("btm_soc_plus_dt", pulp.LpMinimize)
btm_model = optimizer.add_storage(prob, btm_physical, 0, 1.0, 2, 1.0)
prob += btm_model.flows.c_t[0] == 1
prob.solve(pulp.PULP_CBC_CMD(msg=False))
soc_step = pulp.value(btm_model.stored_energy_per_step[1]) - pulp.value(btm_model.stored_energy_per_step[0])
assert abs(soc_step - 600.0) < 1e-6, "BTM SoC in +dT must rise by the thermal charge only, passive loss is covered by the heat pump"
print("BTM SoC in +dT rises by the thermal charge (passive loss excluded): OK")

print("All requested checks passed.")

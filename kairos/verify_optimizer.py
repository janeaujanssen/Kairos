import inspect
import pulp
import optimizer
from classes import BTM, DHW, Battery

print(f"optimizer import: OK ({optimizer.__file__})")

optimize = getattr(optimizer, "optimize", None)
if optimize is None:
    raise AssertionError("optimize function is missing")
params = inspect.signature(optimize).parameters
print("optimize parameters:", ", ".join(params))
assert "switching_penalty" in params, "switching_penalty parameter is missing from optimize()"
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

print("All requested checks passed.")

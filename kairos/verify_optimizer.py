import inspect
import optimizer

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
print("All requested checks passed.")

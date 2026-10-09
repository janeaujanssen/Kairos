"""Pure AI: HTTP API for Kairos, implementing openapi.yaml."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

import converter
import optimizer

app = FastAPI(title="Kairos Energy Optimization API", version="1.0.0")
app.state.latest_optimization = None


def _load_openapi() -> dict[str, Any]:
    """Serve openapi.yaml as the schema so /docs matches the API contract."""
    if app.openapi_schema is None:
        with open(Path(__file__).with_name("openapi.yaml"), encoding="utf-8") as f:
            app.openapi_schema = yaml.safe_load(f)
    return app.openapi_schema


app.openapi = _load_openapi


class OptimizationRequest(BaseModel):
    timestamp: datetime
    time_step_duration_hours: float
    horizon_hours: float
    time_limit_s: int = Field(default=10, ge=1, le=3600)
    switching_penalty: float = Field(default=0.1, ge=0.0)
    grid_peak_penalty: float = Field(
        default=0.1,
        ge=0.0,
        description=(
            "Dimensionless grid peak weight. For example, at 0.40 currency/kWh and 15-minute "
            "steps, a value of 0.1 means the optimizer can accept up to 1 cent higher energy "
            "cost in exchange for a 1 kW lower grid peak. Set to 0 to disable."
        ),
    )
    grid: dict[str, Any]
    pv: list[dict[str, Any]] = []
    base_load: dict[str, Any]
    controllable_loads: list[dict[str, Any]] = []
    storage: list[dict[str, Any]]


class GenericOptimizationRequest(OptimizationRequest):
    """Optimization request whose storage items already use generic parameters."""


class SchedulePoint(BaseModel):
    time: datetime
    value: float


class AssetSchedule(BaseModel):
    setpoint: float
    unit: str
    schedule: list[SchedulePoint]
    soc_schedule: list[SchedulePoint] | None = None


class OptimizationResponse(BaseModel):
    status: str
    objective_cost: float
    time_step_minutes: float
    assets: dict[str, AssetSchedule]


class HealthResponse(BaseModel):
    status: str


class LatestOptimizationResponse(BaseModel):
    request: dict[str, Any]
    response: OptimizationResponse
    completed_at: datetime
    solve_time_seconds: float
    storage_metadata: dict[str, dict[str, float]]


@app.exception_handler(RequestValidationError)
def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """The API contract uses 400 (not FastAPI's default 422) for invalid payloads."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _run(request: OptimizationRequest, storage_converter) -> OptimizationResponse:
    started_at = perf_counter()
    n_steps = round(request.horizon_hours / request.time_step_duration_hours)
    try:
        sources = [converter.convert_grid(request.grid)]
        sources += [converter.convert_pv(p) for p in request.pv]
        loads = [converter.convert_base_load(request.base_load)]
        loads += [converter.convert_controllable_load(l) for l in request.controllable_loads]
        storage = [storage_converter(s, n_steps) for s in request.storage]
        result = optimizer.optimize(
            sources=sources,
            loads=loads,
            storage=storage,
            start=request.timestamp,
            step_hours=request.time_step_duration_hours,
            n_steps=n_steps,
            time_limit_s=request.time_limit_s,
            switching_penalty=request.switching_penalty,
            grid_peak_penalty=request.grid_peak_penalty,
        )
    except KeyError as e:
        raise HTTPException(400, f"Missing field: {e.args[0]}") from e
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e

    response = OptimizationResponse(
        status=result.status,
        objective_cost=result.objective_cost,
        time_step_minutes=result.time_step_minutes,
        assets=result.assets,
    )
    app.state.latest_optimization = {
        "request": jsonable_encoder(request),
        "response": jsonable_encoder(response, exclude_none=True),
        "completed_at": datetime.now().astimezone(),
        "solve_time_seconds": perf_counter() - started_at,
        "storage_metadata": {
            item.id: {
                "energy_capacity": item.energy_capacity,
                "min_soc": item.min_soc,
                "max_soc": item.max_soc,
            }
            for item in storage
        },
    }
    return response


# Plain `def` endpoints run in FastAPI's threadpool, so the solver does not block the event loop.
@app.post("/optimize", response_model=OptimizationResponse, response_model_exclude_none=True)
def run_optimization(request: OptimizationRequest) -> OptimizationResponse:
    """Optimize from device-specific physical storage parameters."""
    return _run(
        request,
        lambda s, n: converter.convert_storage(
            s, request.timestamp, request.time_step_duration_hours, n
        ),
    )


@app.post("/optimize-generic", response_model=OptimizationResponse, response_model_exclude_none=True)
def run_optimization_generic(request: GenericOptimizationRequest) -> OptimizationResponse:
    """Optimize from already converted generic storage parameters."""
    return _run(request, lambda s, _n: converter.convert_generic_storage(s))


@app.get(
    "/optimizations/latest",
    response_model=LatestOptimizationResponse,
    response_model_exclude_none=True,
)
def get_latest_optimization() -> LatestOptimizationResponse:
    """Return the latest completed optimization and its inputs for dashboard display."""
    if app.state.latest_optimization is None:
        raise HTTPException(404, "No optimization has completed yet.")
    return LatestOptimizationResponse(**app.state.latest_optimization)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect the root URL to the interactive API docs."""
    return RedirectResponse("/docs")


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Report that the service is up."""
    return HealthResponse(status="healthy")

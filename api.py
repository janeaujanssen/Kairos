"""HTTP API for Kairos, implementing openapi.yaml."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

import converter
import optimizer

app = FastAPI(title="Kairos Energy Optimization API", version="1.0.0")


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
    grid: dict[str, Any]
    pv: list[dict[str, Any]] = []
    base_load: dict[str, Any]
    controllable_loads: list[dict[str, Any]] = []
    storage: list[dict[str, Any]]


class OptimizationResponse(BaseModel):
    status: str
    objective_cost: float
    schedule: dict[str, list[float]]
    storage_soc: dict[str, list[float]]


class HealthResponse(BaseModel):
    status: str


@app.exception_handler(RequestValidationError)
def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """The API contract uses 400 (not FastAPI's default 422) for invalid payloads."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _run(request: OptimizationRequest, storage_converter) -> OptimizationResponse:
    n_steps = round(request.horizon_hours / request.time_step_duration_hours)
    try:
        sources = [converter.convert_grid(request.grid)]
        sources += [converter.convert_pv(p) for p in request.pv]
        loads = [converter.convert_base_load(request.base_load)]
        loads += [converter.convert_controllable_load(l) for l in request.controllable_loads]
        storage = [storage_converter(s, n_steps) for s in request.storage]
        result = optimizer.optimize(
            sources, loads, storage, request.timestamp, request.time_step_duration_hours, n_steps
        )
    except KeyError as e:
        raise HTTPException(400, f"Missing field: {e.args[0]}") from e
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e

    objective = 0.0 if result.status == "Infeasible" else result.objective_cost
    return OptimizationResponse(
        status=result.status, objective_cost=objective, schedule=result.schedule, storage_soc=result.storage_soc
    )


# Plain `def` endpoints run in FastAPI's threadpool, so the solver does not block the event loop.
@app.post("/optimize", response_model=OptimizationResponse)
def run_optimization(request: OptimizationRequest) -> OptimizationResponse:
    """Optimize from device-specific physical storage parameters."""
    return _run(
        request,
        lambda s, n: converter.convert_storage(
            s, request.timestamp, request.time_step_duration_hours, n
        ),
    )


@app.post("/optimize-generic", response_model=OptimizationResponse)
def run_optimization_generic(request: OptimizationRequest) -> OptimizationResponse:
    """Optimize from already converted generic storage parameters."""
    return _run(request, lambda s, _n: converter.convert_generic_storage(s))


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect the root URL to the interactive API docs."""
    return RedirectResponse("/docs")


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Report that the service is up."""
    return HealthResponse(status="healthy")

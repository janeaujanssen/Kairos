"""
Integration with the external EVCC optimizer (https://github.com/evcc-io/optimizer),
a standalone MILP service for battery/EV charging schedules. Called alongside
(not instead of) the local optimizer, on the *same* forecasts, so results can
be compared.

Field mapping (`time_series`) follows the service's public request schema:
    dt   : seconds per slot
    gt   : home load forecast, Wh per slot   ("Gt" = home profile)
    ft   : PV/solar forecast, Wh per slot    ("Ft" = forecast solar)
    p_N  : grid import tariff, EUR/kWh
    p_E  : feed-in (export) tariff, EUR/kWh
Battery fields (`s_*`) are in Wh, power fields (`c_max`/`d_max`) in W.

This is a best-effort integration against the documented API surface; since
the service is still experimental/evolving, treat non-2xx / connection
errors as "comparison unavailable" rather than a hard failure of the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import requests

from assets import Source, Storage, Load

DEFAULT_EVCC_URL = "http://localhost:7050/optimize/charge-schedule"


class EVCCConnectionError(Exception):
    """Raised when the EVCC optimizer service cannot be reached or errors out."""


@dataclass
class EVCCResult:
    status: str = "unavailable"
    objective_value: Optional[float] = None
    grid_import: np.ndarray = field(default_factory=lambda: np.array([]))  # kW (power per timestep)
    grid_export: np.ndarray = field(default_factory=lambda: np.array([]))  # kW (power per timestep)
    battery_power: np.ndarray = field(default_factory=lambda: np.array([]))  # kW (charge-discharge power)
    battery_soc: np.ndarray = field(default_factory=lambda: np.array([]))  # fraction 0-1, length n
    grid_import_overshoot_kwh: np.ndarray = field(default_factory=lambda: np.array([]))  # kWh above import limit per timestep
    grid_export_overshoot_kwh: np.ndarray = field(default_factory=lambda: np.array([]))  # kWh not exported due to limit per timestep
    flow_direction: np.ndarray = field(default_factory=lambda: np.array([]))  # binary: 1=export, 0=import
    limit_violations: dict = field(default_factory=dict)  # {grid_import_limit_exceeded, grid_export_limit_hit}
    payload: Optional[dict] = None
    raw_response: Optional[dict] = None
    error: Optional[str] = None


def build_payload(
    grid: Source,
    pv: Source,
    battery: Storage,
    load: Load,
    dt_hours: float,
    charge_from_grid: bool = True,
    discharge_to_grid: bool = True,
    prc_p_exc_imp: float = 0.0,
) -> dict:
    """Translate our internal (kW / kWh / hours / fraction) units into the
    EVCC optimizer's (W / Wh / seconds / EUR-per-Wh) request schema."""
    pv_forecast = np.asarray(pv.power_forecast, dtype=float)
    load_forecast = np.asarray(load.power_forecast, dtype=float)
    # Convert price_forecast from EUR/kWh to EUR/Wh (divide by 1000)
    price_import = np.asarray(grid.price_forecast, dtype=float) / 1000.0
    price_export = price_import * (grid.export_price_fraction or 0.0)
    n = len(load_forecast)
    dt_seconds = dt_hours * 3600.0

    capacity_wh = battery.capacity * 1000.0

    payload = {
        "strategy": {
            "charging_strategy": "charge_before_export",
            "discharging_strategy": "discharge_before_import",
        },
        "grid": {
            "p_max_imp": (grid.max_import_power or 0) * 1000.0,
            "p_max_exp": (grid.max_export_power or 0) * 1000.0,
            "prc_p_exc_imp": prc_p_exc_imp,
        },
        "batteries": [
            {
                "charge_from_grid": charge_from_grid,
                "discharge_to_grid": discharge_to_grid,
                "s_capacity": capacity_wh,
                "s_min": battery.min_soc * capacity_wh,
                "s_max": battery.max_soc * capacity_wh,
                "s_initial": battery.current_soc * capacity_wh,
                "p_demand": [0.0] * n,
                "s_goal": [0.0] * n,
                "c_min": 0,
                "c_max": battery.max_charge_power * 1000.0,
                "d_max": battery.max_discharge_power * 1000.0,
                "p_a": 0.0,
                "c_priority": 1,
            }
        ],
        "time_series": {
            "dt": [dt_seconds] * n,
            "gt": (load_forecast * dt_hours * 1000.0).tolist(),
            "ft": (pv_forecast * dt_hours * 1000.0).tolist(),
            "p_N": price_import.tolist(),
            "p_E": price_export.tolist(),
        },
        "eta_c": 0.95,
        "eta_d": 0.95,
    }
    return payload


def run_evcc_optimization(
    grid: Source,
    pv: Source,
    battery: Storage,
    load: Load,
    dt_hours: float,
    base_url: str = DEFAULT_EVCC_URL,
    timeout: float = 15.0,
    prc_p_exc_imp: float = 0.0,
) -> EVCCResult:
    """Call the EVCC optimizer service and parse its response into an EVCCResult.
    Never raises for connectivity/HTTP errors -- returns a result with `.error` set
    so the UI can show a friendly "comparison unavailable" message instead."""
    payload = build_payload(grid, pv, battery, load, dt_hours, prc_p_exc_imp=prc_p_exc_imp)
    capacity_wh = battery.capacity * 1000.0

    try:
        resp = requests.post(base_url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as exc:
        return EVCCResult(status="unavailable", payload=payload, error=f"Could not reach EVCC optimizer: {exc}")
    except ValueError as exc:
        return EVCCResult(status="unavailable", payload=payload, error=f"EVCC optimizer returned invalid JSON: {exc}")
    except Exception as exc:
        return EVCCResult(status="unavailable", payload=payload, error=f"Error parsing EVCC response: {exc}")

    try:
        batt_data = data.get("batteries", [{}])[0]
        # Battery data is in Wh per timestep, convert to kW (power)
        charging_wh = np.asarray(batt_data.get("charging_power", []), dtype=float)
        discharging_wh = np.asarray(batt_data.get("discharging_power", []), dtype=float)
        soc_wh = np.asarray(batt_data.get("state_of_charge", []), dtype=float)

        # Convert Wh/timestep to kW: (Wh / 1000) / dt_hours = kW
        battery_power_kw = (charging_wh - discharging_wh) / 1000.0 / dt_hours
        
        # EVCC returns SoC after each timestep (length n), but we need to include initial SoC at t=0 (length n+1)
        initial_soc_wh = battery.current_soc * capacity_wh
        soc_wh_with_initial = np.concatenate([[initial_soc_wh], soc_wh])
        battery_soc_frac = soc_wh_with_initial / capacity_wh if capacity_wh else np.zeros_like(soc_wh_with_initial)

        # Grid data is in Wh per timestep, convert to kW (power)
        grid_import_wh = np.asarray(data.get("grid_import", []), dtype=float)
        grid_export_wh = np.asarray(data.get("grid_export", []), dtype=float)
        grid_import_overshoot_wh = np.asarray(data.get("grid_import_overshoot", []), dtype=float)
        grid_export_overshoot_wh = np.asarray(data.get("grid_export_overshoot", []), dtype=float)
        
        # Convert Wh/timestep to kW: (Wh / 1000) / dt_hours = kW
        grid_import_kw = grid_import_wh / 1000.0 / dt_hours
        grid_export_kw = grid_export_wh / 1000.0 / dt_hours
        grid_import_overshoot_kwh = grid_import_overshoot_wh / 1000.0
        grid_export_overshoot_kwh = grid_export_overshoot_wh / 1000.0
        flow_direction = np.asarray(data.get("flow_direction", []), dtype=int)

        # Extract limit violations
        limit_violations = data.get("limit_violations", {}) or {}
        limit_violations_dict = {
            "grid_import_limit_exceeded": limit_violations.get("grid_import_limit_exceeded", False),
            "grid_export_limit_hit": limit_violations.get("grid_export_limit_hit", False),
        }

        result = EVCCResult(
            status=data.get("status", "unknown"),
            objective_value=data.get("objective_value"),
            grid_import=grid_import_kw,
            grid_export=grid_export_kw,
            battery_power=battery_power_kw,
            battery_soc=battery_soc_frac,
            grid_import_overshoot_kwh=grid_import_overshoot_kwh,
            grid_export_overshoot_kwh=grid_export_overshoot_kwh,
            flow_direction=flow_direction,
            limit_violations=limit_violations_dict,
            payload=payload,
            raw_response=data,
        )
        return result
    except (KeyError, IndexError, TypeError, ZeroDivisionError) as exc:
        return EVCCResult(status="unavailable", payload=payload, error=f"Unexpected EVCC response shape: {exc}", raw_response=data, limit_violations={"grid_import_limit_exceeded": False, "grid_export_limit_hit": False})

"""
Simulated data generation for Grid price, PV production and Load demand
forecasts. Kept fully separate from the optimizer/asset code so it can later
be swapped out for real forecasts (Home Assistant, weather APIs, tariff
APIs, ...) without touching the rest of the app.
"""

from __future__ import annotations

import numpy as np


def time_axis(horizon_hours: float, interval_minutes: float, start_hour: float = 0.0):
    """
    Build the array of clock hours (float, e.g. 13.5 = 13:30) for each of the
    `n` optimization intervals, where n = horizon_hours * 60 / interval_minutes.
    Each entry represents the *start* of that interval's timestep.

    Returns (hours, dt_hours, n).
    """
    dt_hours = interval_minutes / 60.0
    n = int(round(horizon_hours / dt_hours))
    hours = start_hour + np.arange(n) * dt_hours
    return hours, dt_hours, n


def simulate_grid_price(
    hours: np.ndarray,
    baseline: float = 0.20,
    morning_peak_hour: float = 8.0,
    evening_peak_hour: float = 19.0,
    peak_height: float = 0.15,
    peak_width: float = 1.5,
) -> np.ndarray:
    """
    Dynamic import tariff (EUR/kWh): a flat baseline plus two Gaussian-shaped
    peaks around the given morning/evening hours.
    """
    hod = hours % 24
    morning = peak_height * np.exp(-0.5 * ((hod - morning_peak_hour) / peak_width) ** 2)
    evening = peak_height * np.exp(-0.5 * ((hod - evening_peak_hour) / peak_width) ** 2)
    return baseline + morning + evening


def simulate_pv_production(
    hours: np.ndarray,
    peak_power: float = 5.0,
    sunrise: float = 6.5,
    sunset: float = 20.0,
) -> np.ndarray:
    """Bell curve peaking at solar noon, zero outside [sunrise, sunset] (kW)."""
    hod = hours % 24
    solar_noon = (sunrise + sunset) / 2.0
    width = max((sunset - sunrise) / 4.0, 1e-6)
    production = peak_power * np.exp(-0.5 * ((hod - solar_noon) / width) ** 2)
    return np.where((hod >= sunrise) & (hod <= sunset), production, 0.0)


def simulate_load_demand(
    hours: np.ndarray,
    baseline: float = 0.4,
    morning_peak_hour: float = 7.0,
    evening_peak_hour: float = 19.0,
    peak_height: float = 1.2,
    peak_width: float = 1.0,
) -> np.ndarray:
    """Baseline home consumption plus morning/evening peaks (kW)."""
    hod = hours % 24
    morning = peak_height * np.exp(-0.5 * ((hod - morning_peak_hour) / peak_width) ** 2)
    evening = 1.3 * peak_height * np.exp(-0.5 * ((hod - evening_peak_hour) / peak_width) ** 2)
    return baseline + morning + evening


def with_measured_start(forecast: np.ndarray, measured_current_value: float) -> np.ndarray:
    """
    Per the design note: at t=0 the optimizer should use the *measured*
    current value rather than the simulated forecast; t>0 stays forecast-driven.
    Returns a copy with index 0 overridden.
    """
    out = np.array(forecast, dtype=float, copy=True)
    if len(out) > 0:
        out[0] = measured_current_value
    return out

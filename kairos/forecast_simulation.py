"""Manually checked: Forecast simulation functions to generate time-series from input parameters. Only forecast functions for grid, PV and base load are included here, for EV and DHW forecasts converter.py functions can be used."""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta


def grid_price_forecast(
    hours: list[float],
    baseline_price: float,
    morning_peak_time: time,
    evening_peak_time: time,
    morning_peak_price: float,
    evening_peak_price: float,
    export_fraction: float = 0.4,
) -> tuple[list[float], list[float]]:
    """
    Generate import and export price forecasts.
    
    Args:
        hours: Hour of day for each timestep (0-24)
        baseline_price: Base price [price/Wh]
        morning_peak_time: Time of morning peak (e.g., time(7, 0))
        evening_peak_time: Time of evening peak (e.g., time(19, 0))
        morning_peak_price: Price at morning peak [price/Wh]
        evening_peak_price: Price at evening peak [price/Wh]
        export_fraction: Export price as fraction of import price (0-1)
    
    Returns:
        Tuple of (import_prices, export_prices) as lists
    """
    morning_h = morning_peak_time.hour + morning_peak_time.minute / 60
    evening_h = evening_peak_time.hour + evening_peak_time.minute / 60
    
    import_prices = []
    for h in hours:
        if abs(h - morning_h) < 3:
            price = baseline_price + (morning_peak_price - baseline_price) * math.exp(-((h - morning_h) ** 2) / 2)
        elif abs(h - evening_h) < 3:
            price = baseline_price + (evening_peak_price - baseline_price) * math.exp(-((h - evening_h) ** 2) / 2)
        else:
            price = baseline_price
        import_prices.append(max(0, price))
    
    export_prices = [p * export_fraction for p in import_prices]
    return import_prices, export_prices


def pv_power_forecast(
    hours: list[float],
    peak_power: float,
    sunrise: float = 6.0,
    sunset: float = 18.0,
) -> list[float]:
    """
    Generate PV production forecast with bell curve peaking at solar noon.
    
    Args:
        hours: Hour of day for each timestep (0-24)
        peak_power: Maximum production power [W]
        sunrise: Hour of sunrise (default 6)
        sunset: Hour of sunset (default 18)
    
    Returns:
        Power forecast [W] per timestep
    """
    solar_noon = (sunrise + sunset) / 2
    forecast = []
    for h in hours:
        if sunrise <= h <= sunset:
            power = peak_power * math.sin(math.pi * (h - sunrise) / (sunset - sunrise))
        else:
            power = 0.0
        forecast.append(max(0, power))
    return forecast


def base_load_forecast(
    hours: list[float],
    baseline_consumption: float,
    morning_peak_time: time,
    evening_peak_time: time,
    morning_peak_power: float,
    evening_peak_power: float,
) -> list[float]:
    """
    Generate base load forecast with morning and evening peaks.
    
    Args:
        hours: Hour of day for each timestep (0-24)
        baseline_consumption: Baseline power [W]
        morning_peak_time: Time of morning peak (e.g., time(7, 30))
        evening_peak_time: Time of evening peak (e.g., time(19, 0))
        morning_peak_power: Peak power during morning [W]
        evening_peak_power: Peak power during evening [W]
    
    Returns:
        Power forecast [W] per timestep
    """
    morning_h = morning_peak_time.hour + morning_peak_time.minute / 60
    evening_h = evening_peak_time.hour + evening_peak_time.minute / 60
    
    forecast = []
    for h in hours:
        morning_contrib = (morning_peak_power - baseline_consumption) * math.exp(-((h - morning_h) ** 2) / 2)
        evening_contrib = (evening_peak_power - baseline_consumption) * math.exp(-((h - evening_h) ** 2) / 3)
        power = baseline_consumption + morning_contrib + evening_contrib
        forecast.append(max(0, power))
    return forecast

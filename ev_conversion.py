"""
EV Battery Trip Plan Conversion.

This module converts user-friendly EV trip plans (distance, efficiency, safety buffer)
into optimizer-compatible discharge demand forecasts.

A trip plan specifies:
  - When the EV departs (and optionally returns)
  - How much distance will be traveled
  - Vehicle efficiency
  - Safety buffer for detours/weather

The conversion calculates total energy needed (distance / efficiency + buffer) and
creates a discharge_demand_forecast time-series with a spike at departure time.
The optimizer then ensures SoC >= energy_needed / capacity using the existing
discharge_demand_forecast constraint (same as DHW tank).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class EVTripPlan:
    """User-friendly EV trip definition."""
    departure_hour: float           # When EV leaves (0-24, e.g., 9.0 for 9 AM)
    round_trip_km: float            # Total distance in km
    efficiency_km_per_kwh: float    # Vehicle efficiency (e.g., 5.0 km/kWh)
    safety_buffer_kwh: float        # Extra buffer for detours/weather (kWh)


def calculate_trip_energy_required(trip: EVTripPlan) -> float:
    """
    Calculate total energy needed for a trip.
    
    Args:
        trip: Trip plan with distance, efficiency, and safety buffer
        
    Returns:
        Energy required in kWh = (distance / efficiency) + buffer
    """
    return (trip.round_trip_km / trip.efficiency_km_per_kwh) + trip.safety_buffer_kwh


def trip_to_discharge_demand_forecast(
    trip: EVTripPlan,
    hours: np.ndarray,
) -> np.ndarray:
    """
    Convert a single trip plan to discharge_demand_forecast time-series.
    
    Creates an array with energy spike at departure time, zero elsewhere.
    The optimizer uses existing discharge_demand_forecast constraint:
    SoC[departure_timestep] >= energy_required / capacity
    
    Args:
        trip: Trip plan specification
        hours: Time axis array (hours, float)
        
    Returns:
        discharge_demand_forecast array (same length as hours)
        Energy spike at departure timestep, zero elsewhere
    """
    energy_needed = calculate_trip_energy_required(trip)
    
    # Find timestep index closest to departure_hour
    # Handle wrap-around (e.g., departure at 9 AM in 24-hour cycle)
    hod = hours % 24  # hours of day
    departure_idx = np.argmin(np.abs(hod - (trip.departure_hour % 24)))
    
    # Create demand forecast with spike at departure
    demand = np.zeros(len(hours))
    demand[departure_idx] = energy_needed
    
    return demand


def simulate_ev_charging_window(
    hours: np.ndarray,
    arrival_hour: float,
    departure_hour: float,
) -> np.ndarray:
    """
    Binary array indicating when EV is available for charging.
    
    Returns 1.0 when EV is plugged in at home (between arrival and departure),
    0.0 otherwise. Handles wrap-around (e.g., arrives 18:00, leaves 09:00 next day).
    
    Args:
        hours: Time axis array (hours, float)
        arrival_hour: When EV arrives home (0-24)
        departure_hour: When EV leaves home (0-24)
        
    Returns:
        Binary array: 1.0 when available, 0.0 when not
    """
    hod = hours % 24
    arrival = arrival_hour % 24
    departure = departure_hour % 24
    
    if arrival <= departure:
        # Normal case: e.g., arrives 17:00, leaves 09:00 → Not available
        # availability is between arrival and departure times
        availability = np.where((hod >= arrival) & (hod < departure), 1.0, 0.0)
    else:
        # Wrap-around case: e.g., arrives 22:00, leaves 08:00 next day
        # availability wraps around midnight
        availability = np.where((hod >= arrival) | (hod < departure), 1.0, 0.0)
    
    return availability


def validate_trip_plan(trip: EVTripPlan) -> None:
    """
    Validate trip plan parameters.
    
    Args:
        trip: Trip plan to validate
        
    Raises:
        ValueError: If any parameter is invalid
    """
    if not (0 <= trip.departure_hour < 24):
        raise ValueError(f"departure_hour must be 0-24, got {trip.departure_hour}")
    if trip.round_trip_km <= 0:
        raise ValueError(f"round_trip_km must be positive, got {trip.round_trip_km}")
    if trip.efficiency_km_per_kwh <= 0:
        raise ValueError(f"efficiency_km_per_kwh must be positive, got {trip.efficiency_km_per_kwh}")
    if trip.safety_buffer_kwh < 0:
        raise ValueError(f"safety_buffer_kwh must be non-negative, got {trip.safety_buffer_kwh}")


def validate_charging_window(window: EVChargingWindow) -> None:
    """
    Validate EV charging window parameters.
    
    Args:
        window: Charging window to validate
        
    Raises:
        ValueError: If any parameter is invalid
    """
    if not (0 <= window.arrival_hour < 24):
        raise ValueError(f"arrival_hour must be 0-24, got {window.arrival_hour}")
    if not (0 <= window.departure_hour < 24):
        raise ValueError(f"departure_hour must be 0-24, got {window.departure_hour}")
    if window.capacity_kwh <= 0:
        raise ValueError(f"capacity_kwh must be positive, got {window.capacity_kwh}")
    if not (0 <= window.current_soc_percent <= 100):
        raise ValueError(f"current_soc_percent must be 0-100, got {window.current_soc_percent}")
    if not (0 < window.charge_efficiency <= 1):
        raise ValueError(f"charge_efficiency must be 0-1, got {window.charge_efficiency}")
    if window.max_charge_power <= 0:
        raise ValueError(f"max_charge_power must be positive, got {window.max_charge_power}")

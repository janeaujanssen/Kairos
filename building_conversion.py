"""
Building Thermal Mass Conversion.

This module converts physical building parameters (thermal capacitance, time constant,
current temperature) into optimizer-compatible battery-like state, constraints, and
control parameters.

A building is modeled as thermal energy storage:
- State of Charge (SoC) derived from indoor temperature relative to baseline/comfort range
- Capacity from thermal capacitance and comfort temperature band
- Charging via active pre-heating (raising weather compensation curve)
- Discharging via passive cooling (natural heat loss back to baseline, or lowering curve)
- Zero passive discharge power (baseline heating curve maintains the baseline temperature)

The optimizer then schedules when to pre-heat or allow cooling based on prices and solar.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BuildingThermalParams:
    """Physical thermal properties of a building."""
    thermal_capacitance_kwh_per_k: float    # Energy per 1K temperature rise (e.g., 25 kWh/K)
    time_constant_hours: float              # Hours to cool by 1K when heating is off (e.g., 8 h)
    baseline_temp_celsius: float            # Baseline setpoint maintained by weather curve (e.g., 20°C)
    max_comfort_temp_celsius: float         # Maximum comfort temperature (e.g., 21°C)
    current_indoor_temp_celsius: float      # Measured indoor temperature at t=0


def convert_building_params(params: BuildingThermalParams) -> dict:
    """
    Convert physical building parameters to optimizer battery-equivalent values.
    
    Args:
        params: Physical building thermal parameters
        
    Returns:
        Dictionary with battery-equivalent state and constraints:
        - current_soc: Normalized temperature (0-1)
        - capacity: Usable thermal energy storage (kWh)
        - min_soc / max_soc: SoC limits (0 to 1)
        - max_discharge_power: Passive cooling rate (kW)
        - passive_discharge_power: Zero (baseline curve maintains baseline)
        
    Note: max_charge_power is configured separately in the UI (editable by user)
          since it depends on the specific heat pump installation.
    """
    # Validate input ranges
    if params.thermal_capacitance_kwh_per_k <= 0:
        raise ValueError("Thermal capacitance must be positive")
    if params.time_constant_hours <= 0:
        raise ValueError("Time constant must be positive")
    if params.baseline_temp_celsius >= params.max_comfort_temp_celsius:
        raise ValueError("Baseline temp must be lower than max comfort temp")
    if params.current_indoor_temp_celsius < params.baseline_temp_celsius:
        raise ValueError("Current indoor temp must be >= baseline temp")
    if params.current_indoor_temp_celsius > params.max_comfort_temp_celsius:
        raise ValueError("Current indoor temp must be <= max comfort temp")
    
    # Calculate SoC: normalized temperature between baseline and comfort
    temp_range = params.max_comfort_temp_celsius - params.baseline_temp_celsius
    current_soc = (params.current_indoor_temp_celsius - params.baseline_temp_celsius) / temp_range
    
    # Capacity: thermal energy to raise building from baseline to comfort
    capacity = params.thermal_capacitance_kwh_per_k * temp_range
    
    # Max discharge power: passive cooling rate = capacity / time_constant
    # This is the rate at which stored energy decays back to baseline when heating is off
    max_discharge_power = capacity / params.time_constant_hours
    
    return {
        "current_soc": current_soc,
        "capacity": capacity,
        "min_soc": 0.0,                    # Allow full discharge to baseline
        "max_soc": 1.0,                    # Allow full charge to comfort limit
        "max_discharge_power": max_discharge_power,
        "passive_discharge_power": 0.0,    # Zero: baseline curve handles baseline losses
        "discharge_to_electrical_network": False,  # Thermal discharge stays internal to building
    }

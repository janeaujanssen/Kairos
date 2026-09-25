"""
DHW Tank (Domestic Hot Water) Physical-to-Battery Parameter Conversion.

This module provides functions to convert physical DHW tank parameters
(volume, temperature range, heat loss coefficient) to equivalent battery
storage parameters (SoC, capacity, passive discharge power) that can be
used directly with the Storage asset class.

The conversion treats the DHW tank as a virtual thermal energy storage
with the same interface as electrical batteries, enabling the optimizer
to manage thermal energy alongside electrical storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DHWPhysicalParams:
    """Physical parameters of a DHW tank."""
    volume_liters: float              # Tank volume in liters
    min_temp_celsius: float           # Minimum temperature (ambient, typically 20°C)
    max_temp_celsius: float           # Maximum safe water temperature (typically 60°C)
    current_temp_celsius: float       # Current measured water temperature
    heat_loss_coeff_kw_per_k: float   # Heat loss coefficient in kW/K
    min_comfort_temp_celsius: float   # Minimum comfort temperature for showers (e.g., 40°C)
    max_charge_power_kw: float        # Maximum heat pump power (kW)
    heat_pump_cop: float = 1.0        # Coefficient of Performance (heat output / electrical input)


@dataclass
class DHWEquivalentBatteryParams:
    """Equivalent battery storage parameters for the DHW tank."""
    current_soc: float                # State of Charge (0-1)
    capacity_kwh: float               # Energy capacity in kWh
    min_soc: float                    # Minimum SoC (0-1)
    max_soc: float                    # Maximum SoC (0-1)
    max_charge_power_kw: float        # Max charging power (kW)
    max_discharge_power_kw: float     # Max discharging power (kW) = 0 for DHW
    passive_discharge_power_kw: float # Heat loss power at current temperature (kW)
    charge_efficiency: float          # Heat pump COP (converted to battery efficiency)
    discharge_efficiency: float       # Always 1.0 (no active discharge)
    discharge_to_electrical_network: bool = False  # Thermal discharge stays internal (DHW heating)


def convert_dhw_params(physical: DHWPhysicalParams) -> DHWEquivalentBatteryParams:
    """
    Convert DHW tank physical parameters to equivalent battery storage parameters.
    
    Treats the tank as virtual thermal energy storage using the same Storage
    interface as electrical batteries. All calculations follow the architecture
    documentation.
    
    Args:
        physical: DHW tank physical parameters
        
    Returns:
        Equivalent battery storage parameters suitable for the Storage asset class
        
    Raises:
        ValueError: If physical parameters are invalid
    """
    # Validate inputs
    if physical.volume_liters <= 0:
        raise ValueError("Tank volume must be positive")
    if physical.max_temp_celsius <= physical.min_temp_celsius:
        raise ValueError("Max temperature must be greater than min temperature")
    if not (physical.min_temp_celsius <= physical.current_temp_celsius <= physical.max_temp_celsius):
        raise ValueError("Current temperature must be between min and max temperatures")
    if physical.heat_loss_coeff_kw_per_k < 0:
        raise ValueError("Heat loss coefficient must be non-negative")
    if not (physical.min_temp_celsius <= physical.min_comfort_temp_celsius <= physical.max_temp_celsius):
        raise ValueError("Comfort temperature must be between min and max temperatures")
    if physical.max_charge_power_kw < 0:
        raise ValueError("Max charge power must be non-negative")
    
    # --- Calculate State of Charge (SoC) ---
    # SoC represents the fraction of stored thermal energy relative to capacity
    temp_range = physical.max_temp_celsius - physical.min_temp_celsius
    current_soc = (physical.current_temp_celsius - physical.min_temp_celsius) / temp_range
    
    # --- Calculate Energy Capacity ---
    # Capacity = Volume × Specific Heat of Water × Temperature Range
    # Specific heat of water = 1.163 Wh/(liter·K)
    # Result in kWh
    WATER_SPECIFIC_HEAT_WH_PER_LITER_K = 1.163
    capacity_kwh = (
        physical.volume_liters 
        * WATER_SPECIFIC_HEAT_WH_PER_LITER_K 
        * temp_range 
        / 1000.0  # Convert from Wh to kWh
    )
    
    # --- Calculate Minimum SoC (Comfort Constraint) ---
    # Ensures minimum comfort temperature is always available
    comfort_range = physical.min_comfort_temp_celsius - physical.min_temp_celsius
    min_soc = comfort_range / temp_range
    
    # --- Maximum SoC ---
    # Can heat up to the maximum safe temperature
    max_soc = 1.0
    
    # --- Charging and Discharging Power ---
    # Active charging: limited by heat pump power
    max_charge_power = physical.max_charge_power_kw
    
    # Active discharging: not supported for DHW (no active drain)
    # Tank loses heat passively only
    max_discharge_power = 0.0
    
    # --- Passive Discharge (Heat Loss) ---
    # Heat naturally flows out through tank insulation
    # Q_loss = HLC × (T_water - T_ambient)
    # At current temperature:
    temp_diff_current = physical.current_temp_celsius - physical.min_temp_celsius
    passive_discharge_power = physical.heat_loss_coeff_kw_per_k * temp_diff_current
    
    return DHWEquivalentBatteryParams(
        current_soc=current_soc,
        capacity_kwh=capacity_kwh,
        min_soc=min_soc,
        max_soc=max_soc,
        max_charge_power_kw=max_charge_power,
        max_discharge_power_kw=max_discharge_power,
        passive_discharge_power_kw=passive_discharge_power,
        charge_efficiency=physical.heat_pump_cop,
        discharge_efficiency=1.0,
    )

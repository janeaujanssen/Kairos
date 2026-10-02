from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Sign convention: sources +supply/-absorb, storage +charge/-discharge, loads >= 0.


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
@dataclass
class Source:
    id: str
    name: str
    current_power: float = 0.0  # W


@dataclass
class Grid(Source):
    max_import_power: float = 0.0  # W
    max_export_power: float = 0.0  # W
    import_price_forecast: list[float] = field(default_factory=list)  # price/Wh per step
    export_price_forecast: list[float] = field(default_factory=list)  # price/Wh per step


@dataclass
class PV(Source):
    power_forecast: list[float] = field(default_factory=list)  # W per step


# ---------------------------------------------------------------------------
# Loads
# ---------------------------------------------------------------------------
@dataclass
class Load:
    id: str
    name: str
    current_power: float = 0.0  # W
    controllable: bool = False


@dataclass
class BaseLoad(Load):
    power_forecast: list[float] = field(default_factory=list)  # W per step
    controllable: bool = False


@dataclass
class ControllableLoad(Load):
    average_power: float = 0.0  # W
    energy_demand: float = 0.0  # Wh
    earliest_start_time: datetime | None = None
    latest_finish_time: datetime | None = None
    controllable: bool = True


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
@dataclass
class Storage:
    id: str
    name: str
    current_soc: float  # [-]
    energy_capacity: float  # Wh
    max_soc: float = 1.0
    min_soc: float = 0.0
    charge_efficiency: float = 1.0
    discharge_efficiency: float = 1.0
    passive_discharge_power: float = 0.0  # W
    discharge_to_electrical_network: bool = False
    energy_demand_forecast: list[float] = field(default_factory=list)  # Wh per step
    availability_window: list[int] = field(default_factory=list)  # 1/0 per step


@dataclass
class Battery(Storage):
    max_charge_power: float = 0.0  # W
    max_discharge_power: float = 0.0  # W
    discharge_to_electrical_network: bool = True


@dataclass
class DHW(Storage):
    charge_power: float = 0.0  # W, discrete electric power of the heat pump


@dataclass
class BTM(Storage):
    charge_power: float = 0.0  # W, discrete electric power in +dT mode
    discharge_power: float = 0.0  # W, discrete thermal power in -dT mode
    default_efficiency: float = 1.0  # heat pump COP in default curve mode

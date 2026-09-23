"""
Layer 1: Abstraction Layer - Asset classes.

All energy assets inherit from a common `Asset` base class exposing a uniform
interface (get_state / get_constraints / get_forecast / get_control), so the
Optimizer can work with any asset type without knowing its physical details.

Sign convention (see architecture doc):
    Source Power  : + supply (import / production),  - absorb (export)
    Storage Power : + charge (absorbing energy),      - discharge (supplying)
    Load Power    : + consumption (always >= 0)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np


class Asset(ABC):
    """Common base class for every energy asset in the abstraction layer."""

    #: overridden by subclasses: "source" | "storage" | "load"
    asset_type: str = "asset"

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def get_state(self) -> dict:
        """Current operational state (measured, at t=0)."""

    @abstractmethod
    def get_constraints(self) -> dict:
        """Operational limits for this asset."""

    @abstractmethod
    def get_forecast(self) -> dict:
        """Time-series forecast data for t>0 (empty dict if none)."""

    @abstractmethod
    def get_control(self) -> dict:
        """Control interface exposed to the optimizer (None entries if none)."""


class Source(Asset):
    """
    Energy source (Grid, PV). Sources are never directly controlled by the
    optimizer -- Grid power is a *consequence* of balancing the system, and
    PV production is taken as a fixed forecast (curtailment is out of scope).
    """

    asset_type = "source"

    def __init__(
        self,
        name: str,
        current_power: float,
        max_import_power: Optional[float] = None,
        max_export_power: Optional[float] = None,
        price_forecast: Optional[np.ndarray] = None,
        export_price_fraction: Optional[float] = None,
        power_forecast: Optional[np.ndarray] = None,
    ):
        super().__init__(name)
        self.current_power = current_power           # kW, measured at t=0
        self.max_import_power = max_import_power      # kW  (Grid only)
        self.max_export_power = max_export_power      # kW  (Grid only)
        self.price_forecast = price_forecast           # EUR/kWh, import price (Grid only)
        self.export_price_fraction = export_price_fraction  # export price = fraction * import price
        self.power_forecast = power_forecast           # kW, production forecast (PV only)

    def get_state(self) -> dict:
        return {"current_power": self.current_power}

    def get_constraints(self) -> dict:
        c = {}
        if self.max_import_power is not None:
            c["max_import_power"] = self.max_import_power
        if self.max_export_power is not None:
            c["max_export_power"] = self.max_export_power
        return c

    def get_forecast(self) -> dict:
        f = {}
        if self.price_forecast is not None:
            f["price_forecast"] = self.price_forecast
            f["export_price_forecast"] = self.price_forecast * (self.export_price_fraction or 0.0)
        if self.power_forecast is not None:
            f["power_forecast"] = self.power_forecast
        return f

    def get_control(self) -> dict:
        return {}


class Storage(Asset):
    """
    Energy storage (Home Battery, DHW Tank, Building Thermal Mass, EV Battery).
    State of charge is tracked as a fraction (0-1) of `capacity`.
    
    For assets with passive losses (thermal storage), the passive_discharge_power
    is pre-calculated by a conversion layer and passed in; it represents the power
    lost due to heat loss or other passive processes (kW). The optimizer uses this
    power rate to calculate energy losses over each timestep in the balance equation.
    """

    asset_type = "storage"

    def __init__(
        self,
        name: str,
        current_soc: float,
        capacity: float,
        min_soc: float,
        max_soc: float,
        max_charge_power: float,
        max_discharge_power: float,
        passive_discharge_power: Optional[float] = None,
        charge_efficiency: float = 0.95,
        discharge_efficiency: float = 0.95,
    ):
        super().__init__(name)
        self.current_soc = current_soc                # fraction 0-1, measured at t=0
        self.capacity = capacity                        # kWh
        self.min_soc = min_soc                          # fraction 0-1
        self.max_soc = max_soc                          # fraction 0-1
        self.max_charge_power = max_charge_power        # kW
        self.max_discharge_power = max_discharge_power  # kW
        self.passive_discharge_power = passive_discharge_power  # kWh per timestep (for thermal storage)
        self.charge_efficiency = charge_efficiency      # efficiency when storing energy (0-1, e.g., 0.95 = 95% stored, 5% lost as heat)
        self.discharge_efficiency = discharge_efficiency  # efficiency when releasing energy (0-1, e.g., 0.95 = 95% available, 5% lost as heat)
        self._power_schedule: Optional[np.ndarray] = None  # set by optimizer after solve

    def get_state(self) -> dict:
        return {"current_soc": self.current_soc}

    def get_constraints(self) -> dict:
        c = {
            "capacity": self.capacity,
            "min_soc": self.min_soc,
            "max_soc": self.max_soc,
            "max_charge_power": self.max_charge_power,
            "max_discharge_power": self.max_discharge_power,
            "charge_efficiency": self.charge_efficiency,
            "discharge_efficiency": self.discharge_efficiency,
        }
        if self.passive_discharge_power is not None:
            c["passive_discharge_power"] = self.passive_discharge_power
        return c

    def get_forecast(self) -> dict:
        return {}

    def get_control(self) -> dict:
        return {"set_power": self._power_schedule}

    def set_power(self, schedule: np.ndarray) -> None:
        """Called by the optimizer to attach the resulting control schedule."""
        self._power_schedule = schedule


class Load(Asset):
    """
    Energy consumer. Home Consumption is a fixed (uncontrollable) load driven
    entirely by its forecast; Controllable Loads (future work) additionally
    expose an ON/OFF control.
    """

    asset_type = "load"

    def __init__(
        self,
        name: str,
        current_power: float,
        controllable: bool = False,
        max_power: Optional[float] = None,
        power_forecast: Optional[np.ndarray] = None,
    ):
        super().__init__(name)
        self.current_power = current_power    # kW, measured at t=0
        self.controllable = controllable
        self.max_power = max_power             # kW (controllable loads only)
        self.power_forecast = power_forecast   # kW, demand forecast (Home Consumption)
        self._on_off_schedule: Optional[np.ndarray] = None

    def get_state(self) -> dict:
        return {"current_power": self.current_power}

    def get_constraints(self) -> dict:
        c = {"controllable": self.controllable}
        if self.max_power is not None:
            c["max_power"] = self.max_power
        return c

    def get_forecast(self) -> dict:
        return {"power_forecast": self.power_forecast} if self.power_forecast is not None else {}

    def get_control(self) -> dict:
        return {"set_on_off": self._on_off_schedule} if self.controllable else {}

    def set_on_off(self, schedule: np.ndarray) -> None:
        self._on_off_schedule = schedule

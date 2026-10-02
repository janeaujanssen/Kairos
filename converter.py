"""Convert API payloads to the classes in classes.py.

- Generic inputs:  already in the generic asset model, mapped one-to-one to classes.
                   Used by /optimize-generic, and by /optimize for grid, PV and loads.
- Physical inputs: device-specific storage parameters, converted to the generic storage model.
                   Used by /optimize only.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, time, timedelta
from typing import Any

from classes import (
    BTM,
    DHW,
    PV,
    BaseLoad,
    Battery,
    ControllableLoad,
    Grid,
    Storage,
)

WATER_SPECIFIC_HEAT = 1.163  # Wh/(L*K)


# ===========================================================================
# Shared helpers
# ===========================================================================
def _parse_dt(value: str | datetime) -> datetime:
    """Parse an ISO 8601 string, passing datetimes through unchanged."""
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _parse_optional_dt(value: str | datetime | None) -> datetime | None:
    """Like _parse_dt, but None stays None."""
    return None if value is None else _parse_dt(value)


def _parse_time(value: str | time) -> time:
    """Parse an HH:MM string, passing times through unchanged."""
    return value if isinstance(value, time) else time.fromisoformat(value)


def _time_of_day(value: str | datetime, tz) -> time:
    """Time of day of a timestamp, expressed in timezone tz."""
    return _parse_dt(value).astimezone(tz).time()


def _next_occurrence(after: datetime, tod: time) -> datetime:
    """First moment at or after `after` that falls on time of day `tod`."""
    candidate = datetime.combine(after.date(), tod, tzinfo=after.tzinfo)
    return candidate if candidate >= after else candidate + timedelta(days=1)


def _daily_events(start: datetime, tod: time, n_steps: int, step_hours: float) -> Iterator[datetime]:
    """Yield every occurrence of time of day `tod` inside the horizon."""
    end = start + timedelta(hours=n_steps * step_hours)
    event = _next_occurrence(start, tod)
    while event < end:
        yield event
        event += timedelta(days=1)


def _step_index(t: datetime, start: datetime, step_hours: float) -> int:
    """Index of the time step that contains timestamp t."""
    return int((t - start).total_seconds() // (step_hours * 3600))


# ===========================================================================
# GENERIC INPUTS
# ===========================================================================
def convert_grid(data: dict[str, Any]) -> Grid:
    """Map a grid payload to `Grid`."""
    return Grid(
        id=data["id"],
        name=data["name"],
        current_power=data["current_power"],
        max_import_power=data["max_import_power"],
        max_export_power=data["max_export_power"],
        import_price_forecast=data["import_price_forecast"],
        export_price_forecast=data["export_price_forecast"],
    )


def convert_pv(data: dict[str, Any]) -> PV:
    """Map a PV payload to `PV`."""
    return PV(
        id=data["id"],
        name=data["name"],
        current_power=data["current_power"],
        power_forecast=data["power_forecast"],
    )


def convert_base_load(data: dict[str, Any]) -> BaseLoad:
    """Map a base load payload to `BaseLoad`."""
    return BaseLoad(
        id=data["id"],
        name=data["name"],
        current_power=data["current_power"],
        power_forecast=data["power_forecast"],
    )


def convert_controllable_load(data: dict[str, Any]) -> ControllableLoad:
    """Map a controllable load payload to `ControllableLoad`."""
    return ControllableLoad(
        id=data["id"],
        name=data["name"],
        current_power=data["current_power"],
        average_power=data["average_power"],
        energy_demand=data["energy_demand"],
        earliest_start_time=_parse_optional_dt(data.get("earliest_start_time")),
        latest_finish_time=_parse_optional_dt(data.get("latest_finish_time")),
    )


def convert_generic_storage(data: dict[str, Any]) -> Storage:
    """Map a generic storage payload (`battery`, `dhw`, `building_thermal_mass`) to its class."""
    storage_type = data["storage_type"]
    general = {
        k: data[k]
        for k in (
            "id",
            "name",
            "current_soc",
            "energy_capacity",
            "max_soc",
            "min_soc",
            "charge_efficiency",
            "discharge_efficiency",
            "passive_discharge_power",
            "discharge_to_electrical_network",
            "energy_demand_forecast",
            "availability_window",
        )
    }
    if storage_type == "battery":
        return Battery(
            **general,
            max_charge_power=data["max_charge_power"],
            max_discharge_power=data["max_discharge_power"],
        )
    if storage_type == "dhw":
        return DHW(**general, charge_power=data["charge_power"])
    if storage_type == "building_thermal_mass":
        return BTM(
            **general,
            charge_power=data["charge_power"],
            discharge_power=data["discharge_power"],
            default_efficiency=data["default_efficiency"],
        )
    raise ValueError(f"Unknown generic storage_type: {storage_type!r}")


# ===========================================================================
# PHYSICAL INPUTS (storage only)
# ===========================================================================
def convert_home_battery(data: dict[str, Any], n_steps: int) -> Battery:
    """Home battery: direct mapping to `Battery`, no demand, always available."""
    return Battery(
        id=data["id"],
        name=data["name"],
        current_soc=data["current_soc"],
        energy_capacity=data["energy_capacity"],
        max_soc=data["max_soc"],
        min_soc=data["min_soc"],
        charge_efficiency=data["charge_efficiency"],
        discharge_efficiency=data["discharge_efficiency"],
        passive_discharge_power=data.get("passive_discharge_power", 0.0),
        discharge_to_electrical_network=True,
        energy_demand_forecast=[0.0] * n_steps,
        availability_window=[1] * n_steps,
        max_charge_power=data["max_charge_power"],
        max_discharge_power=data["max_discharge_power"],
    )


def convert_ev_battery(
    data: dict[str, Any], start: datetime, step_hours: float, n_steps: int
) -> Battery:
    """EV battery: `Battery` with trip energy demand and an availability window from the schedule."""
    tz = start.tzinfo
    departure_tod = _time_of_day(data["expected_departure_time"], tz)
    arrival_tod = _time_of_day(data["expected_arrival_time"], tz)
    trip_energy = data["round_trip_distance"] / data["vehicle_efficiency"]  # km / (km/Wh) = Wh

    demand = [0.0] * n_steps
    availability = [1] * n_steps

    def mark_away(first: datetime, last: datetime) -> None:
        """Mark the steps in [first, last) as unavailable."""
        i0 = max(_step_index(first, start, step_hours), 0)
        i1 = min(_step_index(last, start, step_hours), n_steps)
        for i in range(i0, i1):
            availability[i] = 0

    # Next arrival before next departure means the vehicle is away right now.
    next_departure = _next_occurrence(start, departure_tod)
    next_arrival = _next_occurrence(start, arrival_tod)
    if next_arrival < next_departure:
        mark_away(start, next_arrival)

    for departure in _daily_events(start, departure_tod, n_steps, step_hours):
        idx = _step_index(departure, start, step_hours)
        demand[idx] += trip_energy
        mark_away(departure, _next_occurrence(departure, arrival_tod))

    return Battery(
        id=data["id"],
        name=data["name"],
        current_soc=data["current_soc"],
        energy_capacity=data["energy_capacity"],
        max_soc=data["max_soc"],
        min_soc=data["min_soc"],
        charge_efficiency=data["charge_efficiency"],
        discharge_efficiency=data["discharge_efficiency"],
        passive_discharge_power=data.get("passive_discharge_power", 0.0),
        discharge_to_electrical_network=True,
        energy_demand_forecast=demand,
        availability_window=availability,
        max_charge_power=data["max_charge_power"],
        max_discharge_power=data["max_discharge_power"],
    )


def convert_dhw_tank(
    data: dict[str, Any], start: datetime, step_hours: float, n_steps: int
) -> DHW:
    """DHW tank: temperatures to SoC and energy, peak demands to a demand forecast."""
    t_min = data["min_water_temperature"]
    t_max = data["max_water_temperature"]
    span = t_max - t_min

    demand = [0.0] * n_steps
    for peak, energy in (
        ("morning_peak_time", data["morning_peak_energy_demand"]),
        ("evening_peak_time", data["evening_peak_energy_demand"]),
    ):
        for event in _daily_events(start, _parse_time(data[peak]), n_steps, step_hours):
            demand[_step_index(event, start, step_hours)] += energy

    return DHW(
        id=data["id"],
        name=data["name"],
        current_soc=(data["current_water_temperature"] - t_min) / span,
        energy_capacity=data["tank_volume"] * WATER_SPECIFIC_HEAT * span,
        max_soc=1.0,
        min_soc=(data["min_comfort_temperature"] - t_min) / span,
        charge_efficiency=data["heat_pump_cop"],
        discharge_efficiency=1.0,
        passive_discharge_power=data["heat_loss_coefficient"] * span,
        discharge_to_electrical_network=False,
        energy_demand_forecast=demand,
        availability_window=[1] * n_steps,
        charge_power=data["heat_pump_electric_power"],
    )


def convert_building_thermal_mass(data: dict[str, Any], n_steps: int) -> BTM:
    """Building thermal mass: comfort band to SoC and energy, heating/cooldown rates to discrete powers."""
    t_default = data["default_weather_compensation_temperature"]
    span = data["max_comfort_temperature"] - t_default
    thermal_per_degree = data["floor_area"] * data["thermal_mass_coefficient"]  # Wh/°C

    return BTM(
        id=data["id"],
        name=data["name"],
        current_soc=(data["current_indoor_temperature"] - t_default) / span,
        energy_capacity=thermal_per_degree * span,
        max_soc=1.0,
        min_soc=0.0,
        charge_efficiency=data["heat_pump_cop_charge"],
        discharge_efficiency=1.0,
        passive_discharge_power=0.0,
        discharge_to_electrical_network=False,
        energy_demand_forecast=[0.0] * n_steps,
        availability_window=[1] * n_steps,
        charge_power=thermal_per_degree * data["heating_rate"] / data["heat_pump_cop_charge"],
        discharge_power=thermal_per_degree * data["cooldown_rate"],
        default_efficiency=data["heat_pump_cop_default"],
    )


def convert_storage(
    data: dict[str, Any], start: datetime, step_hours: float, n_steps: int
) -> Storage:
    """Convert a physical storage payload (discriminated by `storage_type`) to a generic storage object."""
    storage_type = data["storage_type"]
    if storage_type == "home_battery":
        return convert_home_battery(data, n_steps)
    if storage_type == "ev_battery":
        return convert_ev_battery(data, start, step_hours, n_steps)
    if storage_type == "dhw_tank":
        return convert_dhw_tank(data, start, step_hours, n_steps)
    if storage_type == "building_thermal_mass":
        return convert_building_thermal_mass(data, n_steps)
    raise ValueError(f"Unknown storage_type: {storage_type!r}")


def convert_request_storage(request: dict[str, Any]) -> list[Storage]:
    """Convert all storage entries of an `/optimize` request."""
    start = _parse_dt(request["timestamp"])
    step_hours = request["time_step_duration_hours"]
    n_steps = round(request["horizon_hours"] / step_hours)
    return [convert_storage(s, start, step_hours, n_steps) for s in request["storage"]]

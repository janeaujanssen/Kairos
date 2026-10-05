"""Pure AI: Streamlit UI for Kairos, calling the optimization API (see ui_architecture.md)."""

from __future__ import annotations

import dataclasses
import os
import time as timer
from datetime import datetime, time, timedelta

import plotly.graph_objects as go
import requests
import streamlit as st

import converter
import forecast_simulation as fs
import visualizations as viz

API_URL = os.environ.get("KAIROS_API_URL", "http://localhost:8000")

st.set_page_config(page_title="Kairos - Easy, optimized energy scheduling for Home Assistant", page_icon="⚡", layout="wide")

# ---------------------------------------------------------------------------
# Asset definitions: (key, label, default, kind[, number format])
# kinds: num (>= 0), frac (0-1), temp (any sign), time
# ---------------------------------------------------------------------------
ASSET_TYPES = {
    "grid": {"icon": "⚡", "label": "Grid", "single": True},
    "pv": {"icon": "🔆", "label": "PV", "single": False},
    "base_load": {"icon": "🏠", "label": "Base load", "single": True},
    "controllable_load": {"icon": "🔌", "label": "Controllable load", "single": False},
    "home_battery": {"icon": "🔋", "label": "Home battery", "single": False},
    "ev_battery": {"icon": "🚗", "label": "EV battery", "single": False},
    "dhw_tank": {"icon": "💧", "label": "DHW tank", "single": False},
    "building_thermal_mass": {"icon": "🏢", "label": "Building thermal mass", "single": False},
}
STORAGE_TYPES = ("home_battery", "ev_battery", "dhw_tank", "building_thermal_mass")

_BATTERY_COMMON = [
    ("current_soc", "Current SoC [-]", 0.5, "frac"),
    ("min_soc", "Min SoC [-]", 0.1, "frac"),
    ("max_soc", "Max SoC [-]", 0.9, "frac"),
    ("charge_efficiency", "Charge efficiency [-]", 0.95, "frac"),
    ("discharge_efficiency", "Discharge efficiency [-]", 0.95, "frac"),
    ("passive_discharge_power", "Passive discharge power [W]", 0.0, "num"),
]

PHYSICAL_FIELDS = {
    "grid": [
        ("current_power", "Current power [W] (+import, -export)", 0.0, "temp"),
        ("max_import_power", "Max import power [W]", 11000.0, "num"),
        ("max_export_power", "Max export power [W]", 11000.0, "num"),
    ],
    "pv": [("current_power", "Current power [W]", 0.0, "num")],
    "base_load": [("current_power", "Current power [W]", 450.0, "num")],
    "controllable_load": [
        ("current_power", "Current power [W]", 0.0, "num"),
        ("average_power", "Average power [W]", 1500.0, "num"),
        ("energy_demand", "Energy demand [Wh]", 1800.0, "num"),
        ("earliest_start_h", "Earliest start [h from now]", 0.0, "num"),
        ("latest_finish_h", "Latest finish [h from now]", 12.0, "num"),
    ],
    "home_battery": [
        ("energy_capacity", "Energy capacity [Wh]", 10000.0, "num"),
        ("max_charge_power", "Max charge power [W]", 5000.0, "num"),
        ("max_discharge_power", "Max discharge power [W]", 5000.0, "num"),
        *_BATTERY_COMMON,
    ],
    "ev_battery": [
        ("energy_capacity", "Energy capacity [Wh]", 60000.0, "num"),
        ("max_charge_power", "Max charge power [W]", 7400.0, "num"),
        ("max_discharge_power", "Max discharge power [W]", 0.0, "num"),
        *_BATTERY_COMMON,
    ],
    "dhw_tank": [
        ("tank_volume", "Tank volume [L]", 300.0, "num"),
        ("min_water_temperature", "Min water temperature [°C]", 20.0, "temp"),
        ("max_water_temperature", "Max water temperature [°C]", 60.0, "temp"),
        ("current_water_temperature", "Current water temperature [°C]", 50.0, "temp"),
        ("min_comfort_temperature", "Min comfort temperature [°C]", 40.0, "temp"),
        ("heat_loss_coefficient", "Heat loss coefficient [W/°C]", 4.0, "num"),
        ("heat_pump_electric_power", "Heat pump electric power [W]", 3000.0, "num"),
        ("heat_pump_cop", "Heat pump COP [-]", 3.0, "num"),
    ],
    "building_thermal_mass": [
        ("floor_area", "Floor area [m²]", 100.0, "num"),
        ("thermal_mass_coefficient", "Thermal mass coefficient [Wh/m²/°C]", 200.0, "num"),
        ("default_weather_compensation_temperature", "Default weather compensation temp [°C]", 20.0, "temp"),
        ("current_indoor_temperature", "Current indoor temperature [°C]", 20.5, "temp"),
        ("max_comfort_temperature", "Max comfort temperature [°C]", 21.0, "temp"),
        ("heating_rate", "Heating rate (+dT) [°C/h]", 0.6, "num"),
        ("cooldown_rate", "Cooldown rate (-dT) [°C/h]", 0.1, "num"),
        ("heat_pump_cop_charge", "Heat pump COP, +dT mode [-]", 2.5, "num"),
        ("heat_pump_cop_default", "Heat pump COP, default mode [-]", 3.0, "num"),
    ],
}

FORECAST_FIELDS = {
    "grid": [
        ("baseline_price", "Baseline price [price/kWh]", 0.25, "num"),
        ("morning_peak_time", "Morning peak time", time(7, 0), "time"),
        ("evening_peak_time", "Evening peak time", time(19, 0), "time"),
        ("morning_peak_price", "Morning peak price [price/kWh]", 0.35, "num"),
        ("evening_peak_price", "Evening peak price [price/kWh]", 0.45, "num"),
        ("export_fraction", "Export price / import price [-]", 0.4, "frac"),
    ],
    "pv": [("peak_power", "Peak power [W]", 5000.0, "num")],
    "base_load": [
        ("baseline_consumption", "Baseline consumption [W]", 500.0, "num"),
        ("morning_peak_time", "Morning peak time", time(7, 30), "time"),
        ("evening_peak_time", "Evening peak time", time(19, 0), "time"),
        ("morning_peak_power", "Morning peak power [W]", 2300.0, "num"),
        ("evening_peak_power", "Evening peak power [W]", 3600.0, "num"),
    ],
    "ev_battery": [
        ("vehicle_efficiency", "Vehicle efficiency [km/kWh]", 5.0, "num", "%.2f"),
        ("round_trip_distance", "Round trip distance [km]", 100.0, "num"),
        ("expected_departure_time", "Expected departure time", time(9, 0), "time"),
        ("expected_arrival_time", "Expected arrival time", time(18, 0), "time"),
    ],
    "dhw_tank": [
        ("morning_peak_energy_demand", "Morning peak energy demand [Wh]", 1500.0, "num"),
        ("evening_peak_energy_demand", "Evening peak energy demand [Wh]", 1800.0, "num"),
        ("morning_peak_time", "Morning peak time", time(7, 0), "time"),
        ("evening_peak_time", "Evening peak time", time(19, 0), "time"),
    ],
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
st.session_state.setdefault("assets", [])
st.session_state.setdefault("asset_counter", 0)
st.session_state.setdefault("result", None)


def add_asset(asset_type: str) -> None:
    st.session_state.asset_counter += 1
    n = st.session_state.asset_counter
    label = ASSET_TYPES[asset_type]["label"]
    st.session_state.assets.append(
        {"id": f"{asset_type}_{n}", "type": asset_type, "name": f"{label} {n}", "enabled": True}
    )


def remove_asset(asset_id: str) -> None:
    st.session_state.assets = [a for a in st.session_state.assets if a["id"] != asset_id]


def render_fields(asset_id: str, fields: list[tuple]) -> dict:
    """Render input widgets for the given field specs and return their values by key."""
    values = {}
    for key, label, default, kind, *fmt in fields:
        wkey = f"{asset_id}_{key}"
        if kind == "time":
            values[key] = st.time_input(label, value=default, key=wkey)
        elif kind == "frac":
            values[key] = st.number_input(label, 0.0, 1.0, float(default), step=0.05, key=wkey)
        else:
            values[key] = st.number_input(
                label,
                min_value=0.0 if kind == "num" else None,
                value=float(default),
                step=0.001 if fmt else 1.0,
                format=fmt[0] if fmt else None,
                key=wkey,
            )
    return values


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    run_clicked = st.button("▶ Run optimization", type="primary", width="stretch")

    with st.expander("Sign Convention Reference"):
        st.markdown(
            "- **Grid Power**: +import, −export\n"
            "- **PV Power**: +production\n"
            "- **Battery Power**: +charge, −discharge\n"
            "- **DHW Battery Power**: +charge, −discharge\n"
            "- **Building Battery Power**: +charge, −discharge\n"
            "- **Load Power**: +consumption\n"
            "- Energy balance: Grid + PV = Load + Storage at every timestep"
        )

    st.subheader("Asset Enablement Toggles")
    if not st.session_state.assets:
        st.caption("No assets yet. Add them in the Inputs tab.")
    for asset in st.session_state.assets:
        info = ASSET_TYPES[asset["type"]]
        asset["enabled"] = st.toggle(
            f"{info['icon']} {asset['name']}", value=asset["enabled"], key=f"{asset['id']}_enabled"
        )

    st.subheader("Configuration")
    horizon_h = st.number_input("Planning horizon [h]", 6, 48, 24, step=1)
    interval_min = st.selectbox("Time interval [min]", [15, 30, 60], index=0)
    start_time = st.time_input("Start time [hh:mm]", value=time(0, 0))

# ---------------------------------------------------------------------------
# Time context
# ---------------------------------------------------------------------------
step_h = interval_min / 60
n_steps = round(horizon_h / step_h)
_now = datetime.now().astimezone().replace(second=0, microsecond=0)
start = _now.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
timestamps = [start + timedelta(hours=i * step_h) for i in range(n_steps)]
hours_of_day = [(start.hour + start.minute / 60 + i * step_h) % 24 for i in range(n_steps)]


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------
def build_payload(asset: dict, physical: dict, forecast: dict) -> dict:
    """Assemble the API payload for one asset from its physical and forecast inputs."""
    payload = {"id": asset["id"], "name": asset["name"], **physical}
    t = asset["type"]
    if t == "grid":
        imp, exp = fs.grid_price_forecast(
            hours_of_day,
            forecast["baseline_price"] / 1000,
            forecast["morning_peak_time"],
            forecast["evening_peak_time"],
            forecast["morning_peak_price"] / 1000,
            forecast["evening_peak_price"] / 1000,
            forecast["export_fraction"],
        )
        payload.update(import_price_forecast=imp, export_price_forecast=exp)
    elif t == "pv":
        payload["power_forecast"] = fs.pv_power_forecast(hours_of_day, forecast["peak_power"])
    elif t == "base_load":
        payload["power_forecast"] = fs.base_load_forecast(hours_of_day, **forecast)
    elif t == "controllable_load":
        payload["earliest_start_time"] = (start + timedelta(hours=payload.pop("earliest_start_h"))).isoformat()
        payload["latest_finish_time"] = (start + timedelta(hours=payload.pop("latest_finish_h"))).isoformat()
    elif t in STORAGE_TYPES:
        payload["storage_type"] = t
        for key, value in forecast.items():
            if isinstance(value, time):
                if t == "ev_battery":
                    value = datetime.combine(start.date(), value, tzinfo=start.tzinfo).isoformat()
                else:
                    value = value.strftime("%H:%M")
            elif key == "vehicle_efficiency" and t == "ev_battery":
                # Convert from km/kWh (display) to km/Wh (backend): divide by 1000
                value = value / 1000
            payload[key] = value
    return payload


def to_generic(asset_type: str, payload: dict):
    """Convert a payload to its generic class using the backend converter."""
    if asset_type == "grid":
        return converter.convert_grid(payload)
    if asset_type == "pv":
        return converter.convert_pv(payload)
    if asset_type == "base_load":
        return converter.convert_base_load(payload)
    if asset_type == "controllable_load":
        return converter.convert_controllable_load(payload)
    return converter.convert_storage(payload, start, step_h, n_steps)


def render_asset(asset: dict) -> tuple[dict, object]:
    """Render one asset expander with three columns: Physical, Generic, and Forecast inputs, then chart below."""
    t = asset["type"]
    info = ASSET_TYPES[t]
    with st.expander(f"{info['icon']} {asset['name']}", expanded=False):
        # Asset name input
        asset["name"] = st.text_input("Name", asset["name"], key=f"{asset['id']}_name")
        
        # Create three columns
        cols = st.columns(3)
        
        # First pass: render physical and forecast inputs to collect data
        with cols[0]:
            st.markdown("**Physical inputs**")
            physical = render_fields(asset["id"], PHYSICAL_FIELDS[t])
        
        forecast: dict = {}
        with cols[2]:
            st.markdown("**Forecast inputs**")
            if t in FORECAST_FIELDS:
                forecast = render_fields(asset["id"], FORECAST_FIELDS[t])
            else:
                st.caption("No forecast inputs for this asset")
        
        # Build payload and generic with collected data
        payload = build_payload(asset, physical, forecast)
        generic = None
        try:
            generic = to_generic(t, payload)
        except (ValueError, KeyError, ZeroDivisionError) as e:
            st.warning(f"Cannot convert inputs: {e}")
        
        # Render generic inputs in middle column
        with cols[1]:
            st.markdown("**Generic inputs**")
            if generic is not None:
                st.json(dataclasses.asdict(generic), expanded=False)
        
        # Forecast chart full width below the columns
        if t in FORECAST_FIELDS:
            fig = viz.forecast_chart(t, payload, generic, timestamps, forecast)
            if fig is not None:
                viz.show(fig)
        
        # Remove button
        if st.button("Remove asset", key=f"{asset['id']}_remove"):
            remove_asset(asset["id"])
            st.rerun()
    
    return payload, generic


# ---------------------------------------------------------------------------
# Optimization
# ---------------------------------------------------------------------------
def run_optimization(entries: list[tuple[dict, dict, object]]) -> None:
    """Call the API with all enabled assets and store the result in session state."""
    by_type = lambda t: [(a, p, g) for a, p, g in entries if a["type"] == t]
    grid, base_load = by_type("grid"), by_type("base_load")
    if not grid or not base_load:
        st.session_state.result = {"error": "Add and enable a Grid and a Base load asset."}
        return
    if any(g is None for _, _, g in entries):
        st.session_state.result = {"error": "Fix the invalid asset inputs first."}
        return

    storage = [(a, p, g) for t in STORAGE_TYPES for a, p, g in by_type(t)]
    request = {
        "timestamp": start.isoformat(),
        "time_step_duration_hours": step_h,
        "horizon_hours": horizon_h,
        "grid": grid[0][1],
        "pv": [p for _, p, _ in by_type("pv")],
        "base_load": base_load[0][1],
        "controllable_loads": [p for _, p, _ in by_type("controllable_load")],
        "storage": [p for _, p, _ in storage],
    }
    t0 = timer.perf_counter()
    try:
        response = requests.post(f"{API_URL}/optimize", json=request, timeout=120)
    except requests.RequestException as e:
        st.session_state.result = {"error": f"API request failed: {e}"}
        return
    elapsed = timer.perf_counter() - t0
    if not response.ok:
        st.session_state.result = {"error": f"API error {response.status_code}: {response.text}"}
        return

    optimization_response = response.json()
    grid_id = grid[0][0]["id"]
    result_timestamps = [
        datetime.fromisoformat(point["time"])
        for point in optimization_response["assets"].get(grid_id, {}).get("schedule", [])
    ] or timestamps
    pv_total = [sum(vals) for vals in zip(*(p["power_forecast"] for _, p, _ in by_type("pv")))] or [0.0] * n_steps
    st.session_state.result = {
        "data": optimization_response,
        "solve_time": elapsed,
        "timestamps": result_timestamps,
        "step_h": optimization_response["time_step_minutes"] / 60,
        "import_price": grid[0][1]["import_price_forecast"],
        "export_price": grid[0][1]["export_price_forecast"],
        "base_load": base_load[0][1]["power_forecast"],
        "pv": pv_total,
        "grid_id": grid[0][0]["id"],
        "controllable_ids": [a["id"] for a, _, _ in by_type("controllable_load")],
        "storage_ids": [a["id"] for a, _, _ in storage],
        "generics": {a["id"]: g for a, _, g in storage},
    }


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_inputs, tab_opt = st.tabs(["📥 Inputs", "📊 Optimization results"])

entries: list[tuple[dict, dict, object]] = []
with tab_inputs:
    st.markdown("**Add new assets**")
    present = {a["type"] for a in st.session_state.assets}
    all_options = list(ASSET_TYPES.keys())
    
    # Create rows of + buttons for each asset type
    cols_per_row = 4
    rows = [all_options[i:i+cols_per_row] for i in range(0, len(all_options), cols_per_row)]
    for row in rows:
        cols = st.columns(len(row))
        for col, asset_type in zip(cols, row):
            with col:
                info = ASSET_TYPES[asset_type]
                # Disable button if this is a single-instance asset and it's already added
                is_disabled = info["single"] and asset_type in present
                if st.button(f"+ {info['icon']} {info['label']}", 
                            key=f"add_{asset_type}", use_container_width=True, disabled=is_disabled):
                    add_asset(asset_type)
                    st.rerun()

    if not st.session_state.assets:
        st.info("No assets added yet. Use the + buttons above to start.")
    for asset in list(st.session_state.assets):
        if asset["enabled"]:
            payload, generic = render_asset(asset)
            entries.append((asset, payload, generic))

if run_clicked:
    with st.spinner("Optimizing..."):
        run_optimization(entries)

with tab_opt:
    result = st.session_state.result
    if result is None:
        st.info("No result yet. Click 'Run optimization' in the sidebar.")
    elif "error" in result:
        st.error(result["error"])
    else:
        data, ts, dt = result["data"], result["timestamps"], result["step_h"]
        st.subheader("Solver info")
        c1, c2, c3 = st.columns(3)
        c1.metric("Status", data["status"])
        c2.metric("Solve time", f"{result['solve_time']:.2f} s")
        c3.metric("Objective cost", f"{data['objective_cost']:.2f}")

        if data["status"] == "Infeasible":
            st.warning("No feasible schedule exists for the given constraints.")
        else:
            assets = data["assets"]
            schedule = {
                asset_id: [point["value"] for point in asset["schedule"]]
                for asset_id, asset in assets.items()
            }
            soc = {
                asset_id: [point["value"] for point in asset["soc_schedule"]]
                for asset_id, asset in assets.items()
                if "soc_schedule" in asset
            }
            generics = result["generics"]
            controllable = [
                sum(vals) for vals in zip(*(schedule[i] for i in result["controllable_ids"] if i in schedule))
            ] or [0.0] * len(ts)
            home_load = [b + c for b, c in zip(result["base_load"], controllable)]

            net_grid = schedule[result["grid_id"]]
            soc_timestamps = next(
                (
                    [datetime.fromisoformat(point["time"]) for point in assets[storage_id]["soc_schedule"]]
                    for storage_id in result["storage_ids"]
                    if storage_id in assets and "soc_schedule" in assets[storage_id]
                ),
                [],
            )

            st.subheader("Power Flow")
            viz.show(viz.power_flow_chart(
                ts, home_load, result["storage_ids"], schedule, net_grid, result["pv"],
                result["import_price"], result["export_price"],
            ))
            st.subheader("Cost Analysis")
            viz.show(viz.cost_analysis_chart(ts, net_grid, result["import_price"], result["export_price"], dt))
            st.subheader("State of Charge Trajectories")
            viz.show(viz.soc_chart(soc_timestamps, result["storage_ids"], soc, generics))

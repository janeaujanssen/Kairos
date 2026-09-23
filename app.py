"""
Layer 4: User Interface - Streamlit web app for the Home EMS Optimizer.

Run with:  streamlit run app.py

Scope: Grid, PV, Home Battery, Home Consumption (per architecture doc's
"start with Grid, PV, Battery and Home Load"). EV/DHW/Building thermal mass
are not yet wired in -- the Asset abstraction (assets.py) is already generic
enough to add them later without touching the optimizer's structure.
"""

from __future__ import annotations

import numpy as np
import streamlit as st

from assets import Source, Storage, Load
from simulator import (
    time_axis,
    simulate_grid_price,
    simulate_pv_production,
    simulate_load_demand,
    simulate_dhw_demand,
    with_measured_start,
)
from optimizer import Optimizer, OptimizationResult
from evcc_client import run_evcc_optimization, EVCCResult, DEFAULT_EVCC_URL
from dhw_conversion import DHWPhysicalParams, convert_dhw_params
import visualization as viz

st.set_page_config(page_title="Home EMS Optimizer", page_icon="🏠", layout="wide")

# ----------------------------------------------------------------------------
# Session state defaults
# ----------------------------------------------------------------------------
if "result" not in st.session_state:
    st.session_state.result = None  # type: OptimizationResult | None
if "evcc_result" not in st.session_state:
    st.session_state.evcc_result = None  # type: EVCCResult | None

# ----------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------
st.sidebar.title("🏠 EMS Optimizer")

run_clicked = st.sidebar.button("▶ Run optimization", type="primary", width='stretch')

st.sidebar.divider()

with st.sidebar.expander("⚡ Sign convention reference", expanded=False):
    st.markdown(
        "- **Grid power**: `+` import, `-` export\n"
        "- **PV power**: `+` production\n"
        "- **Battery power**: `+` charge, `-` discharge\n"
        "- **Load power**: `+` consumption (always ≥ 0)\n\n"
        "Energy balance: `Grid + PV = Load + Battery` at every timestep."
    )

st.sidebar.subheader("Strategy")
peak_leveling = st.sidebar.checkbox(
    "Peak leveling", value=False,
    help="Penalize the highest grid power draw to reduce demand charges and grid stress, "
         "without increasing total cost.",
)
charging_priority = st.sidebar.checkbox(
    "Charging priority", value=False,
    help="Among equal-cost solutions, prefer charging the battery over exporting excess PV.",
)

st.sidebar.subheader("Assets")
battery_1_enabled = st.sidebar.checkbox("🔋 Battery 1", value=True)
battery_2_enabled = st.sidebar.checkbox("🔋 Battery 2", value=False)
dhw_tank_enabled = st.sidebar.checkbox("💧 DHW Tank", value=False)

st.sidebar.subheader("Configuration")
mode_label = st.sidebar.selectbox(
    "Optimization mode", ["Cost optimization", "Self-consumption"], index=0,
)
mode = "cost" if mode_label == "Cost optimization" else "self_consumption"

horizon_hours = st.sidebar.slider("Planning horizon (hours)", min_value=6, max_value=48, value=24, step=1)
interval_minutes = st.sidebar.selectbox("Time interval (minutes)", [15, 30, 60], index=0)
start_hour = st.sidebar.slider(
    "Simulated start time (clock hour, t=0)", min_value=0.0, max_value=23.5,
    value=0.0, step=0.5,
)
solver_tolerance = st.sidebar.number_input(
    "Solver tolerance (relative MIP gap)", min_value=1e-12, max_value=1e-2,
    value=1e-9, format="%.1e",
)
max_iterations = st.sidebar.number_input("Max iterations", min_value=10, max_value=100000, value=500, step=10)
soft_penalty = st.sidebar.number_input(
    "Constraint violation penalty (EUR/kWh)", min_value=0.0, max_value=10000.0, value=1000.0, step=100.0,
    help="Cost per kWh of SoC constraint violation. Higher values discourage violations.",
)

st.sidebar.subheader("EVCC optimizer (optional)")
evcc_enabled = st.sidebar.checkbox("Also run EVCC optimizer for comparison", value=False)
evcc_url = st.sidebar.text_input("EVCC service URL", value=DEFAULT_EVCC_URL, disabled=not evcc_enabled)
evcc_prc_p_exc_imp = st.sidebar.number_input(
    "EVCC import limit penalty (EUR/W)", value=0.0, step=0.001, format="%.4f",
    disabled=not evcc_enabled,
    help="Price per W to penalize if grid import power exceeds the limit. Set to 0 for hard limit.",
)

# ----------------------------------------------------------------------------
# Build time axis + forecasts (shared by Inputs tab display and the optimizer)
# ----------------------------------------------------------------------------
hours, dt_hours, n_steps = time_axis(horizon_hours, interval_minutes, start_hour=start_hour)

tab_inputs, tab_optimization = st.tabs(["📥 Inputs", "📊 Optimization"])

# ============================================================================
# INPUTS TAB
# ============================================================================
with tab_inputs:
    st.header("Sources")

    # --- Grid ---
    with st.expander("🔌 Grid", expanded=True):
        st.markdown("**Current state** *(measured, t=0)*")
        c1, c2 = st.columns(2)
        grid_current_power = c1.number_input(
            "Current grid power (kW)", value=0.5, step=0.1, key="grid_current_power",
            help="Measured import(+)/export(-) power right now. Informational; the optimizer "
                 "solves for grid power at every step including t=0.",
        )

        st.markdown("**Constraints**")
        c1, c2 = st.columns(2)
        grid_max_import = c1.number_input("Max import power (kW)", value=10.0, min_value=0.0, key="grid_max_import")
        grid_max_export = c2.number_input("Max export power (kW)", value=8.0, min_value=0.0, key="grid_max_export")

        st.markdown("**Forecast** — dynamic tariff (baseline + morning/evening peaks)")
        c1, c2, c3 = st.columns(3)
        price_baseline = c1.number_input("Baseline price (EUR/kWh)", value=0.20, step=0.01, key="price_baseline")
        price_peak_height = c2.number_input("Peak height (EUR/kWh)", value=0.25, step=0.01, key="price_peak_height")
        export_price_fraction = c3.slider("Export price (fraction of import)", 0.0, 1.0, 0.7, key="export_fraction")
        c1, c2 = st.columns(2)
        price_morning_hour = c1.slider("Morning peak hour", 0.0, 23.5, 8.0, step=0.5, key="price_morning_hour")
        price_evening_hour = c2.slider("Evening peak hour", 0.0, 23.5, 19.0, step=0.5, key="price_evening_hour")

        price_forecast_full = simulate_grid_price(
            hours, baseline=price_baseline, morning_peak_hour=price_morning_hour,
            evening_peak_hour=price_evening_hour, peak_height=price_peak_height,
        )
        st.plotly_chart(
            viz.plot_price_forecast(hours, price_forecast_full, export_price_fraction),
            width='stretch', key="chart_price_forecast",
        )

        st.markdown("**Control**")
        st.caption("None — Sources are not directly controlled; grid power results from the energy balance.")

    # --- PV ---
    with st.expander("☀️ PV", expanded=True):
        st.markdown("**Current state** *(measured, t=0)*")
        pv_current_power = st.number_input("Current PV power (kW)", value=0.0, min_value=0.0, step=0.1, key="pv_current_power")

        st.markdown("**Constraints**")
        st.caption("— (curtailment not modeled)")

        st.markdown("**Forecast** — bell curve peaking at solar noon")
        c1, c2, c3 = st.columns(3)
        pv_peak_power = c1.number_input("Peak production (kW)", value=5.0, min_value=0.0, key="pv_peak_power")
        pv_sunrise = c2.slider("Sunrise hour", 0.0, 12.0, 6.5, step=0.5, key="pv_sunrise")
        pv_sunset = c3.slider("Sunset hour", 12.0, 24.0, 20.0, step=0.5, key="pv_sunset")

        pv_forecast_full = simulate_pv_production(hours, peak_power=pv_peak_power, sunrise=pv_sunrise, sunset=pv_sunset)
        st.plotly_chart(viz.plot_pv_forecast(hours, pv_forecast_full), width='stretch', key="chart_pv_forecast")

        st.markdown("**Control**")
        st.caption("None — Sources are not directly controlled.")

    st.header("Storage")

    # --- Home Battery 1 ---
    with st.expander("🔋 Battery 1", expanded=True):
        st.markdown("**Current state** *(measured, t=0)*")
        battery1_current_soc = st.slider("Current SoC (%)", 0, 100, 50, key="battery1_current_soc") / 100.0

        st.markdown("**Constraints**")
        c1, c2 = st.columns(2)
        battery1_capacity = c1.number_input("Energy capacity (kWh)", value=10.0, min_value=0.1, key="battery1_capacity")
        battery1_min_soc, battery1_max_soc = c2.slider(
            "Min / max SoC (%)", 0, 100, (10, 95), key="battery1_soc_range",
        )
        battery1_min_soc, battery1_max_soc = battery1_min_soc / 100.0, battery1_max_soc / 100.0
        c1, c2 = st.columns(2)
        battery1_max_charge = c1.number_input("Max charge power (kW)", value=5.0, min_value=0.0, key="battery1_max_charge")
        battery1_max_discharge = c2.number_input("Max discharge power (kW)", value=5.0, min_value=0.0, key="battery1_max_discharge")
        battery1_passive_discharge = st.number_input(
            "Passive discharge power (kW)", value=0.0, min_value=0.0, step=0.001,
            key="battery1_passive_discharge",
            help="Power lost due to self-discharge or standby losses (kW). For electrical batteries, typically 0."
        )
        c1, c2 = st.columns(2)
        battery1_charge_efficiency = c1.slider(
            "Charge efficiency", 0.0, 1.0, 0.95, step=0.01, key="battery1_charge_efficiency",
            help="Fraction of input power stored (0-1). 0.95 = 95% stored, 5% lost as heat."
        )
        battery1_discharge_efficiency = c2.slider(
            "Discharge efficiency", 0.0, 1.0, 0.95, step=0.01, key="battery1_discharge_efficiency",
            help="Fraction of stored energy available when discharging (0-1). 0.95 = 95% available, 5% lost."
        )

        st.markdown("**Forecast**")
        st.caption("— None; battery behavior is determined entirely by the optimizer.")

        st.markdown("**Control**")
        st.caption("Battery Charge/Discharge Power (kW) — set by the optimizer.")

    # --- Home Battery 2 ---
    if battery_2_enabled:
        with st.expander("🔋 Battery 2", expanded=True):
            st.markdown("**Current state** *(measured, t=0)*")
            battery2_current_soc = st.slider("Current SoC (%)", 0, 100, 30, key="battery2_current_soc") / 100.0

            st.markdown("**Constraints**")
            c1, c2 = st.columns(2)
            battery2_capacity = c1.number_input("Energy capacity (kWh)", value=5.0, min_value=0.1, key="battery2_capacity")
            battery2_min_soc, battery2_max_soc = c2.slider(
                "Min / max SoC (%)", 0, 100, (10, 95), key="battery2_soc_range",
            )
            battery2_min_soc, battery2_max_soc = battery2_min_soc / 100.0, battery2_max_soc / 100.0
            c1, c2 = st.columns(2)
            battery2_max_charge = c1.number_input("Max charge power (kW)", value=3.0, min_value=0.0, key="battery2_max_charge")
            battery2_max_discharge = c2.number_input("Max discharge power (kW)", value=3.0, min_value=0.0, key="battery2_max_discharge")
            battery2_passive_discharge = st.number_input(
                "Passive discharge power (kW)", value=0.0, min_value=0.0, step=0.001,
                key="battery2_passive_discharge",
                help="Power lost due to self-discharge or standby losses (kW)."
            )
            c1, c2 = st.columns(2)
            battery2_charge_efficiency = c1.slider(
                "Charge efficiency", 0.0, 1.0, 0.95, step=0.01, key="battery2_charge_efficiency",
                help="Fraction of input power stored (0-1). 0.95 = 95% stored, 5% lost as heat."
            )
            battery2_discharge_efficiency = c2.slider(
                "Discharge efficiency", 0.0, 1.0, 0.95, step=0.01, key="battery2_discharge_efficiency",
                help="Fraction of stored energy available when discharging (0-1). 0.95 = 95% available, 5% lost."
            )

            st.markdown("**Forecast**")
            st.caption("— None; battery behavior is determined entirely by the optimizer.")

            st.markdown("**Control**")
            st.caption("Battery Charge/Discharge Power (kW) — set by the optimizer.")
    else:
        battery2_current_soc = 0.0
        battery2_capacity = 0.0
        battery2_min_soc = 0.0
        battery2_max_soc = 1.0
        battery2_max_charge = 0.0
        battery2_max_discharge = 0.0
        battery2_passive_discharge = 0.0
        battery2_charge_efficiency = 0.95
        battery2_discharge_efficiency = 0.95

    # --- DHW Tank ---
    if dhw_tank_enabled:
        with st.expander("🚰 DHW Tank", expanded=True):
            # Physical parameters section with light blue background
            st.markdown("**Physical Parameters** *(editable)*")
            with st.container():
                st.markdown(
                    '<div style="background-color: #E3F2FD; padding: 12px; border-radius: 5px; margin-bottom: 15px;">'
                    '<small><i>Physical tank properties below. Derived battery parameters computed automatically.</i></small>'
                    '</div>',
                    unsafe_allow_html=True
                )
                c1, c2 = st.columns(2)
                dhw_volume = c1.number_input(
                    "Tank volume (liters)", value=300.0, min_value=1.0, step=10.0, key="dhw_volume",
                    help="Total water volume in the DHW tank (liters)"
                )
                dhw_current_temp = c2.number_input(
                    "Current water temp (°C)", value=50.0, min_value=0.0, max_value=100.0, step=1.0, key="dhw_current_temp",
                    help="Measured water temperature at t=0"
                )
                
                c1, c2 = st.columns(2)
                dhw_min_temp = c1.number_input(
                    "Minimum temp (°C)", value=20.0, min_value=0.0, max_value=100.0, step=1.0, key="dhw_min_temp",
                    help="Ambient temperature around the tank (typically 20°C)"
                )
                dhw_max_temp = c2.number_input(
                    "Maximum temp (°C)", value=60.0, min_value=0.0, max_value=100.0, step=1.0, key="dhw_max_temp",
                    help="Maximum safe water temperature"
                )
                
                c1, c2 = st.columns(2)
                dhw_min_comfort_temp = c1.number_input(
                    "Comfort temp (°C)", value=40.0, min_value=0.0, max_value=100.0, step=1.0, key="dhw_min_comfort_temp",
                    help="Minimum water temperature for comfortable use (e.g., showers)"
                )
                dhw_heat_loss_coeff = c2.number_input(
                    "Heat loss coeff (kW/K)", value=0.004, min_value=0.0, step=0.001, format="%.4f", key="dhw_heat_loss_coeff",
                    help="Heat loss per Kelvin temperature difference (kW/K)"
                )
                
                dhw_max_charge_power = st.number_input(
                    "Heat pump power (kW)", value=3.0, min_value=0.0, step=0.1, key="dhw_max_charge_power",
                    help="Maximum heating power from heat pump (kW)"
                )
            
            # Calculate equivalent battery parameters
            try:
                dhw_physical = DHWPhysicalParams(
                    volume_liters=dhw_volume,
                    min_temp_celsius=dhw_min_temp,
                    max_temp_celsius=dhw_max_temp,
                    current_temp_celsius=dhw_current_temp,
                    heat_loss_coeff_kw_per_k=dhw_heat_loss_coeff,
                    min_comfort_temp_celsius=dhw_min_comfort_temp,
                    max_charge_power_kw=dhw_max_charge_power,
                )
                dhw_battery_params = convert_dhw_params(dhw_physical)
            except ValueError as e:
                st.error(f"Invalid DHW parameters: {e}")
                dhw_battery_params = None
            
            if dhw_battery_params:
                st.markdown("**Current state** *(measured, t=0)*")
                dhw_current_soc = st.slider(
                    "Current SoC (%)", 0, 100, 
                    int(dhw_battery_params.current_soc * 100), 
                    disabled=True,
                    help="Derived from current water temperature and temperature range"
                ) / 100.0

                st.markdown("**Constraints** *(derived from physical parameters)*")
                c1, c2 = st.columns(2)
                dhw_capacity = c1.number_input(
                    "Energy capacity (kWh)", value=dhw_battery_params.capacity_kwh, 
                    min_value=0.1,
                    disabled=True,
                    help="Calculated from tank volume and temperature range"
                )
                dhw_min_soc_val, dhw_max_soc_val = c2.slider(
                    "Min / max SoC (%)", 0, 100, 
                    (int(dhw_battery_params.min_soc * 100), int(dhw_battery_params.max_soc * 100)),
                    disabled=True,
                    help="Min: comfort constraint; Max: maximum safe temperature"
                )
                dhw_min_soc = dhw_min_soc_val / 100.0
                dhw_max_soc = dhw_max_soc_val / 100.0
                
                c1, c2 = st.columns(2)
                dhw_max_charge = c1.number_input(
                    "Max charge power (kW)", value=dhw_battery_params.max_charge_power_kw,
                    min_value=0.0,
                    disabled=True,
                    help="From heat pump power input"
                )
                dhw_max_discharge = c2.number_input(
                    "Max discharge power (kW)", value=dhw_battery_params.max_discharge_power_kw,
                    min_value=0.0,
                    disabled=True,
                    help="DHW has no active discharge (0 kW)"
                )
                
                dhw_passive_discharge = st.number_input(
                    "Passive discharge power (kW)", value=dhw_battery_params.passive_discharge_power_kw,
                    min_value=0.0, step=0.001,
                    disabled=True,
                    help="Calculated from heat loss coefficient and current temperature"
                )
                
                c1, c2 = st.columns(2)
                dhw_charge_efficiency = c1.slider(
                    "Charge efficiency", 0.0, 1.0, 1.0, step=0.01,
                    disabled=True,
                    help="Thermal storage has no charge/discharge losses (1.0)"
                )
                dhw_discharge_efficiency = c2.slider(
                    "Discharge efficiency", 0.0, 1.0, 1.0, step=0.01,
                    disabled=True,
                    help="Thermal storage has no charge/discharge losses (1.0)"
                )

                st.markdown("**Forecast** — hot water demand")
                c1, c2 = st.columns(2)
                dhw_morning_peak_energy = c1.number_input(
                    "Morning shower energy (kWh)", value=0.8, min_value=0.0, step=0.1,
                    key="dhw_morning_peak_energy",
                    help="Typical energy needed for morning showers"
                )
                dhw_evening_peak_energy = c2.number_input(
                    "Evening usage energy (kWh)", value=0.5, min_value=0.0, step=0.1,
                    key="dhw_evening_peak_energy",
                    help="Typical energy needed for evening hot water use"
                )
                c1, c2 = st.columns(2)
                dhw_morning_hour = c1.slider(
                    "Morning peak hour", 0.0, 23.5, 7.0, step=0.5, key="dhw_morning_hour",
                    help="Hour of day for typical morning shower"
                )
                dhw_evening_hour = c2.slider(
                    "Evening peak hour", 0.0, 23.5, 21.0, step=0.5, key="dhw_evening_hour",
                    help="Hour of day for typical evening usage"
                )
                
                dhw_demand_forecast_full = simulate_dhw_demand(
                    hours, morning_peak_hour=dhw_morning_hour, evening_peak_hour=dhw_evening_hour,
                    morning_peak_energy=dhw_morning_peak_energy, evening_peak_energy=dhw_evening_peak_energy,
                )
                st.plotly_chart(
                    viz.plot_discharge_demand_forecast(hours, dhw_demand_forecast_full),
                    width='stretch', key="chart_dhw_demand_forecast",
                )

                st.markdown("**Control**")
                st.caption("Thermal Power (kW) — set by the optimizer via heat pump setpoint.")
    else:
        dhw_battery_params = None

    st.header("Loads")

    # --- Home Consumption ---
    with st.expander("🏠 Home Consumption", expanded=True):
        st.markdown("**Current state** *(measured, t=0)*")
        load_current_power = st.number_input("Current load power (kW)", value=0.5, min_value=0.0, step=0.1, key="load_current_power")

        st.markdown("**Constraints**")
        st.caption("— (fixed demand; not controllable)")

        st.markdown("**Forecast** — baseline + morning/evening/EV peaks with daily variation")
        c1, c2 = st.columns(2)
        load_baseline = c1.number_input("Baseline demand (kW)", value=0.4, min_value=0.0, key="load_baseline")
        load_baseline_variation = c2.number_input("Baseline variation (kW)", value=0.2, min_value=0.0, key="load_baseline_variation")
        c1, c2, c3 = st.columns(3)
        load_morning_peak_height = c1.number_input("Morning peak height (kW)", value=3.0, min_value=0.0, key="load_morning_peak_height")
        load_evening_peak_height = c2.number_input("Evening peak height (kW)", value=2.0, min_value=0.0, key="load_evening_peak_height")
        load_ev_peak_height = c3.number_input("EV peak height (kW)", value=6.0, min_value=0.0, key="load_ev_peak_height")
        c1, c2, c3 = st.columns(3)
        load_morning_hour = c1.slider("Morning peak hour", 0.0, 23.5, 7.0, step=0.5, key="load_morning_hour")
        load_evening_hour = c2.slider("Evening peak hour", 0.0, 23.5, 21.0, step=0.5, key="load_evening_hour")
        load_ev_peak_hour = c3.slider("EV peak hour", 0.0, 23.5, 18.0, step=0.5, key="load_ev_peak_hour")

        load_forecast_full = simulate_load_demand(
            hours, baseline=load_baseline, morning_peak_hour=load_morning_hour,
            evening_peak_hour=load_evening_hour, ev_peak_hour=load_ev_peak_hour,
            morning_peak_height=load_morning_peak_height, evening_peak_height=load_evening_peak_height,
            ev_peak_height=load_ev_peak_height, baseline_variation=load_baseline_variation,
        )
        st.plotly_chart(viz.plot_load_forecast(hours, load_forecast_full), width='stretch', key="chart_load_forecast")

        st.markdown("**Control**")
        st.caption("None — fixed load, not controllable in this scope.")

# ----------------------------------------------------------------------------
# Assemble assets from current widget values (t=0 overridden with measured value)
# ----------------------------------------------------------------------------
grid = Source(
    "Grid", current_power=grid_current_power,
    max_import_power=grid_max_import, max_export_power=grid_max_export,
    price_forecast=price_forecast_full, export_price_fraction=export_price_fraction,
)
pv = Source(
    "PV", current_power=pv_current_power,
    power_forecast=with_measured_start(pv_forecast_full, pv_current_power),
)

# Build list of enabled storages
storages = []
if battery_1_enabled:
    storages.append(Storage(
        "Battery 1", current_soc=battery1_current_soc, capacity=battery1_capacity,
        min_soc=battery1_min_soc, max_soc=battery1_max_soc,
        max_charge_power=battery1_max_charge, max_discharge_power=battery1_max_discharge,
        passive_discharge_power=battery1_passive_discharge,
        charge_efficiency=battery1_charge_efficiency, discharge_efficiency=battery1_discharge_efficiency,
    ))

if battery_2_enabled:
    storages.append(Storage(
        "Battery 2", current_soc=battery2_current_soc, capacity=battery2_capacity,
        min_soc=battery2_min_soc, max_soc=battery2_max_soc,
        max_charge_power=battery2_max_charge, max_discharge_power=battery2_max_discharge,
        passive_discharge_power=battery2_passive_discharge,
        charge_efficiency=battery2_charge_efficiency, discharge_efficiency=battery2_discharge_efficiency,
    ))

if dhw_tank_enabled and dhw_battery_params:
    storages.append(Storage(
        "DHW Tank", current_soc=dhw_battery_params.current_soc, capacity=dhw_battery_params.capacity_kwh,
        min_soc=dhw_battery_params.min_soc, max_soc=dhw_battery_params.max_soc,
        max_charge_power=dhw_battery_params.max_charge_power_kw, max_discharge_power=dhw_battery_params.max_discharge_power_kw,
        passive_discharge_power=dhw_battery_params.passive_discharge_power_kw,
        charge_efficiency=1.0, discharge_efficiency=1.0,  # No charge/discharge efficiency losses for thermal storage
        demand_forecast=dhw_demand_forecast_full,
    ))

load = Load(
    "Home Consumption", current_power=load_current_power,
    power_forecast=with_measured_start(load_forecast_full, load_current_power),
)

# ----------------------------------------------------------------------------
# Run optimization (local + optional EVCC) on button click
# ----------------------------------------------------------------------------
if run_clicked:
    if not storages:
        st.error("❌ Please enable at least one storage asset in the sidebar.")
    else:
        with st.spinner("Solving..."):
            opt = Optimizer(
                grid, pv, storages, load, hours, dt_hours,
                mode=mode, peak_leveling=peak_leveling, charging_priority=charging_priority,
                solver_tolerance=solver_tolerance, max_iterations=int(max_iterations),
                soft_penalty=soft_penalty,
            )
            st.session_state.result = opt.solve()

            if evcc_enabled:
                # EVCC integration now supports multiple storages (batteries)
                if storages:
                    st.session_state.evcc_result = run_evcc_optimization(
                        grid, pv, storages, load, dt_hours, base_url=evcc_url,
                        prc_p_exc_imp=evcc_prc_p_exc_imp,
                    )
                else:
                    st.session_state.evcc_result = None
            else:
                st.session_state.evcc_result = None

# ============================================================================
# OPTIMIZATION TAB
# ============================================================================
with tab_optimization:
    result = st.session_state.result
    evcc_result = st.session_state.evcc_result

    if result is None:
        st.info("Configure your system in the **Inputs** tab, then click **▶ Run optimization** in the sidebar.")
    else:
        n_cols = 2 if evcc_result is not None else 1
        cols = st.columns(n_cols)

        # ---- Local optimizer column ----
        with cols[0]:
            st.subheader("Local optimizer")

            st.markdown("**Solver info**")
            s1, s2, s3 = st.columns(3)
            s1.metric("Type", "MILP (CBC)")
            s2.metric("Status", result.status)
            s3.metric("Solve time", f"{result.solve_time * 1000:.0f} ms")

            with st.container(height=150, border=False):
                if result.violations:
                    violation_names = ", ".join([v.asset for v in result.violations])
                    total_penalty = sum([v.penalty_cost for v in result.violations])
                    st.warning(
                        f"Constraint violations reported: {violation_names}\n"
                        f"• Total penalty cost: €{total_penalty:.2f}"
                    )
                    st.markdown("**Violation details**")
                    st.dataframe(
                        [
                            {
                                "Asset": v.asset, "Type": v.type,
                                "Max violation": round(v.max_violation, 4),
                                "Penalty cost": round(v.penalty_cost, 2),
                            }
                            for v in result.violations
                        ],
                        width='stretch', hide_index=True,
                    )
                else:
                    st.success("No constraint violations.")

            st.markdown("**Cost metrics**")
            m1, m2, m3 = st.columns(3)
            m1.metric("Energy cost", f"€{result.cost_energy:.2f}")
            m2.metric("Violation penalty", f"€{result.cost_penalty:.2f}")
            m3.metric("Total cost", f"€{result.cost_total:.2f}")

            st.markdown("**Current control commands (t=0)**")
            ctrl_cols = st.columns(len(result.storages) + 2)
            for i, (storage_name, storage_data) in enumerate(result.storages.items()):
                with ctrl_cols[i]:
                    power_t0 = storage_data["power"][0] if len(storage_data["power"]) > 0 else 0.0
                    st.metric(f"{storage_name} power", f"{power_t0:.2f} kW")
            with ctrl_cols[len(result.storages)]:
                st.metric("Grid import", f"{result.grid_import[0]:.2f} kW")
            with ctrl_cols[len(result.storages) + 1]:
                st.metric("Grid export", f"{result.grid_export[0]:.2f} kW")

            st.plotly_chart(
                viz.plot_power_flow(
                    result.hours, result.grid_import, result.grid_export,
                    result.pv_power, load_power=result.load_power,
                    price_import=result.price_import, price_export=result.price_export,
                    storage_dict={name: data["power"] for name, data in result.storages.items()},
                    horizon_hours=horizon_hours,
                ),
                width='stretch', key="chart_power_flow_local",
            )
            st.plotly_chart(
                viz.plot_cost_analysis(
                    result.hours, result.grid_import, result.grid_export,
                    result.price_import, result.price_export,
                    horizon_hours=horizon_hours,
                ),
                width='stretch', key="chart_cost_local",
            )
            
            # Multi-storage SoC trajectories
            hours_ext = np.append(result.hours, result.hours[-1] + dt_hours) if len(result.hours) else result.hours
            
            # Get min/max SoC for each storage
            soc_bounds = {}
            for storage in storages:
                soc_bounds[storage.name] = (storage.min_soc, storage.max_soc)
            
            # Build dict for visualization: {storage_name: soc_array}
            soc_dict = {name: data["soc"] for name, data in result.storages.items()}
            
            st.plotly_chart(
                viz.plot_soc_trajectory_multi(hours_ext, soc_dict, soc_bounds, horizon_hours=horizon_hours),
                width='stretch', key="chart_soc_local",
            )

        # ---- EVCC comparison column ----
        if evcc_result is not None:
            with cols[1]:
                st.subheader("EVCC optimizer")
                if evcc_result.error:
                    st.warning(f"EVCC comparison unavailable: {evcc_result.error}")
                else:
                    st.markdown("**Solver info**")
                    e1, e2 = st.columns(2)
                    e1.metric("Type", "MILP (external service)")
                    e2.metric("Status", evcc_result.status)

                    with st.container(height=150, border=False):
                        if evcc_result.limit_violations:
                            active = {k: v for k, v in evcc_result.limit_violations.items() if v}
                            if active:
                                violation_str = ", ".join(active.keys())
                                total_import_overshoot = np.sum(evcc_result.grid_import_overshoot_kwh)
                                total_export_overshoot = np.sum(evcc_result.grid_export_overshoot_kwh)
                                st.warning(
                                    f"Limit violations reported: {violation_str}\n"
                                    f"• Import overshoot: {total_import_overshoot:.2f} kWh\n"
                                    f"• Export overshoot: {total_export_overshoot:.2f} kWh"
                                )
                            else:
                                st.success("No limit violations reported.")

                    if evcc_result.objective_value is not None:
                        st.markdown("**Cost metrics**")
                        # Calculate energy cost from grid power and price forecasts
                        num_steps = len(evcc_result.grid_import)
                        energy_cost_evcc = float(
                            np.sum(
                                evcc_result.grid_import * result.price_import[:num_steps]
                                - evcc_result.grid_export * result.price_export[:num_steps]
                            )
                            * dt_hours
                        )
                        m1, m2 = st.columns(2)
                        m1.metric("Calculated energy cost", f"€{energy_cost_evcc:.2f}")
                        m2.metric("Objective value", f"€{evcc_result.objective_value:.2f}")

                    if evcc_result.storages:
                        st.markdown("**Current control commands (t=0)**")
                        # Get slice length from first storage
                        first_storage_power = next(iter(evcc_result.storages.values()))["power"]
                        n_evcc = len(first_storage_power)
                        
                        # Display metrics for all storages
                        ctrl_cols = st.columns(len(evcc_result.storages) + 2)
                        for i, (storage_name, storage_data) in enumerate(evcc_result.storages.items()):
                            with ctrl_cols[i]:
                                power_t0 = storage_data["power"][0] if len(storage_data["power"]) > 0 else 0.0
                                st.metric(f"{storage_name} power", f"{power_t0:.2f} kW")
                        with ctrl_cols[len(evcc_result.storages)]:
                            st.metric("Grid import", f"{evcc_result.grid_import[0]:.2f} kW" if len(evcc_result.grid_import) else "—")
                        with ctrl_cols[len(evcc_result.storages) + 1]:
                            st.metric("Grid export", f"{evcc_result.grid_export[0]:.2f} kW" if len(evcc_result.grid_export) else "—")

                        st.plotly_chart(
                            viz.plot_power_flow(
                                result.hours[:n_evcc],
                                evcc_result.grid_import, evcc_result.grid_export,
                                result.pv_power[:n_evcc],
                                load_power=result.load_power[:n_evcc],
                                price_import=result.price_import[:n_evcc],
                                price_export=result.price_export[:n_evcc],
                                storage_dict={name: data["power"] for name, data in evcc_result.storages.items()},
                                horizon_hours=horizon_hours,
                            ),
                            width='stretch', key="chart_power_flow_evcc",
                        )
                        st.plotly_chart(
                            viz.plot_cost_analysis(
                                result.hours[:n_evcc],
                                evcc_result.grid_import, evcc_result.grid_export,
                                result.price_import[:n_evcc],
                                result.price_export[:n_evcc],
                                horizon_hours=horizon_hours,
                            ),
                            width='stretch', key="chart_cost_evcc",
                        )
                        
                        # Multi-storage SoC trajectories from EVCC
                        if evcc_result.storages:
                            hours_ext_evcc = np.append(result.hours[:n_evcc], result.hours[n_evcc - 1] + dt_hours) if n_evcc > 0 else np.array([])
                            
                            # Get min/max SoC bounds for each storage
                            soc_bounds_evcc = {}
                            for storage in storages:
                                soc_bounds_evcc[storage.name] = (storage.min_soc, storage.max_soc)
                            
                            # Build dict for visualization: {storage_name: soc_array}
                            soc_dict_evcc = {name: data["soc"] for name, data in evcc_result.storages.items()}
                            
                            st.plotly_chart(
                                viz.plot_soc_trajectory_multi(hours_ext_evcc, soc_dict_evcc, soc_bounds_evcc, horizon_hours=horizon_hours),
                                width='stretch', key="chart_soc_evcc",
                            )
                    else:
                        st.info("EVCC service returned no battery schedule to display.")

                    with st.expander("Request payload (input)", expanded=False):
                        if evcc_result.payload:
                            st.json(evcc_result.payload)
                        else:
                            st.info("No payload available")

                    with st.expander("Response data (output)", expanded=False):
                        if evcc_result.raw_response:
                            st.json(evcc_result.raw_response)
                        else:
                            st.info("No response data available")

            st.divider()
            st.plotly_chart(
                viz.plot_comparison_power(
                    result.hours, result.grid_import, result.grid_export,
                    evcc_result.grid_import, evcc_result.grid_export,
                ),
                width='stretch', key="chart_comparison",
            )

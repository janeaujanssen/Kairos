"""
Layer 3: Visualization Layer. Plotly chart builders for both input forecasts
(Inputs tab) and optimization results (Optimization tab). Every function
returns a `plotly.graph_objects.Figure` -- callers are responsible for
`st.plotly_chart(...)`.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _layout(fig: go.Figure, title: str, yaxis_title: str, xaxis_title: str = "Time (h)") -> go.Figure:
    fig.update_layout(
        title=title,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        margin=dict(l=40, r=20, t=40, b=40),
        height=280,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def plot_price_forecast(hours: np.ndarray, price_import: np.ndarray, export_price_fraction: float) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hours, y=price_import, mode="lines", name="Import price", line=dict(color="#d62728")))
    fig.add_trace(
        go.Scatter(
            x=hours,
            y=price_import * export_price_fraction,
            mode="lines",
            name="Export price",
            line=dict(color="#2ca02c", dash="dash"),
        )
    )
    return _layout(fig, "Grid price forecast", "EUR/kWh")


def plot_pv_forecast(hours: np.ndarray, pv_power: np.ndarray) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hours, y=pv_power, mode="lines", name="PV production", fill="tozeroy", line=dict(color="#ff7f0e")))
    return _layout(fig, "PV production forecast", "kW")


def plot_load_forecast(hours: np.ndarray, load_power: np.ndarray) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hours, y=load_power, mode="lines", name="Home consumption", fill="tozeroy", line=dict(color="#1f77b4")))
    return _layout(fig, "Load demand forecast", "kW")


def plot_power_flow(
    hours: np.ndarray,
    grid_import: np.ndarray,
    grid_export: np.ndarray,
    pv_power: np.ndarray,
    battery_power: np.ndarray,
    load_power: np.ndarray,
) -> go.Figure:
    """Power flow chart: sources/storage above zero as supply, load as demand line."""
    fig = go.Figure()
    fig.add_trace(go.Bar(x=hours, y=grid_import, name="Grid import", marker_color="#d62728"))
    fig.add_trace(go.Bar(x=hours, y=-grid_export, name="Grid export", marker_color="#2ca02c"))
    fig.add_trace(go.Bar(x=hours, y=pv_power, name="PV production", marker_color="#ff7f0e"))
    fig.add_trace(go.Bar(x=hours, y=-battery_power, name="Battery (+discharge/-charge shown)", marker_color="#9467bd"))
    fig.add_trace(go.Scatter(x=hours, y=load_power, mode="lines", name="Load", line=dict(color="#1f77b4", width=3)))
    fig.update_layout(barmode="relative")
    return _layout(fig, "Power flow", "kW")


def plot_soc_trajectory(
    hours_extended: np.ndarray,
    soc: np.ndarray,
    min_soc: float,
    max_soc: float,
    name: str = "Battery SoC",
) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hours_extended, y=soc * 100, mode="lines+markers", name=name, line=dict(color="#9467bd")))
    fig.add_hline(y=min_soc * 100, line_dash="dot", line_color="red", annotation_text="min SoC")
    fig.add_hline(y=max_soc * 100, line_dash="dot", line_color="red", annotation_text="max SoC")
    fig.update_yaxes(range=[-5, 105])
    return _layout(fig, "State of charge trajectory", "SoC (%)")


def plot_cost_breakdown(cost_energy: float, cost_penalty: float) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=["Energy cost", "Violation penalty", "Total"],
            y=[cost_energy, cost_penalty, cost_energy + cost_penalty],
            marker_color=["#1f77b4", "#d62728", "#7f7f7f"],
        )
    )
    return _layout(fig, "Cost breakdown", "EUR", xaxis_title="")


def plot_comparison_power(
    hours: np.ndarray,
    local_grid_import: np.ndarray,
    local_grid_export: np.ndarray,
    evcc_grid_import: np.ndarray,
    evcc_grid_export: np.ndarray,
) -> go.Figure:
    """Overlay local vs. EVCC net grid power for a quick visual comparison."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hours, y=local_grid_import - local_grid_export, mode="lines",
            name="Local optimizer", line=dict(color="#1f77b4", width=3),
        )
    )
    if len(evcc_grid_import) == len(hours):
        fig.add_trace(
            go.Scatter(
                x=hours, y=evcc_grid_import - evcc_grid_export, mode="lines",
                name="EVCC optimizer", line=dict(color="#ff7f0e", width=3, dash="dash"),
            )
        )
    return _layout(fig, "Net grid power: local vs. EVCC", "kW")

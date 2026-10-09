"""Manually checked: Chart visualization functions for Kairos UI."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Color scheme per UI architecture
ASSET_COLORS = {
    "grid": ["#000000", "#000000", "#000000"],
    "pv": ["#ff8f0e", "#ff8f0e", "#ff8f0e"],
    "base_load": ["#687385", "#a3acba", "#d5dbe1"],
    "controllable_load": ["#844cef", "#b39cfd", "#dcd4fe"],
    "battery": ["#008434", "#00c652", "#89f09b"],
    "dhw_tank": ["#0570de", "#06b9ef", "#a2e5ef"],
    "building_thermal_mass": ["#906a5d", "#c2a89f", "#e4d9d5"],
    "ev_battery": ["#c722a3", "#e78acb", "#f5cde7"],
}

COST_COLORS = {
    "cost": "#ff8c7e",
    "profit": "#3cce9c",
    "cumulative": "#0570de",
}

GRAY = "#7f7f7f"


def asset_color(asset_type: str, instance_index: int = 0) -> str:
    """Return the palette color for an asset type and its zero-based instance index."""
    palette_key = "battery" if asset_type == "home_battery" else asset_type
    palette = ASSET_COLORS[palette_key]
    return palette[instance_index % len(palette)]


def _storage_color_indices(storage_ids: list[str], storage_types_by_id: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    indices = {}
    for storage_id in storage_ids:
        asset_type = storage_types_by_id.get(storage_id, "home_battery")
        indices[storage_id] = counts.get(asset_type, 0)
        counts[asset_type] = indices[storage_id] + 1
    return indices


def style(fig: go.Figure, y_axis_title: str, height_px: int = 300) -> go.Figure:
    """Apply consistent layout styling to a Plotly figure per UI architecture."""
    fig.update_layout(
        height=height_px,
        hovermode="x unified",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis_title=y_axis_title,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return fig


def show(fig: go.Figure) -> None:
    """Display a Plotly figure in Streamlit."""
    st.plotly_chart(fig, width="stretch")


def area_chart(timestamps, power_w: list[float], series_name: str, color: str, unit: str = "W") -> go.Figure:
    """Create a filled area chart."""
    fig = go.Figure(go.Scatter(
        x=timestamps, y=power_w, name=series_name, fill="tozeroy", line_color=color, line_shape="hv",
        hovertemplate="%{y:.1f} " + unit + "<extra></extra>"
    ))
    return style(fig, unit)


def bar_chart(timestamps, values: list[float], series_name: str, color: str, unit: str = "Wh") -> go.Figure:
    """Create a bar chart."""
    fig = go.Figure(go.Bar(
        x=timestamps, y=values, name=series_name, marker_color=color,
        hovertemplate="%{y:.1f} " + unit + "<extra></extra>"
    ))
    return style(fig, unit)


def power_flow_chart(
    timestamps, load_w: list[float], storage_ids: list[str], storage_schedule_w: dict[str, list[float]],
    net_grid_w: list[float], pv_w: list[float], import_price: list[float], export_price: list[float],
    storage_types_by_id: dict[str, str] | None = None,
    controllable_ids: list[str] | None = None,
) -> go.Figure:
    """Create power flow chart with load, storage, and grid per UI architecture."""
    fig = go.Figure()
    storage_types_by_id = storage_types_by_id or {}
    controllable_ids = controllable_ids or []
    color_indices = _storage_color_indices(storage_ids, storage_types_by_id)

    # Zero line reference
    fig.add_hline(y=0, line_dash="dash", line_color=GRAY, layer="below")

    # Home Load (Base Load) - supply side demand
    fig.add_bar(x=timestamps, y=load_w, name="Home Load", marker_color=asset_color("base_load"),
                hovertemplate="%{y:.1f} W<extra></extra>")

    # Controllable loads - one bar per asset so each instance can use its palette color
    for color_index, controllable_id in enumerate(controllable_ids):
        if controllable_id not in storage_schedule_w:
            continue
        fig.add_bar(
            x=timestamps, y=storage_schedule_w[controllable_id], name=controllable_id,
            marker_color=asset_color("controllable_load", color_index),
            hovertemplate="%{y:.1f} W<extra></extra>",
        )
    
    # Storage assets - demand side
    for storage_id in storage_ids:
        asset_type = storage_types_by_id.get(storage_id, "home_battery")
        color = asset_color(asset_type, color_indices[storage_id])
        fig.add_bar(x=timestamps, y=storage_schedule_w[storage_id], name=storage_id, marker_color=color,
                    hovertemplate="%{y:.1f} W<extra></extra>")
    
    # Supply side - Grid and PV (lines)
    fig.add_scatter(x=timestamps, y=net_grid_w, name="Net Grid Power", line=dict(color=asset_color("grid")), line_shape="hvh",
                    hovertemplate="%{y:.1f} W<extra></extra>")
    fig.add_scatter(x=timestamps, y=pv_w, name="PV Production", line=dict(color=asset_color("pv")), line_shape="hvh",
                    hovertemplate="%{y:.1f} W<extra></extra>")
    

    
    # Prices on secondary y-axis (convert from price/Wh to price/kWh by multiplying by 1000)
    import_price_kwh = [p * 1000 for p in import_price]
    export_price_kwh = [p * 1000 for p in export_price]
    fig.add_scatter(x=timestamps, y=import_price_kwh, name="Import price", yaxis="y2", 
                    line=dict(color=COST_COLORS["cost"], dash="solid"), line_shape="spline",
                    hovertemplate="%{y:.3f} price/kWh<extra></extra>")
    fig.add_scatter(x=timestamps, y=export_price_kwh, name="Export price", yaxis="y2", 
                    line=dict(color=COST_COLORS["profit"], dash="solid"), line_shape="spline",
                    hovertemplate="%{y:.3f} price/kWh<extra></extra>")
    
    fig.update_layout(
        barmode="relative", 
        yaxis2=dict(title="price/kWh", overlaying="y", side="right", showgrid=False)
    )
    return style(fig, "W", 400)


def grid_step_costs(
    net_grid_w: list[float], import_price: list[float], export_price: list[float], step_hours: float
) -> list[float]:
    """Return net grid energy cost per timestep, with export revenue as negative cost."""
    return [
        (max(g, 0) * import_price[i] - max(-g, 0) * export_price[i]) * step_hours for i, g in enumerate(net_grid_w)
    ]


def cost_analysis_chart(
    timestamps, net_grid_w: list[float], import_price: list[float], export_price: list[float], step_hours: float
) -> go.Figure:
    """Create cost analysis chart with grid costs and cumulative cost per UI architecture."""
    step_cost = grid_step_costs(net_grid_w, import_price, export_price, step_hours)
    cumulative_cost = pd.Series(step_cost).cumsum().tolist()
    fig = go.Figure()

    fig.add_hline(y=0, line_dash="dash", line_color=GRAY, layer="below")
    
    # Grid cost (import) - positive values
    fig.add_bar(x=timestamps, y=[max(c, 0) for c in step_cost], name="Grid cost", marker_color=COST_COLORS["cost"],
                hovertemplate="%{y:.2f}<extra></extra>")
    
    # Grid profit (export) - negative values
    fig.add_bar(x=timestamps, y=[min(c, 0) for c in step_cost], name="Grid profit", marker_color=COST_COLORS["profit"],
                hovertemplate="%{y:.2f}<extra></extra>")
    
    # Cumulative cost line on secondary y-axis
    fig.add_scatter(x=timestamps, y=cumulative_cost, name="Cumulative cost", yaxis="y2", 
                    line=dict(color=COST_COLORS["cumulative"]), line_shape="hv",
                    hovertemplate="%{y:.2f}<extra></extra>")
    

    fig.update_layout(
        barmode="relative", 
        yaxis2=dict(title="cumulative", overlaying="y", side="right", showgrid=False)
    )
    return style(fig, "cost", 350)


def soc_chart(
    timestamps, storage_ids: list[str], soc_by_storage: dict[str, list[float]], generics_by_id: dict,
    storage_types_by_id: dict[str, str] | None = None,
) -> go.Figure:
    """Create state of charge trajectories chart for all storage assets per UI architecture."""
    fig = go.Figure()
    storage_types_by_id = storage_types_by_id or {}
    color_indices = _storage_color_indices(storage_ids, storage_types_by_id)
    
    for storage_id in storage_ids:
        if storage_id not in soc_by_storage:
            continue
        generic = generics_by_id.get(storage_id)
        if generic is None:
            continue
        asset_type = storage_types_by_id.get(storage_id, "home_battery")
        color = asset_color(asset_type, color_indices[storage_id])
        soc = soc_by_storage[storage_id]
        fig.add_scatter(
            x=timestamps, y=[v * 100 for v in soc], name=storage_id, line=dict(color=color), line_shape="linear",
            customdata=[v * generic.energy_capacity / 1000 for v in soc],
            hovertemplate="%{y:.1f} %  (%{customdata:.2f} kWh)",
        )
        for bound, label in ((generic.min_soc, "min"), (generic.max_soc, "max")):
            fig.add_hline(y=bound * 100, line_dash="dot", line_color=color,
                          annotation_text=f"{storage_id} {label}", annotation_position="right")
    return style(fig, "SoC [%]", 350)


def forecast_chart(
    asset_type: str, payload: dict, generic, timestamps, forecast: dict = None, color_index: int = 0
) -> go.Figure | None:
    """Forecast chart for assets that have time-series forecasts."""
    if asset_type == "grid" and forecast:
        # Convert prices back from $/Wh to $/kWh for display (multiply by 1000)
        import_prices_kwh = [p * 1000 for p in payload["import_price_forecast"]]
        export_prices_kwh = [p * 1000 for p in payload["export_price_forecast"]]
        fig = go.Figure()
        fig.add_scatter(x=timestamps, y=import_prices_kwh, name="Import price",
                        line=dict(color=COST_COLORS["cost"]), line_shape="hv",
                        hovertemplate="%{y:.3f} price/kWh<extra></extra>")
        fig.add_scatter(x=timestamps, y=export_prices_kwh, name="Export price",
                        line=dict(color=COST_COLORS["profit"], dash="solid"), line_shape="hv",
                        hovertemplate="%{y:.3f} price/kWh<extra></extra>")
        return style(fig, "price/kWh")
    if asset_type == "pv":
        return area_chart(timestamps, payload["power_forecast"], "PV power forecast", asset_color(asset_type, color_index), unit="W")
    if asset_type == "base_load":
        return area_chart(timestamps, payload["power_forecast"], "Base load power forecast", asset_color(asset_type, color_index), unit="W")
    if asset_type == "ev_battery" and generic is not None:
        return bar_chart(timestamps, generic.energy_demand_forecast, "EV energy demand forecast", asset_color(asset_type, color_index), unit="Wh")
    if asset_type == "dhw_tank" and generic is not None:
        return bar_chart(timestamps, generic.energy_demand_forecast, "DHW energy demand forecast", asset_color(asset_type, color_index), unit="Wh")
    return None

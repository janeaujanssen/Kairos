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
        xaxis=dict(domain=[0.02, 0.95]),  # Fixed plot area width regardless of y-axis label length
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


def plot_discharge_demand_forecast(hours: np.ndarray, discharge_demand_energy: np.ndarray) -> go.Figure:
    """Plot discharge demand forecast (energy per timestep, not power).
    
    This represents energy withdrawn from storage (e.g., hot water demand, EV departure goal),
    not electrical load demand. Distinguished from load_power_forecast which is grid demand.
    
    Args:
        hours: Time array (hours)
        discharge_demand_energy: Discharge demand in kWh per timestep (not power)
    """
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=hours, y=discharge_demand_energy,
        name="Discharge demand", marker=dict(color="#ff7f0e"),
        hovertemplate="<b>Discharge demand</b><br>%{y:.2f} kWh<extra></extra>"
    ))
    return _layout(fig, "Discharge demand forecast", "kWh per timestep")


def plot_power_flow(
    hours: np.ndarray,
    grid_import: np.ndarray,
    grid_export: np.ndarray,
    pv_power: np.ndarray,
    battery_power: np.ndarray = None,
    load_power: np.ndarray = None,
    price_import: np.ndarray = None,
    price_export: np.ndarray = None,
    storage_dict: dict = None,
    horizon_hours: float = 24.0,
) -> go.Figure:
    """Hybrid power flow chart showing energy balance: Grid + PV = Load + Storage(s).
    
    Supply side (lines): Grid Power (net) and PV Power shown as separate line traces.
    Demand side (stacked bars): Load Power and Storage Power(s) as separate bar traces.
    With barmode="relative": same-signed bars stack together (e.g. Load + Storage charging),
    while discharging Storage (negative) stacks separately below zero.
    Prices shown as secondary y-axis lines (if provided).
    
    Args:
        storage_dict: Optional {storage_name: power_array} for multiple storages.
                      If provided, battery_power is ignored.
    """
    # Calculate net grid power (positive = import, negative = export)
    net_grid_power = grid_import - grid_export
    
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # SUPPLY SIDE: Show as lines (easier to see individual trends)
    fig.add_trace(
        go.Scatter(
            x=hours, y=net_grid_power,
            name="Grid Power",
            mode="lines",
            line=dict(color="#d62728", width=2),
            hovertemplate="<b>Grid Power</b><br>%{y:.2f} kW<extra></extra>",
        ),
        secondary_y=False
    )
    
    fig.add_trace(
        go.Scatter(
            x=hours, y=pv_power,
            name="PV Production",
            mode="lines",
            line=dict(color="#ff7f0e", width=2),
            hovertemplate="<b>PV Production</b><br>%{y:.2f} kW<extra></extra>",
        ),
        secondary_y=False
    )
    
    # DEMAND SIDE: Load and Storage(s) as separate stacked bars.
    # barmode="relative" stacks positive values together and negative values together,
    # so discharging storage never stacks on top of Load.
    if load_power is not None:
        fig.add_trace(
            go.Bar(
                x=hours, y=load_power,
                name="Home Load",
                marker=dict(color="#1f77b4"),
                hovertemplate="<b>Home Load</b><br>%{y:.2f} kW<extra></extra>",
            ),
            secondary_y=False
        )
    
    # Plot storage(s)
    storage_colors = ["#9467bd", "#ff7f0e", "#2ca02c", "#d62728"]
    
    if storage_dict:
        # Multiple storages: plot each with different color
        for i, (storage_name, power_array) in enumerate(storage_dict.items()):
            color = storage_colors[i % len(storage_colors)]
            fig.add_trace(
                go.Bar(
                    x=hours, y=power_array,
                    name=f"{storage_name} (+charge/-discharge)",
                    marker=dict(color=color),
                    hovertemplate=f"<b>{storage_name}</b><br>" + "%{y:.2f} kW<extra></extra>",
                ),
                secondary_y=False
            )
    elif battery_power is not None:
        # Legacy single battery
        fig.add_trace(
            go.Bar(
                x=hours, y=battery_power,
                name="Battery (+charge/-discharge)",
                marker=dict(color="#9467bd"),
                hovertemplate="<b>Battery</b><br>%{y:.2f} kW<extra></extra>",
            ),
            secondary_y=False
        )
    
    # Optional: Add price traces on secondary y-axis if provided
    if price_import is not None:
        fig.add_trace(
            go.Scatter(
                x=hours, y=price_import,
                name="Import Price",
                mode="lines",
                line=dict(color="#d62728", width=1, dash="dot"),
                hovertemplate="<b>Import Price</b><br>%{y:.3f} €/kWh<extra></extra>",
            ),
            secondary_y=True
        )
    
    if price_export is not None:
        fig.add_trace(
            go.Scatter(
                x=hours, y=price_export,
                name="Export Price",
                mode="lines",
                line=dict(color="#2ca02c", width=1, dash="dot"),
                hovertemplate="<b>Export Price</b><br>%{y:.3f} €/kWh<extra></extra>",
            ),
            secondary_y=True
        )
    
    # Create layout with dual y-axes if prices provided
    layout_update = {
        "title": "Power Flow",
        "xaxis_title": "Time (h)",
        "barmode": "relative",
        "height": 400,
        "margin": dict(l=40, r=20, t=40, b=40),
        "legend": dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        "hovermode": "x unified",
        "xaxis": dict(domain=[0.02, 0.95], range=[0, horizon_hours]),  # Fixed plot area width, dynamic x-axis range
    }
    
    # Configure y-axes
    layout_update["yaxis"] = dict(title="Power (kW)", side="left")
    if price_import is not None or price_export is not None:
        layout_update["yaxis2"] = dict(title="Price (€/kWh)", overlaying="y", side="right")
    
    fig.update_layout(**layout_update)
    
    # Add a zero line to visually emphasize the balance
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(128, 128, 128, 0.3)", line_width=1)
    
    return fig




def plot_soc_trajectory_multi(
    hours_extended: np.ndarray,
    soc_dict: dict,
    bounds_dict: dict,
    horizon_hours: float = 24.0,
) -> go.Figure:
    """Plot SoC trajectories for multiple storage assets.
    
    Args:
        hours_extended: Time array (includes t=0 through t=T)
        soc_dict: {storage_name: soc_array} where soc_array is normalized 0-1
        bounds_dict: {storage_name: (min_soc, max_soc)} with normalized bounds
    """
    fig = go.Figure()
    
    # Color palette for multiple storage assets
    colors = ["#9467bd", "#ff7f0e", "#2ca02c", "#d62728", "#1f77b4"]
    
    # Plot each storage asset
    for i, (storage_name, soc_array) in enumerate(soc_dict.items()):
        color = colors[i % len(colors)]
        min_soc, max_soc = bounds_dict.get(storage_name, (0.0, 1.0))
        
        fig.add_trace(
            go.Scatter(
                x=hours_extended, y=soc_array * 100, mode="lines+markers",
                name=storage_name, line=dict(color=color, width=2),
                hovertemplate="<b>" + storage_name + "</b><br>%{y:.1f}%<extra></extra>",
            )
        )
        fig.add_hline(y=min_soc * 100, line_dash="dot", line_color=color,
                      annotation_text=f"{storage_name} min", annotation_position="right")
        fig.add_hline(y=max_soc * 100, line_dash="dot", line_color=color,
                      annotation_text=f"{storage_name} max", annotation_position="right")
    
    fig.update_yaxes(range=[-5, 105])
    
    fig.update_layout(
        title="State of Charge Trajectories",
        xaxis_title="Time (h)",
        yaxis_title="SoC (%)",
        margin=dict(l=40, r=20, t=40, b=40),
        height=350,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        xaxis=dict(domain=[0.02, 0.95], range=[0, horizon_hours]),  # Fixed plot area width, dynamic x-axis range
    )
    
    return fig


def plot_cost_analysis(
    hours: np.ndarray,
    grid_import: np.ndarray,
    grid_export: np.ndarray,
    price_import: np.ndarray,
    price_export: np.ndarray,
    horizon_hours: float = 24.0,
) -> go.Figure:
    """Plot cost analysis: per-interval cost bars + cumulative cost line with profit/loss indication.
    
    Args:
        hours: Time array (hours)
        grid_import: Grid import power per interval (kW)
        grid_export: Grid export power per interval (kW)
        price_import: Import price per interval (€/kWh)
        price_export: Export price per interval (€/kWh)
    """
    # Calculate time interval in hours from the hours array
    dt_hours = hours[1] - hours[0] if len(hours) > 1 else 1.0
    
    # Calculate cost per interval (€)
    # Positive = cost (importing), Negative = profit (exporting)
    # Must multiply by dt_hours to convert from power (kW) × price (€/kWh) to energy cost (€)
    cost_per_interval = (grid_import * price_import - grid_export * price_export) * dt_hours
    cumulative_cost = np.cumsum(cost_per_interval)
    
    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Bar chart for per-interval cost (colored by profit/loss)
    colors = ["#d62728" if c > 0 else "#2ca02c" for c in cost_per_interval]
    fig.add_trace(
        go.Bar(
            x=hours, y=cost_per_interval,
            name="Cost per interval",
            marker=dict(color=colors),
            hovertemplate="<b>Cost per interval</b><br>€%{y:.2f}<extra></extra>",
        ),
        secondary_y=False
    )
    
    # Line chart for cumulative cost (always blue)
    fig.add_trace(
        go.Scatter(
            x=hours, y=cumulative_cost,
            name="Cumulative cost",
            mode="lines",
            line=dict(color="#1f77b4", width=2),
            hovertemplate="<b>Cumulative cost</b><br>€%{y:.2f}<extra></extra>",
        ),
        secondary_y=True
    )
    
    # Add zero line for reference
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(128, 128, 128, 0.3)", line_width=1)
    
    fig.update_layout(
        title="Cost Analysis (Red=Cost, Green=Profit)",
        xaxis_title="Time (h)",
        margin=dict(l=40, r=20, t=40, b=40),
        height=350,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        xaxis=dict(domain=[0.02, 0.95], range=[0, horizon_hours]),  # Fixed plot area width, dynamic x-axis range
    )
    
    fig.update_yaxes(title_text="Cost per Interval (€)", secondary_y=False)
    fig.update_yaxes(title_text="Cumulative Cost (€)", secondary_y=True)
    
    return fig



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

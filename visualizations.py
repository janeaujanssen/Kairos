"""Chart visualization functions for Kairos UI."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

RED, GREEN, ORANGE, BLUE, PURPLE, GRAY = "#d62728", "#2ca02c", "#ff7f0e", "#1f77b4", "#9467bd", "#7f7f7f"
SOC_COLORS = [PURPLE, ORANGE, GREEN, RED, BLUE]


def style(fig: go.Figure, y_axis_title: str, height_px: int = 300) -> go.Figure:
    """Apply consistent layout styling to a Plotly figure."""
    fig.update_layout(
        height=height_px,
        hovermode="x unified",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis_title=y_axis_title,
    )
    return fig


def show(fig: go.Figure) -> None:
    """Display a Plotly figure in Streamlit."""
    st.plotly_chart(fig, width="stretch")


def area_chart(timestamps, power_w: list[float], series_name: str, color: str) -> go.Figure:
    """Create a filled area chart."""
    fig = go.Figure(go.Scatter(x=timestamps, y=power_w, name=series_name, fill="tozeroy", line_color=color, line_shape="hv"))
    return style(fig, "W")


def bar_chart(timestamps, values: list[float], series_name: str, color: str, unit: str = "Wh") -> go.Figure:
    """Create a bar chart."""
    return style(go.Figure(go.Bar(x=timestamps, y=values, name=series_name, marker_color=color)), unit)


def power_flow_chart(
    timestamps, load_w: list[float], storage_ids: list[str], storage_schedule_w: dict[str, list[float]],
    net_grid_w: list[float], pv_w: list[float], import_price: list[float], export_price: list[float]
) -> go.Figure:
    """Create power flow chart with load, storage, and grid."""
    fig = go.Figure()
    fig.add_bar(x=timestamps, y=load_w, name="Home load", marker_color=BLUE)
    for i, storage_id in enumerate(storage_ids):
        fig.add_bar(x=timestamps, y=storage_schedule_w[storage_id], name=storage_id, marker_color=SOC_COLORS[i % len(SOC_COLORS)])
    fig.add_scatter(x=timestamps, y=net_grid_w, name="Net grid", line=dict(color=RED), line_shape="hv")
    fig.add_scatter(x=timestamps, y=pv_w, name="PV", line=dict(color=ORANGE), line_shape="hv")
    fig.add_hline(y=0, line_dash="dash", line_color=GRAY)
    fig.add_scatter(x=timestamps, y=import_price, name="Import price", yaxis="y2", line=dict(color=RED, dash="dot", width=1))
    fig.add_scatter(x=timestamps, y=export_price, name="Export price", yaxis="y2", line=dict(color=GREEN, dash="dot", width=1))
    fig.update_layout(barmode="relative", yaxis2=dict(title="price/Wh", overlaying="y", side="right", showgrid=False))
    return style(fig, "W", 400)


def cost_analysis_chart(
    timestamps, net_grid_w: list[float], import_price: list[float], export_price: list[float], step_hours: float
) -> go.Figure:
    """Create cost analysis chart with grid costs and cumulative cost."""
    step_cost = [
        (max(g, 0) * import_price[i] - max(-g, 0) * export_price[i]) * step_hours for i, g in enumerate(net_grid_w)
    ]
    cumulative_cost = pd.Series(step_cost).cumsum().tolist()
    fig = go.Figure()
    fig.add_bar(x=timestamps, y=[max(c, 0) for c in step_cost], name="Grid cost", marker_color=RED)
    fig.add_bar(x=timestamps, y=[min(c, 0) for c in step_cost], name="Grid profit", marker_color=GREEN)
    fig.add_scatter(x=timestamps, y=cumulative_cost, name="Cumulative cost", yaxis="y2", line=dict(color=BLUE))
    fig.add_hline(y=0, line_dash="dash", line_color=GRAY)
    fig.update_layout(barmode="relative", yaxis2=dict(title="cumulative", overlaying="y", side="right", showgrid=False))
    return style(fig, "cost", 350)


def soc_chart(
    timestamps, storage_ids: list[str], soc_by_storage: dict[str, list[float]], generics_by_id: dict
) -> go.Figure:
    """Create state of charge trajectories chart for all storage assets."""
    fig = go.Figure()
    for i, storage_id in enumerate(storage_ids):
        if storage_id not in soc_by_storage:
            continue
        generic = generics_by_id.get(storage_id)
        if generic is None:
            continue
        color = SOC_COLORS[i % len(SOC_COLORS)]
        soc = soc_by_storage[storage_id]
        fig.add_scatter(
            x=timestamps, y=[v * 100 for v in soc], name=storage_id, line=dict(color=color), line_shape="hv",
            customdata=[v * generic.energy_capacity / 1000 for v in soc],
            hovertemplate="%{y:.1f} %  (%{customdata:.2f} kWh)",
        )
        for bound, label in ((generic.min_soc, "min"), (generic.max_soc, "max")):
            fig.add_hline(y=bound * 100, line_dash="dot", line_color=color,
                          annotation_text=f"{storage_id} {label}", annotation_position="right")
    return style(fig, "SoC [%]", 350)

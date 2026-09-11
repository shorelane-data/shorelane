"""Plotly figure builders for the FP&A subscriptions page."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from bi.plotly import figures as fg

GEN_COLORS = {1: "#94a3b8", 2: "#60a5fa", 3: fg.PRIMARY}
SEG_COLORS = {"smb": fg.TEAL, "enterprise": fg.PRIMARY}


def fig_active_by_generation(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for g in (1, 2, 3):
        fig.add_trace(go.Scatter(x=df.month, y=df[f"active_gen{g}"], name=f"Generation {g}", stackgroup="one",
                                 mode="lines", line=dict(width=0.5, color=GEN_COLORS[g]),
                                 hovertemplate="%{x|%b %Y}<br>Gen " + str(g) + ": %{y:,}<extra></extra>"))
    fig.add_trace(go.Scatter(x=df.month, y=df.active_subscribers, name="Total (deduplicated)", mode="lines",
                             line=dict(color=fg.SLATE, width=2, dash="dot"),
                             hovertemplate="%{x|%b %Y}<br>Total: %{y:,}<extra></extra>"))
    return fg.style_fig(fig, 320)


def fig_starts_renewals_churn(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df.month, y=df.new_starts, name="New subscriptions", marker_color=fg.TEAL,
                         hovertemplate="%{x|%b %Y}<br>New: %{y:,}<extra></extra>"))
    fig.add_trace(go.Bar(x=df.month, y=df.renewals, name="Renewals", marker_color=fg.PRIMARY,
                         hovertemplate="%{x|%b %Y}<br>Renewals: %{y:,}<extra></extra>"))
    fig.add_trace(go.Bar(x=df.month, y=-df.churned_terms, name="Churned", marker_color=fg.RED,
                         hovertemplate="%{x|%b %Y}<br>Churned: %{customdata:,}<extra></extra>", customdata=df.churned_terms))
    fig.update_layout(barmode="relative")
    return fg.style_fig(fig, 300)


def fig_churn_rate_by_segment(q: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for seg, color in SEG_COLORS.items():
        s = q[q.segment == seg]
        fig.add_trace(go.Scatter(x=s.quarter, y=s.churn_rate, name=seg, mode="lines+markers",
                                 line=dict(color=color, width=2.5),
                                 hovertemplate="%{x|%b %Y} quarter<br>" + seg + " churn: %{y:.1%}<extra></extra>"))
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    return fg.style_fig(fig, 300)


def fig_acv_per_seat(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(x=df.month, y=df.acv_per_seat_new, mode="lines", line=dict(color=fg.PRIMARY, width=2.5),
                               hovertemplate="%{x|%b %Y}<br>ACV/seat (new): $%{y:,.2f}<extra></extra>"))
    fig.update_yaxes(tickprefix="$")
    fig.update_layout(showlegend=False)
    return fg.style_fig(fig, 260)


def fig_acv_under_contract(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(x=df.month, y=df.acv_under_contract, mode="lines", fill="tozeroy",
                               line=dict(color=fg.PRIMARY, width=2), fillcolor="rgba(37,99,235,0.12)",
                               hovertemplate="%{x|%b %Y}<br>ACV under contract: $%{y:,.0f}<extra></extra>"))
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    fig.update_layout(showlegend=False)
    return fg.style_fig(fig, 260)

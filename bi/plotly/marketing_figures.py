"""Plotly figure builders for the marketing dashboard (GMV-first view)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config
from bi.plotly import figures as fg

CATEGORY_COLORS = {
    "paper": "#2563eb", "writing": "#0d9488", "office_tech": "#7c3aed",
    "furniture": "#f59e0b", "breakroom": "#db2777", "storage": "#64748b",
}


def fig_gmv_by_channel(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for col, label, color in (("gmv_subscription", "Business Subscriptions", fg.PRIMARY),
                              ("gmv_d2c", "Direct-to-Consumer", fg.TEAL),
                              ("gmv_marketplace", "Marketplace", fg.AMBER)):
        fig.add_trace(go.Bar(x=df.month, y=df[col], name=label, marker_color=color,
                             hovertemplate="%{x|%b %Y}<br>" + label + ": $%{y:,.0f}<extra></extra>"))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    return fg.style_fig(fig, 320)


def fig_consumer_orders_aov(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=df.month, y=df.consumer_orders, name="Consumer orders", marker_color=fg.AMBER,
                         hovertemplate="%{x|%b %Y}<br>Orders: %{y:,}<extra></extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(x=df.month, y=df.aov, name="AOV", mode="lines", line=dict(color=fg.PRIMARY, width=2.5),
                             hovertemplate="%{x|%b %Y}<br>AOV: $%{y:,.2f}<extra></extra>"), secondary_y=True)
    fig.update_yaxes(tickprefix="$", secondary_y=True, showgrid=False)
    return fg.style_fig(fig, 300)


def fig_spend_vs_new(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=df.month, y=df.ad_spend, name="Ad spend", marker_color="#c7d2fe",
                         hovertemplate="%{x|%b %Y}<br>Spend: $%{y:,.0f}<extra></extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(x=df.month, y=df.new_d2c_customers, name="New d2c customers", mode="lines",
                             line=dict(color=fg.TEAL, width=2.5),
                             hovertemplate="%{x|%b %Y}<br>New d2c customers: %{y:,}<extra></extra>"), secondary_y=True)
    fig.update_yaxes(tickprefix="$", tickformat="~s", secondary_y=False)
    fig.update_yaxes(showgrid=False, secondary_y=True)
    return fg.style_fig(fig, 300)


def fig_cac(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(x=df.month, y=df.cac, mode="lines+markers", line=dict(color=fg.RED, width=2),
                               hovertemplate="%{x|%b %Y}<br>CAC: $%{y:,.2f}<extra></extra>"))
    fig.update_yaxes(tickprefix="$")
    fig.update_layout(showlegend=False)
    return fg.style_fig(fig, 260)


def fig_category_mix(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for cat in config.CATEGORIES:
        col = f"cat_{cat}"
        if col not in df.columns:
            continue
        fig.add_trace(go.Bar(x=df.month, y=df[col], name=cat, marker_color=CATEGORY_COLORS[cat],
                             hovertemplate="%{x|%b %Y}<br>" + cat + ": $%{y:,.0f}<extra></extra>"))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    return fg.style_fig(fig, 300)


def fig_category_margin(cats: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=cats.category, y=cats.margin_pct, marker_color=[CATEGORY_COLORS[c] for c in cats.category],
        text=[f"{v * 100:.0f}%" for v in cats.margin_pct], textposition="outside",
        hovertemplate="%{x}<br>Margin: %{y:.1%}<extra></extra>",
    ))
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    fig.update_layout(showlegend=False)
    return fg.style_fig(fig, 260)


def fig_promo_orders(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=df.month, y=df.promo_orders, name="Orders with a promo code", marker_color="#fbbf24",
                         hovertemplate="%{x|%b %Y}<br>Promo orders: %{y:,}<extra></extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(x=df.month, y=df.discount_dollars, name="Discount $", mode="lines",
                             line=dict(color=fg.RED, width=2),
                             hovertemplate="%{x|%b %Y}<br>Discount: $%{y:,.0f}<extra></extra>"), secondary_y=True)
    fig.update_yaxes(tickprefix="$", tickformat="~s", secondary_y=True, showgrid=False)
    return fg.style_fig(fig, 280)

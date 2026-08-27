"""
Plotly figure builders for the customers dashboard, styled to match
bi/plotly/figures.py (same palette, same fixed channel->color assignment) so the
customers page and the executive page read as one system. All figures are
derived from bi/customers_data.py frames — canonical customer grain only.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from bi.plotly import figures as fg

# Fixed channel -> (label, color) assignment, matching fg.CHANNEL_COLORS.
CHANNEL_SERIES = (
    ("business_subscription", "Business Subscriptions", fg.PRIMARY),
    ("d2c", "Direct-to-Consumer", fg.TEAL),
    ("marketplace", "Marketplace", fg.AMBER),
)
DEDUP_LABEL = "All channels (deduplicated)"

STATUS_COLORS = {
    "resolved": fg.GREEN,
    "unresolved_migration_gap": fg.RED,
    "unresolved_sync_lag": fg.AMBER,
}


def fig_current_customers(df: pd.DataFrame) -> go.Figure:
    """The headline: monthly current customers per channel plus the deduplicated
    total (one customer active in two channels counts once in the slate line)."""
    cols = {
        "business_subscription": "current_subscribers",
        "d2c": "current_d2c",
        "marketplace": "current_marketplace",
    }
    fig = go.Figure()
    for ch, label, color in CHANNEL_SERIES:
        fig.add_trace(
            go.Scatter(
                x=df.month, y=df[cols[ch]], name=label, mode="lines",
                line=dict(color=color, width=2.5),
                hovertemplate="%{x|%b %Y}<br>" + label + ": %{y:,}<extra></extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=df.month, y=df.current_customers, name=DEDUP_LABEL, mode="lines",
            line=dict(color=fg.SLATE, width=2, dash="dot"),
            hovertemplate="%{x|%b %Y}<br>Deduplicated total: %{y:,}<extra></extra>",
        )
    )
    return fg.style_fig(fig, 340)


def fig_active_by_channel(df: pd.DataFrame) -> go.Figure:
    """Monthly active customers (ordered in the month), stacked by channel.
    Stacks sum channel counts, so a multi-channel customer appears in each of
    its channels — the deduplicated monthly total is on hover."""
    fig = go.Figure()
    for ch, label, color in CHANNEL_SERIES:
        fig.add_trace(
            go.Bar(
                x=df.month, y=df[f"active_{ch}"], name=label, marker_color=color,
                hovertemplate="%{x|%b %Y}<br>" + label + ": %{y:,}<extra></extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=df.month, y=df.active_customers, name=DEDUP_LABEL, mode="lines",
            line=dict(color=fg.SLATE, width=2, dash="dot"),
            hovertemplate="%{x|%b %Y}<br>Deduplicated total: %{y:,}<extra></extra>",
        )
    )
    fig.update_layout(barmode="stack", bargap=0.25)
    return fg.style_fig(fig, 300)


def fig_new_returning(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(x=df.month, y=df.new_customers, name="New (first order)", marker_color=fg.TEAL,
               hovertemplate="%{x|%b %Y}<br>New: %{y:,}<extra></extra>")
    )
    fig.add_trace(
        go.Bar(x=df.month, y=df.returning_customers, name="Returning", marker_color="#94a3b8",
               hovertemplate="%{x|%b %Y}<br>Returning: %{y:,}<extra></extra>")
    )
    fig.update_layout(barmode="stack", bargap=0.25)
    return fg.style_fig(fig, 300)


def fig_current_mix(k: dict) -> go.Figure:
    """Current customers by channel at the window end. Slices sum per-channel
    counts; the center shows the deduplicated total (multi-channel customers
    count once there, so slices can sum past the center figure)."""
    labels, values, colors = [], [], []
    key = {"business_subscription": "current_subscribers", "d2c": "current_d2c",
           "marketplace": "current_marketplace"}
    for ch, label, color in CHANNEL_SERIES:
        labels.append(label)
        values.append(k[key[ch]])
        colors.append(color)
    fig = go.Figure(
        go.Pie(
            labels=labels, values=values, hole=0.58, marker_colors=colors,
            sort=False, textinfo="percent", textfont_size=12,
            hovertemplate="%{label}<br>%{value:,} current (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(
        annotations=[dict(
            text=f"{k['current_customers']:,}<br>deduplicated",
            x=0.5, y=0.5, font_size=12, showarrow=False, font_color=fg.SLATE,
        )]
    )
    return fg.style_fig(fig, 300)


def fig_identity_status(by_system: pd.DataFrame, status_labels: dict[str, str]) -> go.Figure:
    """Source aliases per system, stacked by crosswalk resolution status —
    the fragmentation the canonical grain hides."""
    systems = list(by_system.index)
    fig = go.Figure()
    for status, color in STATUS_COLORS.items():
        fig.add_trace(
            go.Bar(
                y=systems, x=by_system[status], name=status_labels[status],
                orientation="h", marker_color=color,
                hovertemplate="%{y}<br>" + status_labels[status] + ": %{x:,}<extra></extra>",
            )
        )
    fig.update_layout(barmode="stack", bargap=0.35)
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=True, gridcolor="#eef2f7")
    return fg.style_fig(fig, 300)


def fig_naive_vs_canonical(idq: dict) -> go.Figure:
    """The join trap in one picture: summing per-system profile rows vs the
    canonical customer grain."""
    bars = [
        ("Σ per-system profiles (naive)", idq["alias_count"], fg.RED),
        ("Canonical app profiles", idq["canonical_profiles"], fg.PRIMARY),
        ("Ever-ordered customers", idq["ordered_customers"], fg.TEAL),
    ]
    fig = go.Figure(
        go.Bar(
            x=[b[0] for b in bars], y=[b[1] for b in bars],
            marker_color=[b[2] for b in bars],
            text=[f"{b[1]:,}" for b in bars], textposition="outside",
            hovertemplate="%{x}: %{y:,}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_yaxes(rangemode="tozero")
    return fg.style_fig(fig, 300)

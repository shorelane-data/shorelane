"""
Free BI path: render the five revenues as an interactive Plotly HTML, straight
from the local Parquet. No warehouse, no BI license required — good enough to
publish alongside a blog post or demo.

    pip install plotly pandas pyarrow
    python -m bi.plotly.revenue_dashboard
    open bi/plotly/revenue_dashboard.html

Pass --as-of YYYY-MM-DD (or "today") to render only what the live warehouse can
see at that date: tables filtered by the arrival rule in loaders/visibility.py,
months truncated to fully-elapsed ones. By the parity property, this HTML equals
a dashboard queried from the drip-fed warehouse — with no credentials involved.

For the Looker Studio path (also free, BigQuery-native) see bi/looker_studio/.
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

import config
from generators import dataset
from generators.measures import five_revenues
from loaders.visibility import visible_tables

MEASURES = ["gmv", "net_revenue", "recognized_revenue", "billed_revenue", "collected_cash"]


def monthly_series(tables: dict[str, pd.DataFrame], as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    months = pd.date_range(config.START_DATE, config.END_DATE, freq="MS")
    rows = []
    for m in months:
        month_end = m + pd.offsets.MonthEnd(0)
        if as_of is not None and month_end > as_of:
            break
        rev = five_revenues(tables, m.strftime("%Y-%m-%d"), month_end.strftime("%Y-%m-%d"))
        rev["month"] = m
        rows.append(rev)
    return pd.DataFrame(rows)


def main() -> None:
    import plotly.graph_objects as go

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                    help='live-warehouse view: apply the arrival rule and stop at '
                         'the last fully-elapsed month ("today" for the current date)')
    ap.add_argument("--out", default=os.path.join("bi", "plotly", "revenue_dashboard.html"),
                    help="output HTML path")
    args = ap.parse_args()

    as_of = None
    if args.as_of:
        as_of = pd.Timestamp.now().normalize() if args.as_of == "today" else pd.Timestamp(args.as_of)

    tables = dataset.generate()
    if as_of is not None:
        tables = visible_tables(tables, as_of)
    df = monthly_series(tables, as_of=as_of)

    title = "Shorelane Commerce — five revenues, monthly (they never agree)"
    if as_of is not None:
        title += f"<br><sup>live warehouse view · fully-elapsed months as of {as_of.date()}</sup>"

    fig = go.Figure()
    for measure in MEASURES:
        fig.add_trace(go.Scatter(x=df.month, y=df[measure], mode="lines", name=measure))
    fig.update_layout(
        title=title,
        xaxis_title="Month",
        yaxis_title="USD",
        hovermode="x unified",
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.write_html(args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

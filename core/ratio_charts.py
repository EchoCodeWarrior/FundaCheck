"""
ratio_charts.py
---------------
One chart per headline ratio, each in the form that ratio actually needs.

The rule followed throughout: the data's job picks the chart type.

  ROE / ROCE          magnitude over time against a threshold  -> banded area
  Net margin          part-to-whole of one year                -> profit ladder
  EBITDA margin       one value against a target range         -> bullet
  Debt / equity       composition over time                    -> 100% stacked area
  Interest cover      distance from a danger line              -> area with zone
  Growth              polarity around zero                     -> diverging columns
  CFO / sales         gap between two related measures         -> dumbbell
  Cash cycle          a total built from parts                 -> stacked columns
  P/E                 today against its own history            -> range strip

Every figure is small enough to live in a bento tile, carries a tooltip, and
direct-labels only the point that matters.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from . import charts as C
from .scoring import Assessment

TILE_HEIGHT = 210


def _tile(fig: go.Figure, height: int = TILE_HEIGHT, legend: bool = False) -> go.Figure:
    """
    House style for a bento tile: minimal chrome, room to breathe.

    `legend` reserves the top band for it — without that the legend is drawn
    outside the plot area and clipped away.
    """
    fig.update_layout(
        height=height,
        font=dict(family=C.FONT_FAMILY, size=12, color=C.INK),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=34 if legend else 10, b=8),
        showlegend=False,
        hoverlabel=dict(bgcolor=C.SURFACE_HEX, bordercolor=C.S1,
                        font=dict(color=C.INK, size=12)),
        bargap=0.42,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=C.GRID,
                     tickfont=dict(color=C.MUTED, size=10))
    fig.update_yaxes(showgrid=True, gridcolor=C.GRID, zeroline=False,
                     linecolor="rgba(0,0,0,0)", tickfont=dict(color=C.MUTED, size=10))
    return fig


def _series(model, metric: str) -> pd.Series:
    return (
        pd.to_numeric(model.series(metric), errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )


def _empty(message: str = "not in this workbook") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False,
                       font=dict(color=C.MUTED, size=12), x=0.5, y=0.5,
                       xref="paper", yref="paper")
    return _tile(fig)


def _band(result: Assessment, metric: str) -> tuple[float, float] | None:
    return result.sector.benchmarks.get(metric)


# --------------------------------------------------------------------------
# 1 & 2 — ROE and ROCE: magnitude over time against the sector's threshold
# --------------------------------------------------------------------------
def return_trend(model, result: Assessment, metric: str) -> go.Figure:
    """
    A return ratio through time with the sector's strong line drawn across it.

    A return number means nothing without the bar it has to clear, so the bar is
    part of the chart rather than a caption underneath it.
    """
    series = _series(model, metric)
    if series.empty:
        return _empty()

    values = series * 100
    band = _band(result, metric)
    fig = go.Figure()

    if band:
        weak, strong = band[0] * 100, band[1] * 100
        fig.add_hrect(y0=weak, y1=strong, fillcolor=C._translucent(C.WARNING, 0.07),
                      line_width=0)
        fig.add_hline(y=strong, line=dict(color=C.GOOD, width=1))
        fig.add_annotation(x=0, xref="paper", y=strong, text=f"sector strong {strong:.0f}%",
                           showarrow=False, xanchor="left", yanchor="bottom",
                           font=dict(color=C.GOOD, size=9))

    fig.add_trace(go.Scatter(
        x=list(series.index), y=values.values, mode="lines",
        line=dict(color=C.S1, width=2.4, shape="spline", smoothing=0.4),
        fill="tozeroy", fillcolor=C._translucent(C.S1, 0.16),
        hovertemplate="%{x}: %{y:.1f}%<extra></extra>", name=metric,
    ))
    # only the endpoint is labelled — a number on every point is noise
    last = float(values.iloc[-1])
    fig.add_trace(go.Scatter(
        x=[series.index[-1]], y=[last], mode="markers+text",
        marker=dict(size=9, color=C.S1, line=dict(color=C.SURFACE_HEX, width=2)),
        text=[f" {last:.1f}%"], textposition="middle left",
        textfont=dict(color=C.INK, size=12), hoverinfo="skip",
    ))
    fig.update_yaxes(ticksuffix="%")
    return _tile(fig)


# --------------------------------------------------------------------------
# 3 — Net profit margin: where the money goes, as a ladder
# --------------------------------------------------------------------------
def profit_ladder(model) -> go.Figure:
    """
    Sales stepping down to net profit for the latest year.

    Net margin is the last rung of a ladder, and the interesting part is which
    rung loses the most — so the whole descent is drawn, not just the total.
    """
    if model.common_size.empty:
        return _empty()

    steps = [
        ("Sales", 1.0, C.MUTED),
        ("Gross profit", None, C.S1),
        ("EBITDA", None, C.S1),
        ("EBIT (Operating Profit)", None, C.S1),
        ("Earnings Before Tax", None, C.S1),
        ("Net Profit", None, C.S1),
    ]
    labels, values = [], []
    for label, fixed, _ in steps:
        if fixed is not None:
            labels.append(label)
            values.append(100.0)
            continue
        if label in model.common_size.index:
            series = model.common_size.loc[label].dropna()
            if not series.empty:
                labels.append(label.replace(" (Operating Profit)", ""))
                values.append(float(series.iloc[-1]) * 100)
    if len(values) < 3:
        return _empty()

    # one hue, dark to light: this is a magnitude ladder, not six identities
    ramp = [C.SEQ[1], C.SEQ[2], C.SEQ[3], C.SEQ[4], C.SEQ[5], C.SEQ[6]]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=ramp[:len(values)], line=dict(color=C.SURFACE_HEX, width=2)),
        text=[f"{v:.1f}%" for v in values], textposition="outside",
        textfont=dict(color=C.MUTED, size=11),
        hovertemplate="%{y}: %{x:.1f}% of sales<extra></extra>", width=0.6,
    ))
    fig.update_xaxes(range=[0, max(values) * 1.28], showgrid=True, gridcolor=C.GRID)
    fig.update_yaxes(autorange="reversed")
    return _tile(fig, 250)


# --------------------------------------------------------------------------
# 4 — EBITDA margin: one number against a target range
# --------------------------------------------------------------------------
def margin_bullet(model, result: Assessment) -> go.Figure:
    """
    A bullet chart: the current margin as a bar, the sector's weak/strong band
    behind it, and the 3-year average as a tick.

    This is the classic form for "one value against a target", and it beats a
    gauge because the qualitative zones are to scale.
    """
    series = _series(model, "EBITDA Margin")
    if series.empty:
        return _empty()

    latest = float(series.iloc[-1]) * 100
    average = float(series.tail(3).mean()) * 100
    band = _band(result, "EBITDA Margin")
    weak, strong = ((band[0] * 100, band[1] * 100) if band else (latest * 0.6, latest * 1.4))
    ceiling = max(latest, strong, average) * 1.35

    fig = go.Figure()
    for start, end, colour in (
        (0, weak, C._translucent(C.CRITICAL, 0.16)),
        (weak, strong, C._translucent(C.WARNING, 0.16)),
        (strong, ceiling, C._translucent(C.GOOD, 0.16)),
    ):
        fig.add_shape(type="rect", x0=start, x1=end, y0=0.16, y1=0.84,
                      fillcolor=colour, line_width=0, layer="below")

    fig.add_trace(go.Bar(
        x=[latest], y=["EBITDA margin"], orientation="h",
        marker=dict(color=C.S1, line=dict(width=0)), width=0.3,
        hovertemplate=f"latest {latest:.1f}%<extra></extra>",
    ))
    fig.add_shape(type="line", x0=average, x1=average, y0=0.1, y1=0.9,
                  line=dict(color=C.INK, width=2))
    fig.add_annotation(x=average, y=0.96, yref="paper",
                       text=f"3Y avg {average:.1f}%", showarrow=False,
                       font=dict(color=C.MUTED, size=10))
    fig.add_annotation(x=latest, y=0.5, text=f" {latest:.1f}%  ", showarrow=False,
                       xanchor="left", font=dict(color=C.INK, size=15))
    fig.update_xaxes(range=[0, ceiling], ticksuffix="%", showgrid=False)
    fig.update_yaxes(showticklabels=False, showgrid=False)
    return _tile(fig, 170)


# --------------------------------------------------------------------------
# 5 — Debt to equity: the funding mix over time
# --------------------------------------------------------------------------
def funding_mix(model) -> go.Figure:
    """
    Borrowings versus equity as a share of the two, year by year.

    A D/E of 1.3 is abstract; "57% of funding is borrowed, up from 48%" is not.
    Part-to-whole over time is an area chart's job.
    """
    borrowings = _series(model, "Borrowings")
    capital = _series(model, "Equity Share Capital")
    reserves = _series(model, "Reserves")
    if borrowings.empty or (capital.empty and reserves.empty):
        return _empty()

    equity = capital.add(reserves, fill_value=0.0)
    frame = pd.DataFrame({"debt": borrowings, "equity": equity}).dropna()
    if frame.empty:
        return _empty()
    total = frame.sum(axis=1).replace(0, np.nan)
    debt_pct = (frame["debt"] / total * 100).dropna()
    equity_pct = 100 - debt_pct

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(equity_pct.index), y=equity_pct.values, mode="lines", stackgroup="mix",
        line=dict(width=0.5, color=C.SURFACE_HEX), fillcolor=C._translucent(C.S1, 0.55),
        name="Equity", hovertemplate="%{x} · equity %{y:.0f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=list(debt_pct.index), y=debt_pct.values, mode="lines", stackgroup="mix",
        line=dict(width=0.5, color=C.SURFACE_HEX), fillcolor=C._translucent(C.S2, 0.55),
        name="Debt", hovertemplate="%{x} · debt %{y:.0f}%<extra></extra>",
    ))
    fig.add_annotation(x=debt_pct.index[-1], y=100 - debt_pct.iloc[-1] / 2,
                       text=f"debt {debt_pct.iloc[-1]:.0f}%", showarrow=False,
                       xanchor="right", font=dict(color=C.INK, size=11))
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    return _tile(fig)


# --------------------------------------------------------------------------
# 6 — Interest cover: distance from the line where profit stops covering interest
# --------------------------------------------------------------------------
def interest_cover_zone(model, result: Assessment) -> go.Figure:
    """
    Interest cover with the danger zone shaded from zero to 1x.

    Below 1x, operating profit no longer pays the interest bill. That line is
    the whole point of the ratio, so it is drawn rather than described.
    """
    series = _series(model, "Interest Coverage Ratio")
    if series.empty:
        return _empty()

    band = _band(result, "Interest Coverage Ratio")
    ceiling = max(float(series.max()) * 1.25, (band[1] if band else 0) * 1.1, 2.0)

    fig = go.Figure()
    fig.add_hrect(y0=0, y1=1, fillcolor=C._translucent(C.CRITICAL, 0.16), line_width=0)
    fig.add_annotation(x=1, xref="paper", y=0.5, text="below 1x, interest is unpaid ",
                       showarrow=False, xanchor="right", yanchor="middle",
                       font=dict(color=C.CRITICAL, size=9))
    if band:
        fig.add_hline(y=band[1], line=dict(color=C.GOOD, width=1))

    fig.add_trace(go.Scatter(
        x=list(series.index), y=series.values, mode="lines+markers",
        line=dict(color=C.S1, width=2.4, shape="spline", smoothing=0.4),
        marker=dict(size=7, color=C.S1, line=dict(color=C.SURFACE_HEX, width=2)),
        hovertemplate="%{x}: %{y:.2f}x cover<extra></extra>",
    ))
    fig.update_yaxes(range=[0, ceiling], ticksuffix="x")
    return _tile(fig)


# --------------------------------------------------------------------------
# 7 — Growth: polarity around zero
# --------------------------------------------------------------------------
def growth_columns(model, metric: str = "Sales Growth") -> go.Figure:
    """
    Growth as columns above and below zero, coloured by direction.

    Direction is the message, so it gets the encoding; the diverging pair is
    used with a real zero baseline rather than a colour ramp.
    """
    series = _series(model, metric)
    if series.empty:
        return _empty()

    values = series * 100
    colours = [C.GOOD if v >= 0 else C.CRITICAL for v in values]
    fig = go.Figure(go.Bar(
        x=list(series.index), y=values.values,
        marker=dict(color=[C._translucent(c, 0.85) for c in colours],
                    line=dict(color=C.SURFACE_HEX, width=2)),
        hovertemplate="%{x}: %{y:+.1f}%<extra></extra>", width=0.62,
    ))
    fig.add_hline(y=0, line=dict(color=C.MUTED, width=1))
    fig.update_yaxes(ticksuffix="%")
    return _tile(fig)


# --------------------------------------------------------------------------
# 8 — CFO / sales: does the profit turn into cash?
# --------------------------------------------------------------------------
def cash_quality_dumbbell(model) -> go.Figure:
    """
    Cash from operations against net profit, both as a share of sales, joined
    per year.

    The gap between the dots IS the earnings-quality question. A dumbbell makes
    that gap the visual subject; two separate lines would not.
    """
    cfo = _series(model, "CFO / Sales")
    margin = _series(model, "Net Margins")
    if margin.empty:
        margin = _series(model, "Net Profit Margin")
    if cfo.empty or margin.empty:
        return _empty()

    frame = pd.DataFrame({"cfo": cfo * 100, "profit": margin * 100}).dropna().tail(8)
    if frame.empty:
        return _empty()

    fig = go.Figure()
    for year, row in frame.iterrows():
        fig.add_trace(go.Scatter(
            x=[row["profit"], row["cfo"]], y=[year, year], mode="lines",
            line=dict(color=C.GRID, width=3), hoverinfo="skip",
            showlegend=False,   # connectors are scaffolding, not a series
        ))
    fig.add_trace(go.Scatter(
        x=frame["profit"], y=list(frame.index), mode="markers", name="Net profit",
        marker=dict(size=10, color=C.S2, line=dict(color=C.SURFACE_HEX, width=2)),
        hovertemplate="%{y} · net profit %{x:.1f}% of sales<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=frame["cfo"], y=list(frame.index), mode="markers", name="Operating cash",
        marker=dict(size=10, color=C.S1, line=dict(color=C.SURFACE_HEX, width=2)),
        hovertemplate="%{y} · operating cash %{x:.1f}% of sales<extra></extra>",
    ))
    fig.add_vline(x=0, line=dict(color=C.MUTED, width=1))
    fig.update_xaxes(ticksuffix="%")
    fig.update_layout(legend=dict(
        orientation="h", y=1.14, x=0, bgcolor="rgba(0,0,0,0)",
        font=dict(size=10, color=C.MUTED)))
    fig = _tile(fig, 250, legend=True)
    fig.update_layout(showlegend=True)
    return fig


# --------------------------------------------------------------------------
# 9 — Cash conversion cycle: a total built from its parts
# --------------------------------------------------------------------------
def cash_cycle_bridge(model) -> go.Figure:
    """
    Receivable and inventory days above the line, payable days below, with the
    resulting cycle tracked on top.

    The cycle is an arithmetic result, so showing the three inputs explains any
    move in it without a second chart.
    """
    parts = [("Debtor Days", C.S1), ("Inventory Days", C.S2), ("Payable Days", C.S3)]
    fig = go.Figure()
    drawn = False
    for label, colour in parts:
        series = _series(model, label)
        if series.empty:
            continue
        drawn = True
        values = -series.values if label == "Payable Days" else series.values
        fig.add_trace(go.Bar(
            x=list(series.index), y=values, name=label,
            marker=dict(color=C._translucent(colour, 0.8),
                        line=dict(color=C.SURFACE_HEX, width=2)),
            hovertemplate=f"{label}: %{{y:.0f}} days<extra></extra>",
        ))
    cycle = _series(model, "Cash Conversion Cycle")
    if not cycle.empty:
        drawn = True
        fig.add_trace(go.Scatter(
            x=list(cycle.index), y=cycle.values, name="Cash conversion cycle",
            mode="lines+markers", line=dict(color=C.INK, width=2),
            marker=dict(size=6, color=C.INK),
            hovertemplate="cycle: %{y:.0f} days<extra></extra>",
        ))
    if not drawn:
        return _empty()

    fig.update_layout(barmode="relative", legend=dict(
        orientation="h", y=1.14, x=0, bgcolor="rgba(0,0,0,0)",
        font=dict(size=10, color=C.MUTED)))
    fig.add_hline(y=0, line=dict(color=C.MUTED, width=1))
    fig.update_yaxes(ticksuffix="d")
    fig = _tile(fig, 250, legend=True)
    fig.update_layout(showlegend=True, barmode="relative")
    return fig


# --------------------------------------------------------------------------
# 10 — P/E: today against its own history
# --------------------------------------------------------------------------
def valuation_strip(model) -> go.Figure:
    """
    The P/E history as a line, with the company's own median as the reference.

    "Expensive" only means anything relative to something; the honest local
    comparison is the same company's past, so that is what is drawn.
    """
    series = _series(model, "PE Ratio")
    series = series[(series > 0) & (series < 500)]
    if series.empty:
        return _empty()

    median = float(series.median())
    latest = float(series.iloc[-1])

    fig = go.Figure()
    fig.add_hline(y=median, line=dict(color=C.MUTED, width=1))
    fig.add_annotation(x=0, xref="paper", y=median, text=f"own median {median:.0f}x",
                       showarrow=False, xanchor="left", yanchor="bottom",
                       font=dict(color=C.MUTED, size=9))
    fig.add_trace(go.Scatter(
        x=list(series.index), y=series.values, mode="lines",
        line=dict(color=C.S4, width=2.4, shape="spline", smoothing=0.4),
        fill="tonexty", fillcolor=C._translucent(C.S4, 0.14),
        hovertemplate="%{x}: %{y:.1f}x earnings<extra></extra>",
    ))
    dearer = latest >= median
    fig.add_trace(go.Scatter(
        x=[series.index[-1]], y=[latest], mode="markers+text",
        marker=dict(size=10, color=C.S4, line=dict(color=C.SURFACE_HEX, width=2)),
        text=[f" {latest:.0f}x "], textposition="middle left",
        textfont=dict(color=C.INK, size=13), hoverinfo="skip",
    ))
    fig.add_annotation(
        x=1, xref="paper", y=1.02, yref="paper", xanchor="right",
        text=("above its own median — the market has priced in some strength"
              if dearer else "below its own median — the market is discounting it"),
        showarrow=False, font=dict(color=C.MUTED, size=10),
    )
    fig.update_yaxes(ticksuffix="x")
    return _tile(fig)

"""
charts.py
---------
Every Plotly figure the dashboard draws.

Keeping charts in one file means the visual language (colours, fonts, grid
weight, hover style) is defined exactly once, so the whole terminal looks like
a single designed product rather than ten charts glued together.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .scoring import Assessment
from .sectors import PERCENT_METRICS

# --- design tokens --------------------------------------------------------
# Two palettes, each SELECTED for its own surface rather than flipped from the
# other. Both were run through the palette validator: lightness band, chroma
# floor, colourblind separation and 3:1 contrast all pass on the adjacent
# pairlist (bars, stacks, lines) that these charts use. Forms that compare every
# pair at once are capped at the first three slots and direct-labelled.
PALETTES = {
    "dark": dict(
        ink="#eaf3ee", muted="#88a598", grid="rgba(136,165,152,0.13)",
        surface="#0b1712",
        series=["#1faa5e", "#9085e9", "#c98500", "#3d9fd0", "#d55181"],
        seq=["#0d2a1c", "#12492e", "#166b41", "#1a8c53", "#1faa5e", "#4cc287", "#8ad9b0"],
        diverging=[[0.0, "#d03b3b"], [0.5, "#2c3330"], [1.0, "#3d9fd0"]],
    ),
    # Light is the primary theme: it matches the FundaCheck design system, whose
    # brand green is slot 1. Validated as a set against that design's surface.
    "light": dict(
        ink="#15201a", muted="#7d847f", grid="rgba(125,132,127,0.16)",
        surface="#ffffff",
        series=["#177245", "#4a3aa7", "#b57500", "#2a78d6", "#c43e6d"],
        # the design's own green ramp, light to dark
        seq=["#eef4f0", "#cde5d8", "#a9d3bd", "#6dbd93", "#2b8b57", "#177245", "#0f5b34"],
        diverging=[[0.0, "#a4483f"], [0.5, "#eceeec"], [1.0, "#2a78d6"]],
    ),
}

# status palette — fixed, never themed, never reused as a series colour
GOOD = "#0ca30c"
WARNING = "#fab219"
SERIOUS = "#ec835a"
CRITICAL = "#d03b3b"

def _translucent(hex_colour: str, alpha: float) -> str:
    """rgba() string from a #rrggbb value — for fills under a solid line."""
    hex_colour = hex_colour.lstrip("#")
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


MODE = "dark"
INK = MUTED = GRID = SURFACE_HEX = ""
SERIES: list[str] = []
S1 = S2 = S3 = S4 = S5 = ""
SEQ: list[str] = []
DIVERGING: list = []
SURFACE = "rgba(0,0,0,0)"   # figures are transparent; the card supplies the ground
GREEN = GREEN_SOFT = AMBER = RED = VIOLET = ""


def set_theme(mode: str = "dark") -> None:
    """
    Point the chart module at one of the two validated palettes.

    Figures are built fresh on every Streamlit run, so swapping these
    module-level names before drawing is enough to retheme the whole dashboard.
    """
    global MODE, INK, MUTED, GRID, SURFACE_HEX, SERIES, SEQ, DIVERGING
    global S1, S2, S3, S4, S5, GREEN, GREEN_SOFT, AMBER, RED, VIOLET

    palette = PALETTES.get(mode, PALETTES["dark"])
    MODE = mode if mode in PALETTES else "dark"
    INK, MUTED, GRID = palette["ink"], palette["muted"], palette["grid"]
    SURFACE_HEX = palette["surface"]
    SERIES = list(palette["series"])
    S1, S2, S3, S4, S5 = SERIES
    SEQ = list(palette["seq"])
    DIVERGING = [list(stop) for stop in palette["diverging"]]
    GREEN, AMBER, RED, VIOLET = S1, WARNING, CRITICAL, S2
    GREEN_SOFT = _translucent(S1, 0.18)


FONT_FAMILY = "'Plus Jakarta Sans', Inter, 'Segoe UI', system-ui, sans-serif"


def _shell(fig: go.Figure, height: int = 320, legend: bool = False) -> go.Figure:
    """Apply the house style to any figure."""
    fig.update_layout(
        height=height,
        font=dict(family=FONT_FAMILY, size=13, color=INK),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        margin=dict(l=10, r=10, t=28, b=10),
        showlegend=legend,
        legend=dict(
            orientation="h", y=1.14, x=0, bgcolor="rgba(0,0,0,0)",
            font=dict(size=11, color=MUTED),
        ),
        hoverlabel=dict(
            bgcolor=SURFACE_HEX, bordercolor=S1, font=dict(color=INK, size=12)
        ),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, tickfont=dict(color=MUTED, size=11),
                     linecolor=GRID)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False,
                     tickfont=dict(color=MUTED, size=11), linecolor="rgba(0,0,0,0)")
    return fig


def _as_percent(metric: str) -> bool:
    return metric in PERCENT_METRICS or "%" in metric or "Margin" in metric


def gauge(result: Assessment) -> go.Figure:
    """The headline score dial."""
    colour = result.colour
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=result.total_score,
        number=dict(font=dict(size=46, color=INK), suffix="<span style='font-size:16px'>/100</span>"),
        gauge=dict(
            axis=dict(range=[0, 100], tickwidth=0, tickcolor=MUTED,
                      tickfont=dict(color=MUTED, size=10)),
            bar=dict(color=colour, thickness=0.34),
            bgcolor="rgba(255,255,255,0.03)",
            borderwidth=0,
            steps=[
                dict(range=[0, 40], color="rgba(255,95,86,0.13)"),
                dict(range=[40, 66], color="rgba(240,180,41,0.13)"),
                dict(range=[66, 100], color="rgba(55,214,122,0.13)"),
            ],
            threshold=dict(line=dict(color=INK, width=2), thickness=0.8,
                           value=result.total_score),
        ),
    ))
    return _shell(fig, height=250)


def pillar_radar(result: Assessment) -> go.Figure:
    """Five-pillar profile — the shape tells you the company's character."""
    labels = [p.title() for p in result.pillar_scores]
    values = list(result.pillar_scores.values())
    if not labels:
        return _shell(go.Figure())

    fig = go.Figure(go.Scatterpolar(
        r=values + values[:1],
        theta=labels + labels[:1],
        fill="toself",
        fillcolor=GREEN_SOFT,
        line=dict(color=GREEN, width=2),
        marker=dict(size=7, color=GREEN),
        hovertemplate="%{theta}: %{r:.0f}/100<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(255,255,255,0.02)",
            radialaxis=dict(range=[0, 100], showline=False, gridcolor=GRID,
                            tickfont=dict(color=MUTED, size=9)),
            angularaxis=dict(gridcolor=GRID, tickfont=dict(color=INK, size=11)),
        ),
    )
    fig = _shell(fig, height=360)
    # the polar labels sit outside the plot area, so give them room
    fig.update_layout(margin=dict(l=70, r=70, t=52, b=58))
    return fig


def scorecard_bars(result: Assessment) -> go.Figure:
    """Every ratio's 0-100 sub-score, coloured by band."""
    ordered = sorted(result.metrics, key=lambda m: m.score)
    colours = [CRITICAL if m.score < 45 else WARNING if m.score < 70 else GOOD
               for m in ordered]
    fig = go.Figure(go.Bar(
        x=[m.score for m in ordered],
        y=[m.metric for m in ordered],
        orientation="h",
        # Translucent fills with a solid status-coloured edge: a long bar at full
        # saturation reads as a heavy block and drowns the labels.
        marker=dict(
            color=[_translucent(c, 0.28) for c in colours],
            line=dict(color=colours, width=1.5),
        ),
        text=[f"{m.display(m.latest)}" for m in ordered],
        textposition="outside",
        textfont=dict(color=MUTED, size=11),
        hovertemplate="%{y}<br>Score %{x:.0f}/100<extra></extra>",
        width=0.5,
    ))
    fig.add_vline(x=45, line=dict(color=CRITICAL, width=1))
    fig.add_vline(x=70, line=dict(color=GOOD, width=1))
    fig.update_xaxes(range=[0, 118], showgrid=True, gridcolor=GRID)
    return _shell(fig, height=max(300, 34 * len(ordered)))


def trend_line(series: pd.Series, metric: str, benchmark: tuple[float, float] | None = None
               ) -> go.Figure:
    """One ratio through time, with the sector's weak/strong bands shaded."""
    values = series.astype(float)
    scale = 100 if _as_percent(metric) else 1
    y = values * scale

    fig = go.Figure()
    if benchmark:
        weak, strong = (b * scale for b in benchmark)
        low, high = sorted((weak, strong))
        fig.add_hrect(y0=low, y1=high, fillcolor="rgba(240,180,41,0.07)", line_width=0)
        fig.add_hline(y=strong, line=dict(color=GOOD, width=1),
                      annotation_text="sector strong", annotation_position="top left",
                      annotation_font=dict(color=GOOD, size=10))
        fig.add_hline(y=weak, line=dict(color=CRITICAL, width=1),
                      annotation_text="sector weak", annotation_position="bottom left",
                      annotation_font=dict(color=CRITICAL, size=10))

    fig.add_trace(go.Scatter(
        x=list(series.index), y=y, mode="lines+markers",
        line=dict(color=GREEN, width=2.6, shape="spline", smoothing=0.5),
        marker=dict(size=8, color=S1, line=dict(color=SURFACE_HEX, width=2)),
        fill="tozeroy", fillcolor=GREEN_SOFT,
        hovertemplate="%{x}: %{y:.2f}<extra></extra>",
        name=metric,
    ))
    suffix = "%" if _as_percent(metric) else ""
    fig.update_yaxes(ticksuffix=suffix)
    return _shell(fig, height=300)


def revenue_profit_panel(model) -> go.Figure:
    """
    Sales, net profit and net margin as stacked small multiples on a shared
    x-axis.

    This used to be one chart with revenue on the left axis and margin on the
    right. A second y-scale lets you imply any relationship you like by
    choosing the ranges, so the panel is split instead: same story, no
    manufactured crossover.
    """
    sales = model.series("Sales").dropna()
    profit = model.series("Net Profit").dropna()
    margin = model.series("Net Margins").dropna()
    if margin.empty:
        margin = model.series("Net Profit Margin").dropna()

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.09,
        subplot_titles=("Sales", "Net profit", "Net margin"),
    )
    if not sales.empty:
        fig.add_trace(go.Bar(
            x=list(sales.index), y=sales.values, name="Sales",
            marker=dict(color=S1, line=dict(color=SURFACE_HEX, width=2)),
            hovertemplate="%{x} · sales %{y:,.0f}<extra></extra>",
        ), row=1, col=1)
    if not profit.empty:
        fig.add_trace(go.Bar(
            x=list(profit.index), y=profit.values, name="Net profit",
            marker=dict(color=S2, line=dict(color=SURFACE_HEX, width=2)),
            hovertemplate="%{x} · net profit %{y:,.0f}<extra></extra>",
        ), row=2, col=1)
    if not margin.empty:
        fig.add_trace(go.Scatter(
            x=list(margin.index), y=margin.values * 100, name="Net margin",
            mode="lines+markers", line=dict(color=S3, width=2),
            marker=dict(size=8, color=S3, line=dict(color=SURFACE_HEX, width=2)),
            hovertemplate="%{x} · net margin %{y:.1f}%<extra></extra>",
        ), row=3, col=1)
        # direct-label the endpoint only, never every point
        fig.add_annotation(
            x=list(margin.index)[-1], y=float(margin.iloc[-1]) * 100,
            text=f"  {float(margin.iloc[-1]) * 100:.1f}%", showarrow=False,
            xanchor="left", font=dict(color=S3, size=11), row=3, col=1,
        )

    fig.update_yaxes(ticksuffix="%", row=3, col=1)
    fig = _shell(fig, height=430)
    for annotation in fig.layout.annotations[:3]:
        annotation.font = dict(size=11, color=MUTED)
        annotation.x = 0
        annotation.xanchor = "left"
    fig.update_layout(bargap=0.45)
    return fig


def cost_structure_panel(model) -> go.Figure:
    """
    Every line of the income statement as a % of sales, one small multiple each.

    This replaces a single 100% stacked bar. COGS is ~75-90% of sales, so on a
    shared 0-100% scale it swallowed the chart and the lines that actually move
    the verdict — interest, depreciation, the profit that survives — were
    invisible slivers. Each component now gets its own panel and its own
    y-scale, so a 2%-to-5% move in interest cost reads as clearly as a move in
    COGS.
    """
    components = [
        ("COGS", S1),
        ("Selling & General Expenses", S2),
        ("Depreciation", S3),
        ("Interest", S4),
        ("Tax", S5),
        ("Net Profit", S1),
    ]
    available = []
    for label, colour in components:
        series = model.common_size.loc[label].dropna() if (
            not model.common_size.empty and label in model.common_size.index
        ) else pd.Series(dtype="float64")
        if not series.empty:
            available.append((label, colour, series))
    if not available:
        return _shell(go.Figure(), height=340)

    columns = 3
    rows = (len(available) + columns - 1) // columns
    fig = make_subplots(
        rows=rows, cols=columns, vertical_spacing=0.19, horizontal_spacing=0.09,
        subplot_titles=[label for label, _, _ in available],
    )

    for index, (label, colour, series) in enumerate(available):
        row, col = divmod(index, columns)
        values = series * 100
        fig.add_trace(go.Scatter(
            x=list(series.index), y=values.values, name=label,
            mode="lines+markers", line=dict(color=colour, width=2, shape="spline",
                                            smoothing=0.4),
            marker=dict(size=6, color=colour, line=dict(color=SURFACE_HEX, width=2)),
            fill="tozeroy", fillcolor=_translucent(colour, 0.14),
            hovertemplate=f"{label} · %{{x}}: %{{y:.1f}}% of sales<extra></extra>",
        ), row=row + 1, col=col + 1)
        # direct-label the latest value; the axis carries the rest
        fig.add_annotation(
            x=list(series.index)[-1], y=float(values.iloc[-1]),
            text=f"{float(values.iloc[-1]):.1f}%", showarrow=False,
            xanchor="right", yanchor="bottom",
            font=dict(color=colour, size=11), row=row + 1, col=col + 1,
        )

    fig.update_yaxes(ticksuffix="%")
    fig.update_xaxes(tickfont=dict(size=9))
    fig = _shell(fig, height=190 * rows + 60)
    for annotation in fig.layout.annotations[:len(available)]:
        annotation.font = dict(size=11, color=MUTED)
        annotation.x = annotation.x - 0.02
        annotation.xanchor = "left"
    return fig


def working_capital_cycle(model) -> go.Figure:
    """Debtor + inventory days minus payable days, stacked."""
    parts = [("Debtor Days", S1), ("Inventory Days", S2), ("Payable Days", S3)]
    fig = go.Figure()
    plotted = False
    for label, colour in parts:
        series = model.series(label).dropna()
        if series.empty:
            continue
        plotted = True
        values = -series.values if label == "Payable Days" else series.values
        fig.add_trace(go.Bar(
            x=list(series.index), y=values, name=label,
            marker=dict(color=colour, line=dict(width=0)),
            hovertemplate=f"{label}: %{{y:.0f}} days<extra></extra>",
        ))
    ccc = model.series("Cash Conversion Cycle").dropna()
    if not ccc.empty:
        plotted = True
        fig.add_trace(go.Scatter(
            x=list(ccc.index), y=ccc.values, name="Cash conversion cycle",
            mode="lines+markers", line=dict(color=INK, width=2.4, dash="dot"),
            marker=dict(size=7, color=INK),
            hovertemplate="CCC: %{y:.0f} days<extra></extra>",
        ))
    if not plotted:
        return _shell(go.Figure(), height=330)
    fig.update_layout(barmode="relative", bargap=0.35)
    fig.update_yaxes(ticksuffix="d")
    return _shell(fig, height=330, legend=True)


def leverage_panel(model) -> go.Figure:
    """
    Debt/equity and interest cover, stacked rather than overlaid.

    Both are leverage measures on wildly different scales, which is exactly the
    case a second y-axis flatters and a small multiple tells honestly.
    """
    de = model.series("Debt to Equity Ratio").dropna()
    cover = model.series("Interest Coverage Ratio").dropna()

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.13,
        subplot_titles=("Debt / equity", "Interest cover"),
    )
    if not de.empty:
        fig.add_trace(go.Bar(
            x=list(de.index), y=de.values, name="Debt / equity",
            marker=dict(color=S2, line=dict(color=SURFACE_HEX, width=2)),
            hovertemplate="%{x} · D/E %{y:.2f}x<extra></extra>",
        ), row=1, col=1)
    if not cover.empty:
        fig.add_trace(go.Scatter(
            x=list(cover.index), y=cover.values, name="Interest cover",
            mode="lines+markers", line=dict(color=S1, width=2),
            marker=dict(size=8, color=S1, line=dict(color=SURFACE_HEX, width=2)),
            hovertemplate="%{x} · interest cover %{y:.2f}x<extra></extra>",
        ), row=2, col=1)
        # 1x is the line below which operating profit no longer covers interest
        fig.add_hline(y=1.0, line=dict(color=CRITICAL, width=1),
                      row=2, col=1)
        fig.add_annotation(x=0, xref="x domain", y=1.0, text="1x — profit covers interest",
                           showarrow=False, xanchor="left", yanchor="bottom",
                           font=dict(color=CRITICAL, size=10), row=2, col=1)

    fig.update_yaxes(ticksuffix="x")
    fig = _shell(fig, height=400)
    for annotation in fig.layout.annotations[:2]:
        annotation.font = dict(size=11, color=MUTED)
        annotation.x = 0
        annotation.xanchor = "left"
    fig.update_layout(bargap=0.45)
    return fig


def cashflow_panel(model) -> go.Figure:
    """
    Operating, investing and financing cash flow — one row each, shared x-axis.

    Grouped side-by-side bars forced all three onto one scale, where a large
    financing inflow flattened operating cash to a stub. Stacked panels keep
    each flow readable while the shared x-axis still lines the years up, so the
    "funded by debt, not by operations" pattern is visible at a glance.
    """
    flows = [
        ("Cash from Operating Activity", "Operating", S1),
        ("Cash from Investing Activity", "Investing", S2),
        ("Cash from Financing Activity", "Financing", S3),
    ]
    available = [
        (label, short, colour, model.series(label).dropna())
        for label, short, colour in flows
        if not model.series(label).dropna().empty
    ]
    if not available:
        return _shell(go.Figure(), height=340)

    fig = make_subplots(
        rows=len(available), cols=1, shared_xaxes=True, vertical_spacing=0.1,
        subplot_titles=[short for _, short, _, _ in available],
    )
    for index, (label, short, colour, series) in enumerate(available):
        fig.add_trace(go.Bar(
            x=list(series.index), y=series.values, name=short,
            marker=dict(color=colour, line=dict(color=SURFACE_HEX, width=2)),
            hovertemplate=f"{short} · %{{x}}: %{{y:,.0f}} Cr<extra></extra>",
        ), row=index + 1, col=1)
        fig.add_hline(y=0, line=dict(color=GRID, width=1), row=index + 1, col=1)

    fig = _shell(fig, height=140 * len(available) + 60)
    for annotation in fig.layout.annotations[:len(available)]:
        annotation.font = dict(size=11, color=MUTED)
        annotation.x = 0
        annotation.xanchor = "left"
    fig.update_layout(bargap=0.45)
    return fig


def sector_lens_chart(frame: pd.DataFrame) -> go.Figure:
    """Same company, different sector rule books — the project's core idea."""
    if frame.empty:
        return _shell(go.Figure(), height=320)
    colours = [
        GOOD if v == "STRONG" else WARNING if v == "NEUTRAL" else CRITICAL
        for v in frame["Verdict"]
    ]
    fig = go.Figure(go.Bar(
        x=frame["Score"], y=frame["Sector lens"], orientation="h",
        marker=dict(color=colours, line=dict(width=0)),
        text=[f"{s:.0f} · {v}" for s, v in zip(frame["Score"], frame["Verdict"])],
        textposition="outside", textfont=dict(color=MUTED, size=11),
        hovertemplate="%{y}: %{x:.1f}/100<extra></extra>",
        width=0.6,
    ))
    fig.add_vline(x=40, line=dict(color=CRITICAL, width=1))
    fig.add_vline(x=66, line=dict(color=GOOD, width=1))
    fig.update_xaxes(range=[0, 125])
    return _shell(fig, height=max(300, 42 * len(frame)))


def sparkline(series: pd.Series, positive_is_good: bool = True) -> go.Figure:
    """Tiny inline trend for the KPI tiles."""
    values = series.astype(float)
    if len(values) < 2:
        return _shell(go.Figure(), height=52)
    rising = values.iloc[-1] >= values.iloc[0]
    good = rising if positive_is_good else not rising
    colour = GOOD if good else CRITICAL
    fig = go.Figure(go.Scatter(
        x=list(range(len(values))), y=values.values, mode="lines",
        line=dict(color=colour, width=2, shape="spline"),
        fill="tozeroy",
        fillcolor=_translucent(colour, 0.15),
        hoverinfo="skip",
    ))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(margin=dict(l=0, r=0, t=4, b=0))
    return _shell(fig, height=52)


def correlation_heatmap(model, metrics: list[str]) -> go.Figure:
    """How the key ratios move together across the company's history."""
    frame = pd.DataFrame({m: model.series(m) for m in metrics}).dropna(axis=1, how="all")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    if frame.shape[0] < 3 or frame.shape[1] < 2:
        return _shell(go.Figure(), height=320)
    corr = frame.corr()
    fig = go.Figure(go.Heatmap(
        z=corr.values, x=list(corr.columns), y=list(corr.index),
        colorscale=DIVERGING,
        zmin=-1, zmax=1, showscale=False,
        hovertemplate="%{y} vs %{x}: %{z:.2f}<extra></extra>",
    ))
    return _shell(fig, height=340)


def sparkline_svg(series: pd.Series, positive_is_good: bool = True,
                  width: int = 150, height: int = 34) -> str:
    """
    A sparkline as inline SVG.

    Plotly charts cannot live inside a Streamlit markdown card, so the KPI tiles
    draw their trend line by hand. It also renders instantly, which matters when
    six of them sit at the top of the page.
    """
    values = _clean_numeric(series)
    if len(values) < 2:
        return ""

    low, high = float(np.min(values)), float(np.max(values))
    span = high - low or 1.0
    step = width / (len(values) - 1)
    pad = 3
    points = [
        (i * step, height - pad - (v - low) / span * (height - 2 * pad))
        for i, v in enumerate(values)
    ]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    rising = values[-1] >= values[0]
    good = rising if positive_is_good else not rising
    colour = GOOD if good else CRITICAL
    fill = _translucent(colour, 0.16)
    last_x, last_y = points[-1]

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="none" style="display:block;margin-top:.55rem">'
        f'<polygon points="0,{height} {path} {width},{height}" fill="{fill}"/>'
        f'<polyline points="{path}" fill="none" stroke="{colour}" stroke-width="1.8" '
        f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.4" fill="{colour}"/>'
        f"</svg>"
    )


def _clean_numeric(series: pd.Series) -> np.ndarray:
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return s.to_numpy(dtype=float)


def growth_heatmap(model, metrics: list[str] | None = None) -> go.Figure:
    """
    A growth-rate grid: one row per growth measure, one column per year.

    Growth has polarity — it sits above or below zero — so this uses the
    diverging pair with a neutral gray midpoint. Margins are deliberately NOT
    on this grid: they are magnitude, not polarity, and putting both jobs on
    one diverging scale washes the margins out to gray.
    """
    metrics = metrics or [
        "Sales Growth", "EBITDA Growth", "EBIT Growth",
        "Net Profit Growth", "EPS Growth",
    ]
    rows, labels = [], []
    for metric in metrics:
        series = _finite(model.series(metric))
        if series.empty:
            continue
        rows.append(series)
        labels.append(metric)
    if not rows:
        return _shell(go.Figure(), height=280)

    frame = pd.DataFrame(rows, index=labels) * 100
    # Series start in different years, so pandas unions the indexes in order of
    # appearance. Re-impose the workbook's own chronology.
    ordered = [year for year in model.years if year in frame.columns]
    frame = frame[ordered or sorted(frame.columns)]

    # Clip the scale at the 90th percentile so one outlier year does not flatten
    # every other cell to the midpoint.
    limit = float(np.nanpercentile(np.abs(frame.to_numpy()), 90)) or 1.0

    fig = go.Figure(go.Heatmap(
        z=frame.values, x=list(frame.columns), y=list(frame.index),
        colorscale=DIVERGING, zmid=0, zmin=-limit, zmax=limit,
        xgap=2, ygap=2, showscale=False,
        hovertemplate="%{y} · %{x}: %{z:.1f}%<extra></extra>",
    ))
    fig.update_xaxes(side="bottom", type="category")
    return _shell(fig, height=max(250, 44 * len(labels)))


def pillar_meters(pillar_scores: dict[str, float]) -> str:
    """
    The five pillar scores as an HTML meter stack.

    Drawn by hand rather than with Plotly so the bars can animate in on load —
    the numbers are the same ones the radar plots.
    """
    if not pillar_scores:
        return ""
    rows = []
    for index, (pillar, score) in enumerate(pillar_scores.items()):
        colour = GOOD if score >= 70 else WARNING if score >= 45 else CRITICAL
        rows.append(
            f'<div class="meter-row">'
            f'<span class="meter-label">{pillar.title()}</span>'
            f'<span class="meter-track">'
            f'<span class="meter-fill" style="--target:{score:.0f}%;'
            f'background:{colour};animation-delay:{index * 90}ms"></span></span>'
            f'<span class="meter-value">{score:.0f}</span>'
            f"</div>"
        )
    return f'<div class="meter-stack">{"".join(rows)}</div>'


def score_ring(score: float, verdict: str, colour: str) -> str:
    """
    The composite score as an animated SVG ring.

    Replaces the Plotly gauge: it draws instantly, animates its sweep on load,
    and states the verdict in text rather than leaving colour to carry it.
    """
    radius, stroke = 78.0, 13.0
    circumference = 2 * np.pi * radius
    filled = circumference * min(max(score, 0.0), 100.0) / 100.0

    return f'''
    <div class="score-ring">
      <svg viewBox="0 0 200 200" role="img"
           aria-label="Composite score {score:.0f} out of 100 — {verdict}">
        <circle cx="100" cy="100" r="{radius}" fill="none"
                stroke="rgba(136,165,152,0.14)" stroke-width="{stroke}"/>
        <circle cx="100" cy="100" r="{radius}" fill="none" stroke="{colour}"
                stroke-width="{stroke}" stroke-linecap="round"
                transform="rotate(-90 100 100)"
                stroke-dasharray="{filled:.1f} {circumference:.1f}"
                style="--sweep:{filled:.1f};--track:{circumference:.1f}"
                class="ring-progress"/>
        <text x="100" y="96" text-anchor="middle" class="ring-score"
              fill="{INK}">{score:.0f}</text>
        <text x="100" y="120" text-anchor="middle" class="ring-unit"
              fill="{MUTED}">/ 100</text>
      </svg>
      <div class="ring-caption">
        <span class="ring-band"><i style="background:{CRITICAL}"></i>weak &lt;40</span>
        <span class="ring-band"><i style="background:{WARNING}"></i>neutral 40–66</span>
        <span class="ring-band"><i style="background:{GOOD}"></i>strong 66+</span>
      </div>
    </div>'''


def _finite(series: pd.Series) -> pd.Series:
    """Drop NaNs and the infinities that come from divide-by-near-zero."""
    return (
        pd.to_numeric(series, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )


set_theme("dark")

"""
design_blocks.py
----------------
HTML panels drawn to match the FundaCheck design canvas.

Some of the design's panels are simpler and sharper as hand-built HTML than as
Plotly figures: the revenue trend is a row of rounded pill bars, the key-ratio
list is a label/value stack, the health gauge is one arc. Building them the way
the design does keeps the radii, weights and spacing exactly on-spec, and they
render instantly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .scoring import Assessment

GREEN = "#177245"
GREEN_DARK = "#0f5b34"
INK = "#15201a"
MUTED = "#8b918e"
FAINT = "#9aa09d"
# the design's green ramp, oldest (palest) to latest (deepest)
RAMP = ["#cde5d8", "#a9d3bd", "#6dbd93", "#2b8b57", "#177245", "#0f5b34"]


def _crore(value: float) -> str:
    """Indian money formatting: a lakh crore reads better than eight digits."""
    if abs(value) >= 1e5:
        return f"{value / 1e5:.2f}L cr"
    return f"{value:,.0f} cr"


def revenue_trend(model, years: int = 6) -> str:
    """
    Sales as rounded pill bars, the tallest one labelled.

    Bar height is proportional to the value, so the shape is honest; the colour
    ramp only reinforces recency and carries no separate meaning.
    """
    sales = pd.to_numeric(model.series("Sales"), errors="coerce").dropna().tail(years)
    if sales.empty:
        return ""

    peak = float(sales.max()) or 1.0
    tallest = sales.idxmax()
    bars = []
    for index, (period, value) in enumerate(sales.items()):
        height = max(18, round(float(value) / peak * 150))
        colour = RAMP[min(index, len(RAMP) - 1)]
        if period == tallest:
            colour = GREEN_DARK
        label = ""
        if period == tallest:
            label = (
                f'<div class="pill-tag">{_crore(float(value))}</div>'
            )
        last = "font-weight:700;color:#15201a" if index == len(sales) - 1 else ""
        bars.append(
            f'<div class="pill-col">'
            f'<div class="pill-wrap">{label}'
            f'<div class="pill" style="height:{height}px;background:{colour}"></div></div>'
            f'<span style="{last}">{period}</span></div>'
        )

    # The card supplies the heading, so this block only carries the note.
    return (
        f'<div class="pill-head"><span class="pill-note">₹ crore · '
        f'{sales.index[0]}–{sales.index[-1]}</span></div>'
        f'<div class="pill-row">{"".join(bars)}</div>'
    )


def key_ratios(model, result: Assessment) -> str:
    """The design's Key Ratios list: name, the family it belongs to, and value."""
    rows = [
        ("Gross Margin", "Profitability", "Gross Margin", "pct"),
        ("ROCE", "Efficiency", "Return on Capital Employed (ROCE) %", "pct"),
        ("Interest Coverage", "Solvency", "Interest Coverage Ratio", "x"),
        ("EBITDA Margin", "Operating", "EBITDA Margin", "pct"),
        ("Cash Cycle", "Working capital", "Cash Conversion Cycle", "days"),
        ("Debtor Days", "Collections", "Debtor Days", "days"),
    ]
    items = []
    for label, family, metric, unit in rows:
        series = pd.to_numeric(model.series(metric), errors="coerce").dropna()
        if series.empty:
            continue
        value = float(series.iloc[-1])
        if unit == "pct":
            text = f"{value * 100:.1f}%"
        elif unit == "x":
            text = f"{value:.2f}x"
        else:
            text = f"{value:.0f} d"
        items.append(
            f'<div class="kr-row"><div><div class="kr-name">{label}</div>'
            f'<div class="kr-fam">{family}</div></div>'
            f'<span class="kr-val">{text}</span></div>'
        )
    return f'<div class="kr-list">{"".join(items)}</div>'


def health_gauge(result: Assessment) -> str:
    """
    The composite score as the design's half-arc health gauge.

    A semicircle rather than a full ring: it reads as a dial, and the three
    bands under it name what the colours mean so the reading never rests on
    colour alone.
    """
    score = max(0.0, min(100.0, float(result.total_score)))
    radius, cx, cy = 100.0, 118.0, 118.0
    length = np.pi * radius                      # half circumference
    filled = length * score / 100.0
    label = "Strong" if score >= 66 else "Stable" if score >= 40 else "At risk"

    return f'''
    <div class="gauge-wrap">
      <svg viewBox="0 0 236 132" role="img"
           aria-label="Health index {score:.0f} of 100 — {label}">
        <path d="M18,118 A100,100 0 0,1 218,118" fill="none"
              stroke="#eceeec" stroke-width="17" stroke-linecap="round"/>
        <path d="M18,118 A100,100 0 0,1 218,118" fill="none"
              stroke="{result.colour}" stroke-width="17" stroke-linecap="round"
              stroke-dasharray="{filled:.1f} {length:.1f}"/>
      </svg>
      <div class="gauge-read">
        <div class="gauge-score">{label}</div>
        <div class="gauge-sub">Health index · {score:.0f}/100</div>
      </div>
    </div>
    <div class="gauge-legend">
      <span><i style="background:#3d9e6b"></i>Strong 66+</span>
      <span><i style="background:#d9a441"></i>Stable 40–66</span>
      <span><i style="background:#a4483f"></i>At risk &lt;40</span>
    </div>'''


def valuation_panel(model) -> str:
    """Valuation multiples against the company's own 10-year median."""
    rows = [("P/E Ratio", "PE Ratio", "x"), ("Price to Sales", "Price to Sales", "x")]
    items = []
    for label, metric, unit in rows:
        series = pd.to_numeric(model.series(metric), errors="coerce").dropna()
        series = series[(series > 0) & (series < 1000)]
        if series.empty:
            continue
        latest, median = float(series.iloc[-1]), float(series.median())
        cheaper = latest < median
        arrow = "▼" if cheaper else "▲"
        tone = "kr-good" if cheaper else "kr-warn"
        items.append(
            f'<div class="kr-row"><div><div class="kr-name">{label}</div>'
            f'<div class="kr-fam">own median {median:.1f}{unit}</div></div>'
            f'<span class="kr-val">{latest:.1f}{unit} '
            f'<span class="{tone}">{arrow}</span></span></div>'
        )
    if not items:
        return ""
    return f'<div class="kr-list">{"".join(items)}</div>'

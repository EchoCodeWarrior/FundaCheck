"""
report.py
---------
Export Report -> one branded PDF containing an image-style snapshot of every
section of the dashboard, drawn natively with fpdf2 (no browser needed).
"""

from __future__ import annotations

import datetime as _dt
from io import BytesIO

import pandas as pd
from fpdf import FPDF

GREEN = (23, 114, 69)
GREEN_DARK = (15, 91, 52)
MID = (61, 158, 107)
LIGHT = (158, 207, 180)
AMBER = (217, 164, 65)
AMBER_TXT = (181, 118, 31)
RED = (180, 72, 60)
INK = (21, 32, 26)
BODY = (95, 102, 99)
MUTED = (139, 145, 142)
FAINT = (154, 160, 157)
CARD = (244, 245, 243)
WHITE = (255, 255, 255)

PAGE_W, PAGE_H = 210, 297
MARGIN = 14


def _t(text) -> str:
    """Latin-1-safe text (core PDF fonts have no rupee sign)."""
    return (str(text)
            .replace("\u20b9", "Rs ")
            .replace("\u2013", "-").replace("\u2014", "-")
            .replace("\u2192", "->").replace("\u00b7", "-")
            .replace("\u25b2", "^").replace("\u25bc", "v")
            .encode("latin-1", "replace").decode("latin-1"))


def band(v: float):
    return MID if v >= 66 else AMBER if v >= 40 else RED


class _Doc(FPDF):
    def __init__(self, company: str, sector: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.company = company
        self.sector = sector
        self.set_auto_page_break(False)
        self.set_margins(MARGIN, MARGIN, MARGIN)

    def footer(self):
        self.set_y(-12)
        self.set_font("helvetica", "", 8)
        self.set_text_color(*FAINT)
        self.cell(0, 6, _t(f"FundaCheck report - {self.company} - "
                           f"{_dt.date.today():%d %b %Y}"), align="L")
        self.cell(0, 6, f"Page {self.page_no()}", align="R")


class R:
    """Tiny cursor helper."""

    def __init__(self, pdf: _Doc):
        self.pdf = pdf
        self.y = MARGIN

    def need(self, h: float):
        if self.y + h > PAGE_H - 18:
            self.pdf.add_page()
            self.y = MARGIN


def _chip(pdf: _Doc, x: float, y: float, text: str, fg, bg, size=8):
    pdf.set_font("helvetica", "B", size)
    w = pdf.get_string_width(text) + 5
    pdf.set_fill_color(*bg)
    pdf.set_text_color(*fg)
    pdf.rect(x, y, w, 6, style="F", round_corners=True, corner_radius=3)
    pdf.set_xy(x, y - 0.4)
    pdf.cell(w, 6.4, _t(text), align="C")
    pdf.set_text_color(*INK)
    return w


def _card(pdf: _Doc, r: R, x: float, y: float, w: float, h: float,
          fill=(255, 255, 255), rail=None):
    pdf.set_fill_color(*fill)
    pdf.set_draw_color(236, 238, 236)
    pdf.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=3)
    if rail:
        pdf.set_fill_color(*rail)
        pdf.rect(x, y, 1.6, h, style="F")


def _section_title(pdf: _Doc, r: R, title: str, sub: str = ""):
    r.need(14)
    pdf.set_xy(MARGIN, r.y)
    pdf.set_font("helvetica", "B", 13)
    pdf.set_text_color(*INK)
    pdf.cell(0, 7, _t(title))
    r.y += 7
    if sub:
        pdf.set_xy(MARGIN, r.y)
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(*FAINT)
        pdf.cell(0, 5, _t(sub))
        r.y += 5
    r.y += 1.5


# --------------------------------------------------------------------------
def build_pdf(model, result) -> bytes:
    pdf = _Doc(model.company.title(), result.sector.name)
    r = R(pdf)
    pdf.add_page()

    # ---- cover band -------------------------------------------------------
    pdf.set_fill_color(*GREEN)
    pdf.rect(0, 0, PAGE_W, 30, style="F")
    pdf.set_fill_color(*WHITE)
    pdf.rect(MARGIN, 8, 10, 10, style="F", round_corners=True, corner_radius=3)
    pdf.set_font("helvetica", "B", 11)
    pdf.set_text_color(*GREEN)
    pdf.set_xy(MARGIN, 7.6)
    pdf.cell(10, 10, "F", align="C")
    pdf.set_font("helvetica", "B", 13)
    pdf.set_text_color(*WHITE)
    pdf.set_xy(MARGIN + 13, 7)
    pdf.cell(0, 7, "FundaCheck")
    pdf.set_font("courier", "", 6.5)
    pdf.set_text_color(214, 228, 219)
    pdf.set_xy(MARGIN + 13, 14)
    pdf.cell(0, 5, "F U N D A M E N T A L   T E R M I N A L")

    r.y = 38
    pdf.set_font("helvetica", "B", 21)
    pdf.set_text_color(*INK)
    pdf.set_xy(MARGIN, r.y)
    pdf.cell(0, 10, _t(model.company.title()))
    r.y += 10
    pdf.set_font("courier", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, _t(f"{result.sector.name.upper()}  |  "
                      f"{model.years[0]}-{model.latest_year}  |  "
                      f"{len(model.years)} PERIODS"))
    r.y += 12

    # ---- score hero -------------------------------------------------------
    _card(pdf, r, MARGIN, r.y, PAGE_W - 2 * MARGIN, 30, CARD)
    pdf.set_font("helvetica", "B", 26)
    pdf.set_text_color(*(band(result.total_score)))
    pdf.set_xy(MARGIN + 6, r.y + 4)
    pdf.cell(28, 16, f"{result.total_score:.0f}", align="L")
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(MARGIN + 34, r.y + 7)
    pdf.multi_cell(90, 5,
                   _t(f"Funda Score out of 100, judged against {result.sector.name}"))
    chip_fg = WHITE
    _chip(pdf, PAGE_W - MARGIN - 40, r.y + 9, result.verdict,
          chip_fg, band(result.total_score), size=9)
    r.y += 38

    # ---- KPI cards --------------------------------------------------------
    kpis = _kpi_cards(model, result)
    cw = (PAGE_W - 2 * MARGIN - 3 * 4) / 4
    for i, (label, value, foot, tone) in enumerate(kpis):
        x = MARGIN + i * (cw + 4)
        lead = i == 0
        bg = GREEN if lead else WHITE
        _card(pdf, r, x, r.y, cw, 26, bg)
        pdf.set_xy(x + 4, r.y + 3)
        pdf.set_font("helvetica", "", 8)
        pdf.set_text_color(*(WHITE if lead else INK))
        pdf.cell(cw - 8, 4.5, _t(label))
        pdf.set_xy(x + 4, r.y + 7.5)
        pdf.set_font("helvetica", "B", 15)
        pdf.cell(cw - 8, 7, _t(value))
        pdf.set_xy(x + 4, r.y + 15)
        pdf.set_font("helvetica", "", 7)
        pdf.set_text_color(*(214, 228, 219) if lead else MUTED)
        pdf.multi_cell(cw - 8, 3.6, _t(foot))
    r.y += 32

    # ---- strengths / risks -------------------------------------------------
    col_w = (PAGE_W - 2 * MARGIN - 5) / 2
    strengths = (result.strengths or [])[:5]
    risks = (result.concerns or [])[:5]
    _card(pdf, r, MARGIN, r.y, col_w, 78, (240, 247, 243))
    _card(pdf, r, MARGIN + col_w + 5, r.y, col_w, 78, (252, 241, 239))
    for idx, (items, title, colour) in enumerate((
            (strengths, "Ratio Strengths", GREEN),
            (risks, "Ratio Risks", RED))):
        x = MARGIN + idx * (col_w + 5)
        pdf.set_xy(x + 5, r.y + 4)
        pdf.set_font("helvetica", "B", 10.5)
        pdf.set_text_color(*INK)
        pdf.cell(col_w - 20, 5.5, _t(title))
        _chip(pdf, x + col_w - 13, r.y + 3.6, str(len(items)), WHITE, colour)
        yy = r.y + 12
        pdf.set_font("helvetica", "", 8)
        for item in items:
            txt = _t(str(item))[:150]
            pdf.set_xy(x + 5, yy)
            pdf.multi_cell(col_w - 10, 3.9, "- " + txt)
            yy = pdf.get_y() + 1.2
            if yy > r.y + 74:
                break
    r.y += 84

    # ---- drivers ------------------------------------------------------------
    _section_title(pdf, r, "What moves the score")
    ranked = sorted(result.metrics, key=lambda m: m.score, reverse=True)[:8]
    track_x, track_w = MARGIN + 62, PAGE_W - MARGIN - 84
    for m in ranked:
        r.need(7)
        pdf.set_xy(MARGIN, r.y)
        pdf.set_font("helvetica", "", 8.5)
        pdf.set_text_color(63, 71, 68)
        pdf.cell(58, 4.6, _t(m.metric[:34]))
        pdf.set_fill_color(241, 243, 241)
        pdf.rect(track_x, r.y + .6, track_w, 3.2, style="F",
                 round_corners=True, corner_radius=1.6)
        pdf.set_fill_color(*band(m.score))
        pdf.rect(track_x, r.y + .6, max(1.5, track_w * m.score / 100), 3.2,
                 style="F", round_corners=True, corner_radius=1.6)
        pdf.set_xy(track_x + track_w + 3, r.y)
        pdf.set_font("courier", "B", 8)
        pdf.set_text_color(*INK)
        pdf.cell(10, 4.6, str(round(m.score)))
        r.y += 6.4
    r.y += 4

    # ---- revenue trend ------------------------------------------------------
    revenue_chart(pdf, r, model)
    r.y += 4

    # ---- valuation + key ratios ---------------------------------------------
    col_w2 = (PAGE_W - 2 * MARGIN - 5) / 2
    box_h = 46
    _card(pdf, r, MARGIN, r.y, col_w2, box_h)
    pdf.set_xy(MARGIN + 5, r.y + 3.5)
    pdf.set_font("helvetica", "B", 10); pdf.set_text_color(*INK)
    pdf.cell(col_w2 - 10, 5, "Valuation")
    yy = r.y + 11
    for label, metric in (("P/E", "PE Ratio"), ("P/S", "Price to Sales")):
        s = pd.to_numeric(model.series(metric), errors="coerce").dropna()
        s = s[(s > 0) & (s < 1000)]
        if s.empty:
            continue
        latest, med = float(s.iloc[-1]), float(s.median())
        pdf.set_font("helvetica", "", 8.5); pdf.set_text_color(63, 71, 68)
        pdf.set_xy(MARGIN + 5, yy)
        pdf.cell(col_w2 / 2 - 5, 4.4, label)
        pdf.set_font("courier", "B", 8.5); pdf.set_text_color(*INK)
        pdf.cell(col_w2 / 2 - 5, 4.4, f"{latest:.1f}x  (med {med:.1f}x)")
        yy += 5.2
    _card(pdf, r, MARGIN + col_w2 + 5, r.y, col_w2, box_h)
    pdf.set_xy(MARGIN + col_w2 + 10, r.y + 3.5)
    pdf.set_font("helvetica", "B", 10); pdf.set_text_color(*INK)
    pdf.cell(col_w2 - 10, 5, "Key Ratios")
    yy = r.y + 11
    for label, metric, fmt in (("Gross Margin", "Gross Margin", "%"),
                               ("ROCE", "Return on Capital Employed (ROCE) %", "%"),
                               ("Interest cover", "Interest Coverage Ratio", "x"),
                               ("Cash cycle", "Cash Conversion Cycle", "d")):
        s = pd.to_numeric(model.series(metric), errors="coerce").dropna()
        if s.empty:
            continue
        v = float(s.iloc[-1])
        txt = f"{v:.1f}{fmt}"
        pdf.set_font("helvetica", "", 8.5); pdf.set_text_color(63, 71, 68)
        pdf.set_xy(MARGIN + col_w2 + 10, yy)
        pdf.cell(col_w2 / 2 - 5, 4.4, label)
        pdf.set_font("courier", "B", 8.5); pdf.set_text_color(*INK)
        pdf.cell(col_w2 / 2 - 5, 4.4, txt)
        yy += 4.8
    r.y += box_h + 6

    # ---- health gauge ---------------------------------------------------------
    _gauge(pdf, r, result.total_score)
    r.y += 6

    # ---- profit waterfall -------------------------------------------------------
    _waterfall(pdf, r, model)
    r.y += 4

    # ---- deep dive charts ----------------------------------------------------------
    _plot_lines(pdf, r, "Margin ladder", "Gross -> EBITDA -> Net, latest years", [
        ("Gross", MID, _pct_series_vals(model, "Gross Margin")),
        ("EBITDA", GREEN, _pct_series_vals(model, "EBITDA Margin")),
        ("Net", AMBER, _pct_series_vals(model, "Net Profit Margin")),
    ], "%")
    _bar_block(pdf, r, "Leverage & working capital", [
        ("D/E", LIGHT, _vals(model, "Debt to Equity Ratio")),
        ("Interest cover", GREEN, _vals(model, "Interest Coverage Ratio")),
    ])
    _scorecard_block(pdf, r, result)
    _sector_block(pdf, r, model, result)
    _heatmap_block(pdf, r, model)
    _statements_block(pdf, r, model)

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
# small helpers shared by blocks
# --------------------------------------------------------------------------
def _series(model, *names) -> pd.Series:
    for n in names:
        s = pd.to_numeric(model.series(n), errors="coerce").dropna()
        if not s.empty:
            return s
    return pd.Series(dtype=float)


def _scale(s: pd.Series) -> pd.Series:
    if s.empty or abs(float(s.abs().max())) <= 3:
        return s * 100
    return s


def _vals(model, metric, pct: bool = False) -> list[float]:
    s = _series(model, metric)
    if pct:
        s = _scale(s)
    return [float(v) for v in s.tail(10)]


def _pct_series_vals(model, metric) -> list[float]:
    return _vals(model, metric, pct=True)


def _kpi_cards(model, result):
    pe = _series(model, "PE Ratio")
    pe = pe[(pe > 0) & (pe < 1000)]
    pe_txt, pe_foot = "n/a", ""
    if not pe.empty:
        latest, med = float(pe.iloc[-1]), float(pe.median())
        pe_txt = f"{latest:.1f}x"
        pe_foot = f"{'below' if latest < med else 'above'} own median {med:.1f}x"
    roe = _scale(_series(model, "Return on Equity (ROE) %"))
    roe_txt, roe_foot = "n/a", ""
    if not roe.empty:
        latest = float(roe.iloc[-1])
        prev = float(roe.iloc[-2]) if len(roe) > 1 else None
        roe_txt = f"{latest:.1f}%"
        if prev is not None:
            roe_foot = f"prev year {prev:.1f}% ({latest - prev:+.1f})"
    de = _series(model, "Debt to Equity Ratio")
    de_txt = f"{float(de.iloc[-1]):.2f}x" if not de.empty else "n/a"
    scored = result.metric("Debt to Equity Ratio")
    de_foot = ("within sector norms" if scored is None or scored.score >= 40
               else "above sector comfort zone")
    return [("Funda Score", f"{result.total_score:.0f}/100", result.verdict, ""),
            ("P/E Ratio", pe_txt, pe_foot, ""), ("Return on Equity", roe_txt,
                                                 roe_foot, ""),
            ("Debt / Equity", de_txt, de_foot, "")]


def _revenue_chart(pdf: _Doc, r: R):
    s = pd.to_numeric(model_sales_getter(pdf), errors="coerce") \
        if False else None  # replaced below
    return


def model_series_sales():  # pragma: no cover
    return None


def revenue_chart(pdf: _Doc, r: R, model):
    s = pd.to_numeric(_series(model, "Sales"), errors="coerce").dropna().tail(8)
    if s.empty:
        return
    peak = float(s.max()) or 1
    h = 34
    x, y = _chart_frame(pdf, r, "Revenue trend",
                        f"Sales, Rs crore, {s.index[0]}-{s.index[-1]}", h)
    inner = PAGE_W - 2 * MARGIN - 20
    n = len(s)
    step = inner / n
    ramp = [(205, 229, 216), (169, 211, 189), (109, 189, 147),
            (43, 139, 87), GREEN, GREEN_DARK]
    for i, (yr, v) in enumerate(s.items()):
        bh = max(3, float(v) / peak * (h - 8))
        colour = GREEN_DARK if v == peak else ramp[min(i, len(ramp) - 1)]
        pdf.set_fill_color(*colour)
        bx = x + i * step + step * .18
        pdf.rect(bx, y + h - bh, step * .64, bh, style="F")
        pdf.set_font("helvetica", "", 6)
        pdf.set_text_color(*(INK if i == n - 1 else MUTED))
        pdf.set_xy(bx - step * .18, y + h + 1)
        pdf.cell(step, 2.8, str(yr).replace("FY", ""), align="C")
        if v == peak:
            pdf.set_font("courier", "B", 6.5)
            pdf.set_text_color(*GREEN_DARK)
            pdf.set_xy(bx - step * .18, y + h - bh - 4)
            pdf.cell(step * .64 + step * .36, 3.5,
                     _t(f"Rs {v / 1e5:.2f}L cr" if v >= 1e5 else f"Rs {v:,.0f} cr"),
                     align="C")
    _finish_chart(pdf, r, h)


def _chart_frame(pdf: _Doc, r: R, title: str, sub: str, h: float) -> tuple[float, float]:
    """Card frame for one chart; returns (x, y) of plot area."""
    r.need(h + 14)
    w = PAGE_W - 2 * MARGIN
    _card(pdf, r, MARGIN, r.y, w, h + 14)
    pdf.set_xy(MARGIN + 5, r.y + 3)
    pdf.set_font("helvetica", "B", 9.5)
    pdf.set_text_color(*INK)
    pdf.cell(w - 10, 5, _t(title))
    pdf.set_font("helvetica", "", 7.5)
    pdf.set_text_color(*FAINT)
    pdf.set_xy(MARGIN + 5, r.y + 7.5)
    pdf.cell(w - 10, 4, _t(sub))
    r.y += 14
    return MARGIN + 5, r.y


def _finish_chart(pdf: _Doc, r: R, h: float):
    r.y += h + 6


def _axes(pdf: _Doc, x: float, y: float, w: float, h: float,
          lo: float, hi: float, fmt="{:.0f}"):
    pdf.set_draw_color(238, 240, 238)
    pdf.set_line_width(.2)
    for f in (0, .5, 1):
        yy = y + h * f
        pdf.line(x, yy, x + w, yy)
        pdf.set_font("helvetica", "", 6.5)
        pdf.set_text_color(*FAINT)
        pdf.set_xy(x - 12, yy - 1.6)
        pdf.cell(11, 3.2, fmt.format(hi - f * (hi - lo)), align="R")


def _plot_lines(pdf: _Doc, r: R, title: str, sub: str,
                series: list[tuple[str, tuple, list[float]]],
                suffix: str = "%"):
    vals_all = [v for _, _, vals in series for v in vals]
    if len(vals_all) < 3:
        return
    hi = max(max(vals) for _, _, vals in series) or 1
    lo = min(0.0, min(vals_all))
    h = 42
    x, y = _chart_frame(pdf, r, title, sub, h)
    plot_w = PAGE_W - 2 * MARGIN - 24
    _axes(pdf, x, y, plot_w, h, lo, hi, ("{" + ":.0f}" + suffix) if suffix == "%" else "{:.1f}")
    n = max(len(vals) for _, _, vals in series)
    for name, colour, vals in series:
        if len(vals) < 2:
            continue
        pdf.set_draw_color(*colour)
        pdf.set_line_width(.6)
        pts = []
        for i, v in enumerate(vals):
            px = x + i / max(1, len(vals) - 1) * plot_w
            py = y + h - (v - lo) / ((hi - lo) or 1) * h
            pts.append((px, py))
        for i in range(len(pts) - 1):
            pdf.line(*pts[i], *pts[i + 1])
        pdf.set_fill_color(*colour)
        lx, ly = pts[-1]
        pdf.ellipse(lx - 1, ly - 1, 2, 2, style="F")
        pdf.set_font("helvetica", "", 7)
        pdf.set_text_color(*colour)
        pdf.set_xy(min(lx, x + plot_w - 22), ly - 5)
        pdf.cell(22, 3, f"{name} {vals[-1]:.1f}{suffix}")
    _finish_chart(pdf, r, h)


def _bar_block(pdf: _Doc, r: R, title: str,
               series: list[tuple[str, tuple, list[float]]]):
    vals_all = [v for _, _, vals in series for v in vals]
    if len(vals_all) < 3:
        return
    mx = max(abs(v) for v in vals_all) or 1
    h = 40
    x, y = _chart_frame(pdf, r, title, "Latest years side by side", h)
    plot_w = PAGE_W - MARGIN - 20 - x
    n_years = max(len(vals) for _, _, vals in series)
    group = plot_w / n_years
    # gridlines + y labels
    pdf.set_draw_color(238, 240, 238)
    pdf.set_line_width(.2)
    pdf.set_font("helvetica", "", 6.5)
    for f in (0, .5, 1):
        yy = y + h * f
        pdf.line(x, yy, x + plot_w, yy)
        pdf.set_text_color(*FAINT)
        pdf.set_xy(x - 13, yy - 1.6)
        pdf.cell(12, 3.2, f"{mx * (1 - f):.1f}", align="R")
    bw = min(5, group / (len(series) + 1))
    for si, (name, colour, vals) in enumerate(series):
        pdf.set_fill_color(*colour)
        for i, v in enumerate(vals):
            bh = abs(v) / mx * h
            bx = x + i * group + group * .5 - bw * len(series) / 2 + si * bw
            pdf.rect(bx, y + h - bh, bw - .6, bh, style="F")
    # year labels under each group
    pdf.set_font("helvetica", "", 6.5)
    pdf.set_text_color(*FAINT)
    for i in range(n_years):
        pdf.set_xy(x + i * group, y + h + 1.5)
        pdf.cell(group, 3, f"Yr {i + 1}", align="C")
    # legend with swatches, both entries
    lx = x
    for name, colour, _vals in series:
        pdf.set_fill_color(*colour)
        pdf.rect(lx, y + h + 6.5, 3, 3, style="F")
        pdf.set_font("helvetica", "", 7.5)
        pdf.set_text_color(*BODY)
        pdf.set_xy(lx + 4.5, y + h + 5.6)
        pdf.cell(40, 4, name)
        lx += pdf.get_string_width(name) + 12
    _finish_chart(pdf, r, h + 8)


def _scorecard_block(pdf: _Doc, r: R, result):
    rows = sorted(result.metrics, key=lambda m: m.score, reverse=True)
    if not rows:
        return
    row_h = 5.4
    h = min(len(rows), 11) * row_h + 4
    x, y = _chart_frame(pdf, r, "Ratio scorecard",
                        "Scored against sector bands (weak 40 / strong 66)", h)
    lx = x + 58
    tw = PAGE_W - MARGIN - 20 - lx
    pdf.set_draw_color(182, 214, 195)
    pdf.line(lx + tw * .66, y, lx + tw * .66, y + h - 2)
    pdf.set_draw_color(224, 182, 176)
    pdf.line(lx + tw * .40, y, lx + tw * .40, y + h - 2)
    for i, m in enumerate(rows[:11]):
        yy = y + i * row_h
        pdf.set_font("helvetica", "", 7.5)
        pdf.set_text_color(63, 71, 68)
        pdf.set_xy(x, yy)
        pdf.cell(56, 3.6, _t(m.metric[:32]))
        pdf.set_fill_color(*band(m.score))
        pdf.rect(lx, yy, max(1.5, tw * m.score / 100), 3, style="F")
        pdf.set_font("courier", "", 6.5)
        pdf.set_text_color(*BODY)
        pdf.set_xy(lx + tw * m.score / 100 + 1.5, yy)
        pdf.cell(24, 3.6, _t(str(m.display(m.latest))))
    _finish_chart(pdf, r, h)


def _sector_block(pdf: _Doc, r: R, model, result):
    from .scoring import compare_sectors
    from .sectors import SECTORS
    frame = compare_sectors(model, list(SECTORS.values()))
    if frame.empty:
        return
    row_h = 5.2
    h = len(frame) * row_h + 3
    x, y = _chart_frame(pdf, r, "Sector lens",
                        "Same numbers under every rule book", h)
    lx = x + 62
    tw = PAGE_W - MARGIN - 44 - lx
    hot = result.sector.name.lower()
    for i, (_, row) in enumerate(frame.iterrows()):
        yy = y + i * row_h
        sc = float(row["Score"])
        name = str(row["Sector lens"])
        is_hot = name.strip().lower().startswith(hot[:12])
        pdf.set_font("helvetica", "B" if is_hot else "", 7)
        pdf.set_text_color(*(INK if is_hot else (63, 71, 68)))
        pdf.set_xy(x, yy)
        pdf.cell(60, 3.4, _t(name[:34]))
        pdf.set_fill_color(*band(sc))
        pdf.rect(lx, yy, max(1.5, tw * sc / 100), 3.2, style="F")
        pdf.set_font("courier", "", 6.5)
        pdf.set_text_color(*BODY)
        pdf.set_xy(lx + tw * sc / 100 + 1.5, yy)
        word = "STRONG" if sc >= 66 else "NEUTRAL" if sc >= 40 else "WEAK"
        pdf.cell(26, 3.6, f"{sc:.0f} {word}")
    _finish_chart(pdf, r, h)


def _heatmap_block(pdf: _Doc, r: R, model):
    defs = [("Sales Gr.", "Sales Growth", True),
            ("EBITDA Mg", "EBITDA Margin", True),
            ("Net Mg", "Net Profit Margin", True),
            ("ROE", "Return on Equity (ROE) %", True),
            ("D/E", "Debt to Equity Ratio", False),
            ("Int.Cov", "Interest Coverage Ratio", False)]
    labels, cols = [], []
    for lab, metric, pct in defs:
        s = _scale(_series(model, metric)) if pct else _series(model, metric)
        vals = [float(v) for v in s.tail(10)]
        if len(vals) >= 3:
            labels.append(lab)
            cols.append(vals)
    if len(labels) < 3:
        return
    import numpy as np
    n = len(labels)
    cell = 9.5
    size = n * cell
    x, y = _chart_frame(pdf, r, "How the ratios move together",
                        "Pairwise correlation across history", size + 4)
    for ri in range(n):
        for ci in range(n):
            if ri == ci:
                v = 1.0
            else:
                k = min(len(cols[ri]), len(cols[ci]))
                cc = np.corrcoef(cols[ri][-k:], cols[ci][-k:])[0, 1]
                v = 0.0 if np.isnan(cc) else float(cc)
            t = min(1, abs(v))
            if v >= 0:
                colour = (int(23 + t * (23 - 23)), int(114 + t * (158 - 114)),
                          int(69 + t * (107 - 69)))
            else:
                colour = (int(180 - t * 16), int(72 + t * 8), int(60 + t * 3))
            pdf.set_fill_color(*colour)
            pdf.rect(x + ci * cell, y + ri * cell, cell - 1, cell - 1, style="F")
            lum = .299 * colour[0] + .587 * colour[1] + .114 * colour[2]
            pdf.set_font("courier", "B", 6.5)
            pdf.set_text_color(*(WHITE if t > .55 else BODY))
            pdf.set_xy(x + ci * cell, y + ri * cell + 1.2)
            pdf.cell(cell - 1, 3.4, f"{v:+.2f}", align="C")
    for i, lab in enumerate(labels):
        pdf.set_font("helvetica", "", 6.5)
        pdf.set_text_color(63, 71, 68)
        pdf.set_xy(x - 22, y + i * cell + 1.4)
        pdf.cell(21, 3, lab, align="R")
        pdf.set_xy(x + i * cell, y + n * cell + 1)
        pdf.cell(cell, 3, lab)
    _finish_chart(pdf, r, size + 4)


def _gauge(pdf: _Doc, r: R, score: float):
    score = max(0.0, min(100.0, float(score)))
    h = 34
    x, y = _chart_frame(pdf, r, "Financial health",
                        "Composite index across the scored ratios", h)
    cx, cy, rad = x + (PAGE_W - 2 * MARGIN - 20) / 2, y + h - 4, 26
    try:
        pdf.set_line_width(5)
        pdf.set_draw_color(220, 223, 220)
        pdf.arc(cx, cy, rad, 180, 360)
        pdf.set_draw_color(*MID)
        pdf.arc(cx, cy, rad, 180, 180 + 180 * score / 100)
        pdf.set_line_width(.2)
    except Exception:                                    # noqa: BLE001
        pdf.set_fill_color(241, 243, 241)
        pdf.rect(cx - rad, cy - 3, 2 * rad, 4, style="F")
        pdf.set_fill_color(*MID)
        pdf.rect(cx - rad, cy - 3, 2 * rad * score / 100, 4, style="F")
    label = "Strong" if score >= 66 else "Stable" if score >= 40 else "At risk"
    pdf.set_font("helvetica", "B", 13)
    pdf.set_text_color(*INK)
    pdf.set_xy(cx - 20, cy - 12)
    pdf.cell(40, 6, f"{label} - {score:.0f}/100", align="C")
    _finish_chart(pdf, r, h)


def _waterfall(pdf: _Doc, r: R, model):
    year = None
    for y in reversed([str(yr) for yr in model.years]):
        if y.upper() not in ("TTM", "TREND", "MEAN", "MEDIAN"):
            year = y
            break
    if year is None:
        return

    def col(*names):
        for n in names:
            frame_names = [n]
            s = pd.to_numeric(model.historical.loc[n], errors="coerce") \
                if n in model.historical.index else pd.Series(dtype=float)
            if not s.empty and year in s.index and pd.notna(s[year]):
                return float(s[year])
        return None

    sales = col("Sales")
    cogs = col("COGS")
    pbt = col("Earnings Before Tax", "Profit before tax")
    net = col("Net Profit")
    tax = col("Tax")
    if sales is None or net is None:
        return
    gross = (sales - cogs) if cogs is not None else None
    bucket = (gross + (col("Other Income") or 0) - pbt) if gross is not None and pbt else None
    steps = [("Sales", sales), ("Cost of goods", -(cogs or 0)),
             ("Gross profit", gross or 0),
             ("Opex, dep. & interest", -(bucket or 0)),
             ("Profit before tax", pbt or 0), ("Tax", -(tax or 0)),
             ("Net profit", net)]
    h = 46
    x, y = _chart_frame(pdf, r, f"How {year} revenue becomes profit",
                        "Income statement flow (Rs crore)", h)
    inner = PAGE_W - 2 * MARGIN - 20
    step_w = inner / len(steps)
    peak = max(abs(v) for _, v in steps) or 1
    running = 0.0
    prev_top = None
    for i, (name, v) in enumerate(steps):
        bh = abs(v) / peak * (h - 10)
        base = y + h - 4
        if name in ("Gross profit", "Profit before tax", "Net profit"):
            colour = GREEN
            top = base - bh
        elif name == "Sales":
            colour = (154, 160, 157)
            top = base - bh
            running = v
        else:
            colour = RED
            new_run = running + v
            top = base - (new_run / peak * (h - 10)) if running else base - bh
            bh = abs(running - new_run) / peak * (h - 10) if running else bh
            running = new_run
        bx = x + i * step_w + step_w * .2
        pdf.set_fill_color(*colour)
        pdf.rect(bx, base - bh, step_w * .6, bh, style="F")
        if prev_top is not None and name != "Sales":
            pdf.set_draw_color(200, 205, 200)
            pdf.set_line_width(.25)
            pdf.line(bx - step_w * .2, prev_top, bx, base - bh)
        prev_top = base - bh
        pdf.set_font("helvetica", "", 6)
        pdf.set_text_color(63, 71, 68)
        pdf.set_xy(bx - step_w * .2, base + 1)
        pdf.cell(step_w * .8, 2.8, _t(name.split(" ")[0][:9]), align="C")
        # numbers on the bars only for Sales and Net profit (mirrors the site);
        # every other value lives in the flow table below the chart
        if name in ("Sales", "Net profit"):
            pdf.set_font("courier", "B", 6)
            pdf.set_text_color(*INK)
            pdf.set_xy(bx - step_w * .2, base - bh - 3.4)
            pdf.cell(step_w * .8, 3, _t(f"{abs(v):,.0f}"), align="C")
    # the numbers the web version shows on hover, listed under the chart
    pdf.set_font("helvetica", "", 6.5)
    col_w2 = (PAGE_W - 2 * MARGIN - 20) / 2
    for i, (name, v) in enumerate(steps):
        col = i % 2
        row = i // 2
        xx = x + col * col_w2
        yy2 = y + h + 9 + row * 3.6
        pdf.set_text_color(63, 71, 68)
        pdf.set_xy(xx, yy2)
        pdf.cell(col_w2 * .6, 3, _t(name))
        pdf.set_font("courier", "", 6.5)
        pdf.set_text_color(*INK)
        pdf.cell(col_w2 * .4, 3, _t(f"{v:,.0f}"), align="R")
        pdf.set_font("helvetica", "", 6.5)
    _finish_chart(pdf, r, h + 9 + ((len(steps) + 1) // 2) * 3.6 + 2)


def _statements_block(pdf: _Doc, r: R, model):
    wanted = ["Sales", "COGS", "EBITDA", "Depreciation", "Interest",
              "Earnings Before Tax", "Tax", "Net Profit"]
    years = [y for y in [str(yr) for yr in model.years]
             if y.upper() != "TTM"][-6:]
    rows = []
    for name in wanted:
        s = pd.to_numeric(model.series(name), errors="coerce")
        if s.empty:
            continue
        s = s.reindex([y for y in model.years]).dropna(how="all")
        vals = []
        for y in years:
            v = s[y] if y in s.index else None
            vals.append(None if v is None or pd.isna(v) else float(v))
        if any(v is not None for v in vals):
            rows.append((name, vals))
    if not rows:
        return
    row_h = 5.2
    h = len(rows) * row_h + 6
    x, y = _chart_frame(pdf, r, "Income statement",
                        f"Key lines, Rs crore, {years[0]}-{years[-1]}", h)
    col_w = (PAGE_W - MARGIN - 20 - x) / (len(years) + 1)
    pdf.set_font("courier", "B", 7)
    pdf.set_text_color(*INK)
    pdf.set_xy(x, y)
    pdf.cell(34, 3.6, "")
    for j, yr in enumerate(years):
        pdf.set_xy(x + 36 + j * col_w, y)
        pdf.cell(col_w - 2, 3.6, yr.replace("FY", ""), align="R")
    yy = y + 5
    for name, vals in rows:
        head = name in ("Sales", "Net Profit")
        pdf.set_font("helvetica", "B" if head else "", 7.2)
        pdf.set_text_color(*(INK if head else (63, 71, 68)))
        pdf.set_xy(x, yy)
        pdf.cell(34, 4, _t(name[:26]))
        for j, v in enumerate(vals):
            pdf.set_font("courier", "B" if head else "", 7)
            pdf.set_text_color(*INK)
            pdf.set_xy(x + 36 + j * col_w, yy)
            pdf.cell(col_w - 2, 4, "-" if v is None else f"{v:,.0f}", align="R")
        if head:
            pdf.set_draw_color(238, 240, 238)
            pdf.set_line_width(.2)
            pdf.line(x, yy + 4.4, PAGE_W - MARGIN - 6, yy + 4.4)
        yy += row_h
    _finish_chart(pdf, r, h)

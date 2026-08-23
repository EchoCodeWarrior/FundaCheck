"""
FundaCheck — an AI-assisted fundamental analysis dashboard.

Upload a 3-statement Excel model, pick the sector, and the terminal turns it
into an interactive dashboard plus a STRONG / NEUTRAL / WEAK verdict that is
judged against sector-specific benchmarks rather than one universal rule book.

Run it with:   streamlit run app.py
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st

from core import charts as C
from core import design_blocks as D
from core import ratio_charts as R
from core.llm import LLMConfig, analyse, answer_question, config_from_env
from core.derive import fill_missing_ratios
from core.parser import ParseError, load_model
from core.scoring import assess, compare_sectors
from core.sectors import (
    PERCENT_METRICS,
    SECTORS,
    detect_sector,
    get_sector,
    sector_choices,
)

# Ratios stored as a decimal that read better as a percentage than as "0.02".
EXTRA_PERCENT_METRICS = {"CFO / Sales", "CFO / Total Assets", "CFO / Total Debt",
                         "Dividend Payout %", "Retained Earnings%"}

# Figures reported in crore in an Indian 3-statement model.
CURRENCY_METRICS = {
    "Sales", "Net Profit", "EBITDA", "EBIT (OPM)", "Gross Margin",
    "Total Asset", "Total Liabilities", "Borrowings", "Reserves",
    "Cash from Operating Activity", "Cash from Investing Activity",
    "Cash from Financing Activity", "Net Cash Flow", "Market Capitalization",
}

LOGGER = logging.getLogger("fundacheck")

APP_DIR = Path(__file__).parent
SAMPLE = APP_DIR / "sample_data" / "3S_model_sample.xlsx"

st.set_page_config(
    page_title="FundaCheck · Fundamental Analysis",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------------------------------
# small UI helpers
# --------------------------------------------------------------------------
def inject_css(mode: str = "dark") -> None:
    """
    Load the stylesheet, plus the light overrides when day mode is on.

    Streamlit strips <script> from markdown, so the theme cannot be stamped onto
    the root element and switched with a CSS attribute selector — the light
    rules are injected as their own sheet instead.
    """
    css = (APP_DIR / "assets" / "style.css").read_text()
    if mode == "light":
        css += "\n" + (APP_DIR / "assets" / "light.css").read_text()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


@contextmanager
def card(title: str):
    """
    A titled panel.

    Streamlit widgets cannot be written inside a raw HTML <div>, so the panel is
    a real bordered container and the styling is applied from style.css.
    """
    with st.container(border=True):
        st.markdown(f'<div class="card-title">{title}</div>', unsafe_allow_html=True)
        yield


def fmt(value: float | None, metric: str = "") -> str:
    """Format one metric for display, in its own natural unit."""
    if value is None or pd.isna(value):
        return "n/a"
    if metric in PERCENT_METRICS or metric in EXTRA_PERCENT_METRICS:
        return f"{value * 100:.1f}%"
    if "Days" in metric or "Cycle" in metric:
        return f"{value:.0f}<small> days</small>"
    if metric in CURRENCY_METRICS:
        return f"{value:,.0f}<small> Cr</small>"
    if "Ratio" in metric or "Turnover" in metric or "Coverage" in metric:
        return f"{value:.2f}<small>x</small>"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def kpi_tile(label: str, value: str, delta: str = "", direction: str = "",
             spark: str = "", period: str = "", footer: str = "",
             variant: str = "") -> None:
    delta_html = f'<div class="delta {direction}">{delta}</div>' if delta else ""
    # Sheets do not always run to the same last period (the ratio sheet may stop
    # at FY26 while the P&L carries a TTM column), so every tile states its own.
    period_html = f'<span class="period">{period}</span>' if period else ""
    # Word values ("Profitability") need a smaller size than figures, or they
    # break mid-word inside a narrow tile.
    size_class = " value-text" if not any(ch.isdigit() for ch in value) else ""
    st.markdown(
        f'<div class="kpi {variant}"><div class="label">{label}{period_html}</div>'
        f'<div class="value{size_class}">{value}</div>{delta_html}{spark}{footer}</div>',
        unsafe_allow_html=True,
    )


def note_list(title: str, items: list[str], kind: str = "") -> None:
    if not items:
        return
    bullets = "".join(f"<li>{str(i)}</li>" for i in items)
    st.markdown(
        f'<div class="note-block {kind}"><div class="card-title">{title}</div>'
        f"<ul>{bullets}</ul></div>",
        unsafe_allow_html=True,
    )


def chart(fig, key: str) -> None:
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={"displayModeBar": False})


# --------------------------------------------------------------------------
# sidebar: data in, sector, LLM
# --------------------------------------------------------------------------
# The ten ratios the front page leads with. Order matters: profitability and
# returns first, then risk, then momentum, cash quality and market context.
HEADLINE_RATIOS: list[tuple[str, str, bool]] = [
    ("Return on Equity (ROE) %", "ROE", True),
    ("Return on Capital Employed (ROCE) %", "ROCE", True),
    ("Net Profit Margin", "Net margin", True),
    ("EBITDA Margin", "EBITDA margin", True),
    ("Debt to Equity Ratio", "Debt / equity", False),
    ("Interest Coverage Ratio", "Interest cover", True),
    ("Sales Growth", "Sales growth", True),
    ("CFO / Sales", "CFO / sales", True),
    ("Cash Conversion Cycle", "Cash cycle", False),
    ("PE Ratio", "P/E", True),
]

NAV_PAGES = [
    ("overview", "Dashboard"),
    ("ratios", "Ratio deep dive"),
    ("lens", "Sector lens"),
    ("statements", "Statements"),
    ("qa", "Ask the analyst"),
]


def analyst_config() -> LLMConfig:
    """
    Build the analyst connection from Streamlit secrets or the environment.

    Nothing about this is user-facing: the app either has keys or it does not,
    and falls back to the deterministic note when it does not.
    """
    try:
        secrets = dict(st.secrets)
    except Exception:                       # noqa: BLE001 - no secrets file present
        secrets = {}
    return config_from_env("groq", secrets=secrets)


def step(number: int, label: str) -> None:
    st.markdown(
        f'<div class="step"><span class="n">{number}</span>{label}'
        f'<span class="rule"></span></div>',
        unsafe_allow_html=True,
    )


def sidebar() -> tuple[object, str, str]:
    with st.sidebar:
        st.markdown(
            '<div class="side-brand"><div class="side-mark">F</div>'
            '<div><div class="name">FundaCheck</div>'
            '<div class="tag">FUNDAMENTAL ANALYSIS</div></div></div>',
            unsafe_allow_html=True,
        )

        # ---- navigation ----
        st.markdown('<div class="nav-head">MENU</div>', unsafe_allow_html=True)
        current = st.session_state.setdefault("page", "overview")
        # The click is recorded here but acted on at the very end of the
        # sidebar. Rerunning from inside this loop would abort the script before
        # the widgets below (the uploader above all) are instantiated, and
        # Streamlit discards the state of any widget a run did not render — which
        # is how navigating between pages used to throw the uploaded file away.
        navigate_to = None
        for key, label in NAV_PAGES:
            active = key == current
            if st.button(label, key=f"nav-{key}", use_container_width=True,
                         type="primary" if active else "secondary"):
                navigate_to = key

        st.markdown('<div class="nav-head">GENERAL</div>', unsafe_allow_html=True)
        st.session_state.setdefault("dark_mode", False)
        dark = st.toggle(
            "Dark mode", key="dark_mode",
            help="Both themes use their own validated palette — the light one is "
                 "a separate set of colours, not the dark set inverted.",
        )

        step(1, "Your data")
        upload = st.file_uploader(
            "3-statement model (.xlsx)", type=["xlsx", "xlsm"],
            label_visibility="collapsed", key="upload",
            help="Any Screener.in-style workbook.",
        )
        # The uploader is the single source of truth for "is a file loaded".
        # That only holds because every st.rerun() in this app now happens after
        # the sidebar has fully rendered — a rerun fired before this widget is
        # instantiated would make Streamlit discard its state, which is exactly
        # how navigating between pages used to lose the file. Keep it that way.
        if upload is not None:
            st.session_state.demo_on = False

        use_sample = st.toggle(
            "Load the demo model", key="demo_on", disabled=upload is not None,
            help="A real 3-statement model, if you want to try FundaCheck "
                 "before uploading your own.",
        )

        if upload is not None:
            source, source_label = upload.getvalue(), upload.name
        elif use_sample:
            source, source_label = SAMPLE, "Demo model"
        else:
            source, source_label = None, ""

        if source is not None:
            st.markdown(
                f'<div class="loaded-chip"><span class="dot"></span>'
                f'<span class="txt"><b>{source_label}</b></span></div>',
                unsafe_allow_html=True,
            )

        step(2, "Sector lens")
        choices = sector_choices()
        keys = [k for k, _ in choices]
        # Held in a plain state key rather than the widget's own key: Streamlit
        # forbids writing to a widget key once the widget exists, and detection
        # (in main(), after the workbook loads) has to be able to set it.
        preferred = st.session_state.setdefault("sector_pref", "generic")
        sector_key = st.selectbox(
            "Sector", options=keys, format_func=lambda k: dict(choices)[k],
            index=keys.index(preferred) if preferred in keys else 0,
            label_visibility="collapsed",
            help="Benchmarks and pillar weights change with the sector.",
        )
        st.session_state.sector_pref = sector_key
        st.caption(get_sector(sector_key).notes)

    if navigate_to and navigate_to != current:
        # Safe here: every sidebar widget above has been instantiated, so their
        # state survives the rerun.
        st.session_state.page = navigate_to
        st.rerun()

    C.set_theme("dark" if dark else "light")
    return source, sector_key, source_label


# --------------------------------------------------------------------------
# page sections
# --------------------------------------------------------------------------
def masthead(model, sector_name: str) -> None:
    """
    The page hero: company, sector, last traded price and market cap.

    Laid out per the FundaCheck design — the name at display size, the market
    data in its own white card to the right.
    """
    price = model.meta.get("current_price")
    mcap = model.meta.get("market_cap")

    stats = ""
    if price:
        whole, _, frac = f"{price:,.2f}".partition(".")
        stats += (
            '<div><div class="lbl">LAST TRADED PRICE</div>'
            f'<div class="val">₹{whole}<small>.{frac}</small></div></div>'
        )
    if mcap:
        # Indian convention: a lakh crore reads better than eight digits.
        pretty = f"₹{mcap / 1e5:.2f}L cr" if mcap >= 1e5 else f"₹{mcap:,.0f} cr"
        if stats:
            stats += '<div class="hero-rule"></div>'
        stats += f'<div><div class="lbl">MKT CAP</div><div class="val">{pretty}</div></div>'
    if stats:
        stats = f'<div class="hero-stat">{stats}</div>'

    st.markdown(
        f"""
        <div class="masthead">
          <div style="display:flex;align-items:flex-start;gap:20px;flex-wrap:wrap">
            <div>
              <h1>{model.company.title()}</h1>
              <div class="sub">{sector_name.upper()} &nbsp;·&nbsp;
                   {model.years[0]}–{model.latest_year} &nbsp;·&nbsp;
                   {len(model.years)} PERIODS</div>
            </div>
            <div style="margin-left:auto">{stats}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_row(model, result) -> None:
    """
    The ten ratios that carry a fundamental call, five to a row.

    Each tile shows the latest value, the year-on-year move, a sparkline, and —
    where the sector defines a band for it — whether the number currently sits
    in the strong, adequate or weak zone for THIS sector.
    """
    # The design leads with the score itself, then the ratios behind it.
    # Card order follows the design: the score, then the three ratios an analyst
    # reaches for first, then everything else in fours.
    by_metric = {metric: (metric, label, higher) for metric, label, higher in HEADLINE_RATIOS}
    lead_metrics = ["PE Ratio", "Return on Equity (ROE) %", "Debt to Equity Ratio"]
    rest = [row for row in HEADLINE_RATIOS if row[0] not in lead_metrics]

    lead = st.columns(4)
    with lead[0]:
        kpi_tile(
            "Funda Score", f"{result.total_score:.0f}<small>/100</small>",
            footer=f'<span class="band">{result.verdict} · sector adjusted</span>',
            variant="kpi-score",
        )
    for column, metric in zip(lead[1:], lead_metrics):
        if metric in by_metric:
            _ratio_tile(model, result, column, *by_metric[metric])
    st.write("")

    for chunk in (rest[:4], rest[4:]):
        columns = st.columns(4)
        for column, (metric, label, higher_better) in zip(columns, chunk):
            _ratio_tile(model, result, column, metric, label, higher_better)
        st.write("")


def _ratio_tile(model, result, column, metric: str, label: str,
                higher_better: bool) -> None:
    """One headline-ratio card: value, year-on-year move, and its sector band."""
    series = model.series(metric).dropna()
    with column:
        if series.empty:
            kpi_tile(label, "n/a", "not in this workbook")
            return

        latest = float(series.iloc[-1])
        delta_text, direction = "", ""
        if len(series) > 1:
            previous = float(series.iloc[-2])
            if previous:
                change = (latest - previous) / abs(previous) * 100
                improving = change >= 0 if higher_better else change < 0
                direction = "up" if improving else "down"
                delta_text = f"{'▲' if change >= 0 else '▼'} {abs(change):.1f}% YoY"

        scored = result.metric(metric)
        band_html = ""
        if scored is not None:
            tone = "good" if scored.score >= 70 else "warn" if scored.score >= 45 else "bad"
            band_html = f'<span class="band {tone}">{scored.verdict} for sector</span>'

        kpi_tile(
            label, fmt(latest, metric), delta_text, direction,
            spark=C.sparkline_svg(series.tail(9), higher_better),
            period=str(series.index[-1]), footer=band_html,
        )


def verdict_panel(result, note: dict) -> None:
    left, right = st.columns([1.35, 1])
    with left:
        st.markdown(
            f"""
            <div class="verdict" style="--accent:{result.colour};--amber-rail:{result.colour}">
              <span class="tag" style="color:{result.colour};
                    border:1px solid {result.colour}55; background:{result.colour}18;">
                {result.verdict}
              </span>
              <h2 style="color:{result.colour}">{result.headline}</h2>
              <p>{note.get('summary', '')}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("")
        quality = (
            f"{result.earnings_quality:.2f}x" if result.earnings_quality is not None else "n/a"
        )
        covered = len(result.metrics)
        strip = st.columns(3)
        with strip[0]:
            kpi_tile("Earnings quality", quality, "3Y avg CFO / PAT")
        with strip[1]:
            kpi_tile("Ratios scored", f"{covered}", f"{len(result.data_gaps)} not found")
        with strip[2]:
            best = max(result.pillar_scores, key=result.pillar_scores.get)
            kpi_tile("Strongest pillar", best.title(),
                     f"{result.pillar_scores[best]:.0f}/100")
        st.write("")

        if note.get("sector_context"):
            st.markdown(
                f'<div class="note-block"><div class="card-title">Sector context · '
                f'{result.sector.name}</div><p style="margin:.35rem 0 0;font-size:.89rem;'
                f'line-height:1.55">{note["sector_context"]}</p></div>',
                unsafe_allow_html=True,
            )
    with right:
        with card("What moves the score"):
            st.markdown(D.score_drivers(result), unsafe_allow_html=True)


def analyst_note(result, note: dict) -> None:
    if note.get("_error"):
        st.warning(f"LLM call failed, showing the rule-based note instead. ({note['_error']})")
    columns = st.columns(3)
    with columns[0]:
        note_list("Strengths", note.get("strengths", []) or result.strengths)
    with columns[1]:
        note_list("Risks", note.get("risks", []) or result.concerns, kind="risk")
    with columns[2]:
        note_list("What to watch", note.get("what_to_watch", []), kind="watch")

    source = "rule-based engine" if note.get("_offline") else f"LLM · {note.get('_model', '')}"
    st.markdown(
        f'<p class="caption-mono">Commentary source: {source} &nbsp;·&nbsp; '
        f'confidence: {note.get("confidence", "n/a")}</p>',
        unsafe_allow_html=True,
    )


def bento(title: str, subtitle: str, key: str, figure, span: str = "") -> None:
    """One bento tile: a titled card wrapping a single chart."""
    with card(title):
        if subtitle:
            st.markdown(f'<p class="tile-sub">{subtitle}</p>', unsafe_allow_html=True)
        chart(figure, key=key)


def design_panels(model, result) -> None:
    """The Revenue Trend / Valuation / Key Ratios / Health row from the design."""
    left, middle, right = st.columns([1.25, 1, 1])
    with left:
        with card("Revenue Trend"):
            st.markdown(D.revenue_trend(model), unsafe_allow_html=True)
    with middle:
        with card("Valuation"):
            st.markdown('<p class="tile-sub">Multiples against the company\'s own '
                        'history</p>', unsafe_allow_html=True)
            st.markdown(D.valuation_panel(model), unsafe_allow_html=True)
    with right:
        with card("Key Ratios"):
            st.markdown(D.key_ratios(model, result), unsafe_allow_html=True)

    st.write("")
    left, right = st.columns([1, 1])
    with left:
        with card("Financial Health"):
            st.markdown(D.health_gauge(result), unsafe_allow_html=True)
    with right:
        with card("Five-pillar profile"):
            chart(C.pillar_radar(result), key="radar")

    st.write("")
    sankey_title, sankey_svg = D.income_sankey(model)
    if sankey_svg:
        with card(sankey_title):
            st.markdown('<p class="tile-sub">Income statement flow, ₹ crore</p>',
                        unsafe_allow_html=True)
            st.markdown(sankey_svg, unsafe_allow_html=True)


def overview_tab(model, result) -> None:
    """The Dashboard page: the design's panels, then the income-statement flow."""
    design_panels(model, result)


def ratio_bento(model, result) -> None:
    """The ten headline ratios, one chart each — the Ratio deep dive grid."""
    # Row 1 — the two return ratios, side by side and directly comparable
    left, right = st.columns([1, 1])
    with left:
        bento("Return on equity", "How hard shareholder money is working",
              "roe", R.return_trend(model, result, "Return on Equity (ROE) %"))
    with right:
        bento("Return on capital employed", "The same question, but debt counts too",
              "roce", R.return_trend(model, result, "Return on Capital Employed (ROCE) %"))

    left, right = st.columns([1.35, 1])
    with left:
        bento("Sales to profit", "Which rung of the ladder loses the most",
              "ladder", R.profit_ladder(model))
    with right:
        bento("EBITDA margin vs sector", "Bar is today, tick is the 3-year average",
              "bullet", R.margin_bullet(model, result))
        bento("Momentum", "Growth above the line, contraction below",
              "growth", R.growth_columns(model, "Sales Growth"))

    left, right = st.columns([1, 1])
    with left:
        bento("Funding mix", "Share of capital that is borrowed, year by year",
              "mix", R.funding_mix(model))
    with right:
        bento("Interest cover", "Distance from the line where profit stops covering interest",
              "cover", R.interest_cover_zone(model, result))

    left, right = st.columns([1, 1.15])
    with left:
        bento("Earnings quality", "The gap between reported profit and actual cash",
              "cashq", R.cash_quality_dumbbell(model))
    with right:
        bento("Cash conversion cycle", "Collected and held, minus what suppliers fund",
              "ccc", R.cash_cycle_bridge(model))

    bento("Valuation", "Today's P/E against the company's own history",
          "pe", R.valuation_strip(model))


def ratios_tab(model, result) -> None:
    ratio_bento(model, result)
    st.write("")
    with card("Ratio scorecard — scored against sector bands"):
        chart(C.scorecard_bars(result), key="scorecard")

    st.write("")
    left, right = st.columns([1, 1])
    with left:
        with card("Leverage & solvency"):
            chart(C.leverage_panel(model), key="lev")
    with right:
        with card("Working capital cycle"):
            chart(C.working_capital_cycle(model), key="wc")

    st.write("")
    with card("Explore any ratio through time"):
        available = [m for m in model.ratios.index] or list(model.historical.index)
        default = "Return on Capital Employed (ROCE) %"
        metric = st.selectbox(
            "Ratio", available,
            index=available.index(default) if default in available else 0,
            label_visibility="collapsed",
        )
        band = result.sector.benchmarks.get(metric)
        series = model.series(metric).dropna()
        if series.empty:
            st.info("No history available for that ratio.")
        else:
            chart(C.trend_line(series, metric, band), key="trend")
            if band:
                st.markdown(
                    f'<p class="caption-mono">{result.sector.name} band · '
                    f'weak {fmt(band[0], metric)} · strong {fmt(band[1], metric)}</p>',
                    unsafe_allow_html=True,
                )


def statements_tab(model) -> None:
    tabs = st.tabs(["Historical financials", "Ratio analysis", "Common size"])
    frames = [model.historical, model.ratios, model.common_size]
    names = ["historical", "ratios", "common_size"]
    for tab, frame, name in zip(tabs, frames, names):
        with tab:
            if frame.empty:
                st.info("This sheet was not found in the uploaded workbook.")
                continue
            styled = frame.style.format("{:,.2f}", na_rep="—")
            try:
                # A row-wise gradient makes trends readable at a glance.
                # It needs matplotlib, so fall back to a plain table without it.
                styled = styled.background_gradient(cmap="Greens", axis=1)
            except ImportError:
                pass
            st.dataframe(styled, use_container_width=True, height=520)
            st.download_button(
                "Download as CSV", frame.to_csv().encode(),
                file_name=f"{model.company}_{name}.csv", mime="text/csv",
                key=f"dl-{name}",
            )


def sector_lens_tab(model, result) -> None:
    st.markdown(
        '<div class="note-block watch"><div class="card-title">Why this matters</div>'
        '<p style="margin:.35rem 0 0;font-size:.89rem;line-height:1.55">'
        'The financials below never change — only the yardstick does. A debt/equity '
        'of 8x is routine for a bank and a solvency alarm for a software firm, so the '
        'same company can be strong under one lens and weak under another. This view '
        'runs every sector rule book over the loaded model at once.</p></div>',
        unsafe_allow_html=True,
    )
    frame = compare_sectors(model, list(SECTORS.values()))
    with card("Same numbers, every sector rule book"):
        chart(C.sector_lens_chart(frame), key="lens")

    st.write("")
    left, right = st.columns([1.1, 1])
    with left:
        with card("How the ratios move together"):
            chart(
                C.correlation_heatmap(model, [
                    "Sales Growth", "EBITDA Margin", "Net Profit Margin",
                    "Return on Equity (ROE) %", "Debt to Equity Ratio",
                    "Interest Coverage Ratio",
                ]),
                key="corr",
            )
    with right:
        with card(f"Applied benchmarks · {result.sector.name}"):
            bands = pd.DataFrame([
                {
                    "Metric": m.metric,
                    "Latest": m.display(m.latest),
                    "Weak at": m.display(m.weak_at),
                    "Strong at": m.display(m.strong_at),
                    "Score": round(m.score),
                }
                for m in result.metrics
            ])
            st.dataframe(bands, use_container_width=True, hide_index=True, height=430)


def qa_tab(result, config: LLMConfig) -> None:
    with card("Ask the analyst"):
        st.caption(
            "Free-text questions about the loaded company. The model only sees the "
            "scored ratios and the sector profile, so it cannot invent outside facts."
        )
        suggestions = [
            "Is the debt load sustainable given the cash flows?",
            "What single ratio would change the verdict fastest?",
            "How would this company look if it were an IT services firm instead?",
        ]
        picked = st.radio("Suggested questions", suggestions, horizontal=False, index=None,
                          label_visibility="collapsed")
        question = st.text_input(
            "Your question", value=picked or "",
            placeholder="e.g. why is the return profile weak despite profit growth?",
            label_visibility="collapsed",
        )
        if st.button("Ask", type="primary") and question.strip():
            with st.spinner("Analysing…"):
                st.markdown(
                    f'<div class="note-block"><p style="margin:0;font-size:.92rem;'
                    f'line-height:1.6">{answer_question(result, question.strip(), config)}</p></div>',
                    unsafe_allow_html=True,
                )


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load(file_bytes: bytes | None, path: str | None):
    return load_model(path) if path else load_model(pd.io.common.BytesIO(file_bytes))


def main() -> None:
    mode = "dark" if st.session_state.get("dark_mode", False) else "light"
    inject_css(mode)
    source, sector_key, source_label = sidebar()
    # Keys live in the deployment's secret store, never in the UI or the repo.
    config = analyst_config()

    if source is None:
        st.markdown(
            '<div class="masthead"><div><h1><span class="brand-dot"></span>FundaCheck</h1>'
            '<div class="sub">UPLOAD A 3-STATEMENT MODEL TO BEGIN</div></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="empty-hero"><div class="glyph">◈</div>'
            "<h3>Drop a 3-statement model into the sidebar</h3>"
            "<p>Any Screener.in-style workbook works — it needs a <b>HistoricalFS</b> "
            "sheet and, ideally, a <b>Ratio Analysis</b> sheet. Nothing is uploaded "
            "anywhere: the file is parsed in memory for this session only.</p>"
            '<div class="empty-steps"><div>1 · Upload the .xlsx</div>'
            "<div>2 · Pick the sector</div><div>3 · Read the verdict</div></div></div>",
            unsafe_allow_html=True,
        )
        return

    try:
        if isinstance(source, (bytes, bytearray)):
            model = _load(bytes(source), None)
        else:
            model = _load(None, str(source))
    except ParseError as exc:
        st.error(f"That workbook could not be read: {exc}")
        return
    except Exception as exc:                       # noqa: BLE001
        st.error(f"Unexpected problem reading the workbook: {exc}")
        return

    # Fill in any benchmark ratio the workbook did not supply, computed from
    # its own statements, so a formulas-only export still analyses.
    derived = fill_missing_ratios(model)
    if derived:
        LOGGER.info("derived %d ratios for %s", len(derived), model.company)

    # A new workbook gets its sector detected once; after that the dropdown is
    # the source of truth, so changing it by hand sticks.
    if st.session_state.get("detected_for") != model.company:
        detected, why = detect_sector(model.company, {
            "Debt to Equity Ratio": model.latest("Debt to Equity Ratio"),
            "Interest % Sales": model.latest("Interest % Sales"),
            "EBITDA Margin": model.latest("EBITDA Margin"),
            "Fixed Asset Turnover": model.latest("Fixed Asset Turnover"),
            "Net Profit Margin": model.latest("Net Profit Margin"),
        })
        st.session_state.detected_for = model.company
        st.session_state.sector_pref = detected
        LOGGER.info("sector detected for %s: %s (%s)", model.company, detected, why)
        st.rerun()

    sector = get_sector(sector_key)
    try:
        result = assess(model, sector)
    except ValueError as exc:
        st.error(str(exc))
        return

    page = st.session_state.get("page", "overview")
    masthead(model, sector.name)

    if page == "overview":
        kpi_row(model, result)

        with st.spinner("Writing the analyst note…"):
            note = analyse(result, config)

        verdict_panel(result, note)
        st.write("")
        analyst_note(result, note)

        if result.data_gaps:
            st.caption(
                "Metrics not found in this workbook (excluded from the score): "
                + ", ".join(result.data_gaps)
            )

    st.write("")
    if page == "overview":
        overview_tab(model, result)
    elif page == "ratios":
        ratios_tab(model, result)
    elif page == "lens":
        sector_lens_tab(model, result)
    elif page == "statements":
        statements_tab(model)
    else:
        qa_tab(result, config)


if __name__ == "__main__":
    main()

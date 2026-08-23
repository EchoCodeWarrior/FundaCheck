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


def chart(fig, key: str) -> None:
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={"displayModeBar": False})


# --------------------------------------------------------------------------
# sidebar: data in, sector, LLM
# --------------------------------------------------------------------------
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
            '<div class="tag">FUNDAMENTAL TERMINAL</div></div></div>',
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

        # Day/Night lives in the main-area top bar now (the design puts it there);
        # only the default is seeded here so the first paint is themed correctly.
        st.session_state.setdefault("dark_mode", False)

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

    C.set_theme("dark" if st.session_state.get("dark_mode") else "light")
    return source, sector_key, source_label


# --------------------------------------------------------------------------
# page sections
# --------------------------------------------------------------------------
def topbar() -> None:
    """
    The design's top bar: search field, day/night pill and the Ask Analyst AI
    button. Every control is real — search filters the statements tables, the
    pill flips the theme, the button jumps to the analyst page.
    """
    search_col, theme_col, ai_col = st.columns([3.2, 1.05, 1.75], gap="small")
    with search_col:
        st.text_input(
            "Search", key="search_q",
            placeholder="🔍  Search company or ticker",
            label_visibility="collapsed",
        )
    with theme_col:
        # The toggle owns dark_mode directly; the sidebar no longer repeats it.
        st.toggle("Night" if st.session_state.get("dark_mode", False) else "Day",
                  key="dark_mode")
    with ai_col:
        if st.button("✦  Ask Analyst AI", key="top-ai", use_container_width=True,
                     type="primary"):
            st.session_state.page = "qa"
            st.rerun()


def _export_report(model, result) -> bytes:
    """Plain-text report for the Export Report button."""
    lines = [
        f"FundaCheck report — {model.company.title()}",
        f"Sector lens : {result.sector.name}",
        f"Score       : {result.total_score:.0f}/100 ({result.verdict})",
        "",
        f"{'METRIC':<38}{'LATEST':>14}{'WEAK AT':>12}{'STRONG AT':>12}{'SCORE':>8}",
        "-" * 84,
    ]
    for m in result.metrics:
        lines.append(
            f"{m.metric:<38}{m.display(m.latest):>14}"
            f"{m.display(m.weak_at):>12}{m.display(m.strong_at):>12}"
            f"{round(m.score):>8}"
        )
    lines += ["", f"Periods covered: {model.years[0]}–{model.latest_year}"]
    return "\n".join(lines).encode()


def masthead(model, sector_name: str, result) -> None:
    """
    The page hero, as one rounded shell per the design: company name and
    sector line on the left, market data in its own white card, then the
    outlined Export Report action.
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

    with st.container():
        # The marker lets the stylesheet find this container and paint the
        # shell around all three columns (same trick the card() helper uses).
        st.markdown('<div class="hero-marker"></div>', unsafe_allow_html=True)
        name_col, stat_col, btn_col = st.columns(
            [2.1, 1.6, 1.05], gap="small", vertical_alignment="center")
        with name_col:
            st.markdown(
                f'<div class="hero-name">{model.company.title()}</div>'
                f'<div class="hero-sub">{sector_name.upper()} &nbsp;·&nbsp; '
                f'{model.years[0]}–{model.latest_year} &nbsp;·&nbsp; '
                f'{len(model.years)} PERIODS</div>',
                unsafe_allow_html=True,
            )
        if stats:
            with stat_col:
                st.markdown(f'<div class="hero-stat">{stats}</div>',
                            unsafe_allow_html=True)
        with btn_col:
            st.download_button(
                "Export Report", data=_export_report(model, result),
                file_name=f"{model.company}_fundacheck_report.txt",
                mime="text/plain", key="export-report", use_container_width=True,
            )


def kpi_row(model, result) -> None:
    """
    The design's four lead cards: the score, then the three ratios an analyst
    reaches for first — P/E against its own history, ROE year on year, and
    leverage against the sector comfort zone.
    """
    def series_of(metric: str):
        return pd.to_numeric(model.series(metric), errors="coerce").dropna()

    score_col, pe_col, roe_col, de_col = st.columns(4)

    with score_col:
        kpi_tile(
            "Funda Score", f"{result.total_score:.0f}<small>/100</small>",
            footer=f'<span class="band">{result.verdict}</span>sector adjusted',
            variant="kpi-score",
        )

    with pe_col:
        pe = series_of("PE Ratio")
        pe = pe[(pe > 0) & (pe < 1000)]
        if pe.empty:
            kpi_tile("P/E Ratio", "n/a", "not in this workbook")
        else:
            latest, median = float(pe.iloc[-1]), float(pe.median())
            cheaper = latest < median
            kpi_tile(
                "P/E Ratio", f"{latest:.1f}",
                footer=f'<span class="mini {"good" if cheaper else "warn"}">'
                       f'{"▼" if cheaper else "▲"}</span>'
                       f'10-yr median {median:.1f}',
            )

    with roe_col:
        roe = series_of("Return on Equity (ROE) %")
        if roe.empty:
            kpi_tile("Return on Equity", "n/a", "not in this workbook")
        else:
            latest = float(roe.iloc[-1])
            delta_text, direction = "", ""
            prev_label = ""
            if len(roe) > 1:
                previous = float(roe.iloc[-2])
                change = latest - previous
                improving = change >= 0
                direction = "up" if improving else "down"
                arrow = "▲" if improving else "▼"
                delta_text = f"{change:+.1f} {arrow}"
                prev_label = f"{roe.index[-2]} was {previous:.1f}%"
            kpi_tile(
                "Return on Equity", f"{latest:.1f}%", delta_text, direction,
                footer=prev_label,
            )

    with de_col:
        de = series_of("Debt to Equity Ratio")
        scored = result.metric("Debt to Equity Ratio")
        if de.empty:
            kpi_tile("Debt / Equity", "n/a", "not in this workbook")
        else:
            note = ("Comfortably within sector norms"
                    if scored is None or scored.score >= 66 else
                    "Within sector norms, cover is thin"
                    if scored.score >= 40 else
                    "Above the sector comfort zone")
            kpi_tile("Debt / Equity", f"{float(de.iloc[-1]):.2f}", footer=note)


def verdict_panel(result, note: dict) -> None:
    """The verdict card with the score drivers living inside it."""
    emoji = {"STRONG": "😃", "NEUTRAL": "😐"}.get(result.verdict, "😕")
    drivers = D.score_drivers(result)
    text_col, driver_col = st.columns([1.5, 1], gap="medium")
    with text_col:
        st.markdown(
            f"""
            <div class="verdict" style="--accent:{result.colour};--amber-rail:{result.colour}">
              <div class="verdict-chips">
                <span class="tag" style="color:{result.colour};
                      border:1px solid {result.colour}55; background:{result.colour}18;">
                  {result.verdict}
                </span>
                <span class="sector-mono">SECTOR AWARE · {result.sector.name.upper()}</span>
              </div>
              <h2 style="color:{result.colour}">{result.headline} {emoji}</h2>
              <p>{note.get('summary', '')}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with driver_col:
        st.markdown('<div class="drivers-card"><div class="card-title">Score drivers'
                    f'</div>{drivers}</div>', unsafe_allow_html=True)


def _split_note(text: str) -> tuple[str, str]:
    """Split 'Net profit growth 29.3% — well above…' into title + description."""
    for sep in (" — ", " – ", ": "):
        if sep in text:
            head, _, tail = text.partition(sep)
            return head.strip(), tail.strip()
    cut = text.find(". ")
    if 30 < cut < 110:
        return text[:cut].strip(), text[cut + 1:].strip()
    return text.strip(), ""


def strength_risk_panels(note: dict, result) -> None:
    """Tinted strengths / risks panels with count badges and a See all toggle."""
    show_all = st.session_state.get("show_all_notes", False)
    limit = None if show_all else 3

    strengths_all = list(note.get("strengths") or result.strengths)
    risks_all = list(note.get("risks") or result.concerns)
    strengths = strengths_all if limit is None else strengths_all[:limit]
    risks = risks_all if limit is None else risks_all[:limit]

    def panel(title: str, items: list[str], kind: str, colour: str):
        bullets = "".join(
            f"<li><b>{t}</b><span class='d'>{d}</span></li>"
            for t, d in (_split_note(str(i)) for i in items)
        )
        st.markdown(
            f'<div class="note-block {kind}"><div class="note-head">'
            f'<span class="nb-title">{title}</span>'
            f'<span class="count-badge" style="background:{colour}">'
            f'{len(items)}</span></div><ul>{bullets}</ul></div>',
            unsafe_allow_html=True,
        )

    left, right = st.columns(2, gap="small")
    with left:
        panel("Ratio Strengths", strengths, "strong", "#177245")
    with right:
        panel("Ratio Risks", risks, "risk", "#a4483f")

    if st.button("See all" if not show_all else "Show fewer",
                 key="toggle-notes", use_container_width=True):
        st.session_state.show_all_notes = not show_all
        st.rerun()


def peers_panel() -> None:
    """
    The design's Peer Comparison card. Peers are user-entered (the workbook
    carries no peer set), held in session state so they survive reruns.
    """
    peers = st.session_state.setdefault("peers", [])
    avatar_bg = ["#e8f1ec", "#f2f0e6", "#f0eaf2", "#f6ebe6"]

    rows = []
    for i, p in enumerate(peers):
        roe, de, pe = p.get("roe"), p.get("de"), p.get("pe")
        sub = f'ROE <span class="v">{roe:.1f}%</span>' if roe is not None else "ROE n/a"
        sub += f" · D/E {de:.2f}" if de is not None else ""
        if pe is not None and pe > 0:
            tone = "chip-bad" if pe >= 45 else "chip-warn" if pe >= 32 else "chip-good"
            chip = f'<span class="peer-chip {tone}">P/E {pe:.1f}</span>'
        else:
            chip = '<span class="peer-chip chip-bad">Loss</span>'
        rows.append(
            f'<div class="peer-row"><div class="peer-avatar" '
            f'style="background:{avatar_bg[i % len(avatar_bg)]}"></div>'
            f'<div class="peer-main"><div class="peer-name">{p["name"]}</div>'
            f'<div class="peer-sub">{sub}</div></div>{chip}</div>'
        )
    body = ('<div class="peer-list">' + "".join(rows) + "</div>") if rows else \
           '<p class="tile-sub">No peers yet — add companies to compare them side by side.</p>'

    with st.container():
        head_left, head_right = st.columns([2.4, 1], vertical_alignment="center")
        with head_left:
            st.markdown('<div class="card-title">Peer Comparison</div>',
                        unsafe_allow_html=True)
        with head_right:
            add = st.toggle("+ Add Peer", key="add-peer-on")

        if add:
            with st.form("add-peer"):
                name = st.text_input("Company")
                c1, c2, c3 = st.columns(3)
                pe = c1.number_input("P/E", min_value=0.0, step=0.1)
                roe = c2.number_input("ROE %", step=0.1)
                de = c3.number_input("Debt / Equity", step=0.05)
                if st.form_submit_button("Add to comparison") and name.strip():
                    peers.append({"name": name.strip(), "pe": pe or None,
                                  "roe": roe, "de": de})
                    st.session_state.add_peer_on = False
                    st.rerun()

        st.markdown(body, unsafe_allow_html=True)

        if peers:
            rm_col, btn_col = st.columns([2, 1], vertical_alignment="center")
            idx = rm_col.selectbox(
                "Remove a peer", options=list(range(len(peers))), index=None,
                format_func=lambda i: peers[i]["name"], placeholder="Remove a peer…",
                label_visibility="collapsed",
            )
            if btn_col.button("Remove selected", disabled=idx is None,
                              use_container_width=True):
                peers.pop(idx)
                st.rerun()


def design_panels(model, result) -> None:
    """Revenue Trend / Valuation / Key Ratios, then Peers / Health, then flow."""
    left, middle, right = st.columns([1.25, 1, 1])
    with left:
        with card("Revenue Trend"):
            st.markdown(D.revenue_trend(model), unsafe_allow_html=True)
    with middle:
        with card("Valuation"):
            st.markdown('<p class="tile-sub">Fundamental metrics to determine fair value'
                        '</p>', unsafe_allow_html=True)
            st.markdown(D.valuation_panel(model), unsafe_allow_html=True)
    with right:
        with card("Key Ratios"):
            st.markdown(D.key_ratios(model, result), unsafe_allow_html=True)

    st.write("")
    left, right = st.columns([1, 1])
    with left:
        peers_panel()
    with right:
        with card("Financial Health"):
            st.markdown(D.health_gauge(result), unsafe_allow_html=True)

    st.write("")
    sankey_title, sankey_svg = D.income_sankey(model)
    if sankey_svg:
        with card(sankey_title):
            st.markdown('<p class="tile-sub">Income statement flow, ₹ crore</p>',
                        unsafe_allow_html=True)
            st.markdown(sankey_svg, unsafe_allow_html=True)


def bento(title: str, subtitle: str, key: str, figure, span: str = "") -> None:
    """One bento tile: a titled card wrapping a single chart."""
    with card(title):
        if subtitle:
            st.markdown(f'<p class="tile-sub">{subtitle}</p>', unsafe_allow_html=True)
        chart(figure, key=key)


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
    # The top-bar search filters every statement table by row name.
    query = (st.session_state.get("search_q") or "").strip().lower()
    tabs = st.tabs(["Historical financials", "Ratio analysis", "Common size"])
    frames = [model.historical, model.ratios, model.common_size]
    names = ["historical", "ratios", "common_size"]
    for tab, frame, name in zip(tabs, frames, names):
        with tab:
            if frame.empty:
                st.info("This sheet was not found in the uploaded workbook.")
                continue
            if query:
                frame = frame[frame.index.astype(str).str.lower().str.contains(query)]
                if frame.empty:
                    st.info(f'No rows match "{query}".')
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
        topbar()
        st.markdown(
            '<div class="masthead"><h1>FundaCheck</h1>'
            '<div class="sub">UPLOAD A 3-STATEMENT MODEL TO BEGIN</div></div>',
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
    topbar()
    masthead(model, sector.name, result)

    if page == "overview":
        kpi_row(model, result)
        st.write("")

        with st.spinner("Writing the analyst note…"):
            note = analyse(result, config)

        verdict_panel(result, note)
        st.write("")
        strength_risk_panels(note, result)

        if note.get("_error"):
            st.warning(f"LLM call failed, showing the rule-based note instead. "
                       f"({note['_error']})")

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

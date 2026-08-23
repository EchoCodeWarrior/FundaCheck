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
import streamlit.components.v1 as components

from core import charts as C
from core import design_blocks as D
from core import report as REP
from core import sections as S
from core import viz
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
def inject_css(mode: str = "dark", minimized: bool = False) -> None:
    """
    Load the stylesheet, plus the light overrides when day mode is on, plus
    the narrow-sidebar rules when the Minimize toggle is engaged.
    """
    css = (APP_DIR / "assets" / "style.css").read_text()
    if mode == "light":
        css += "\n" + (APP_DIR / "assets" / "light.css").read_text()
    if minimized:
        css += "\n" + MIN_CSS
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


MIN_CSS = """
section[data-testid="stSidebar"]{min-width:92px!important;max-width:92px!important}
.side-brand .txtwrap{display:none}
.side-brand .side-mark{margin:0 auto}
.nav-head,.step,[class*="detected"]{display:none!important}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"],
section[data-testid="stSidebar"] .stSelectbox,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"],
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] .stToggle{display:none!important}
.loaded-chip{justify-content:center;padding:.55rem .3rem!important}
.loaded-chip .txt{display:none}
section[data-testid="stSidebar"] .stButton>button{
  padding-left:.15rem!important;padding-right:.15rem!important;
  font-size:16px!important;justify-content:center;text-align:center}
"""


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


def vcomp(html: str, height: int) -> None:
    """Render one design-exact HTML/SVG block (iframe => hover tooltips work)."""
    components.html(viz.doc(html), height=height, scrolling=False)


def chart_card(title: str, subtitle: str, html: str, height: int) -> None:
    with card(title):
        if subtitle:
            st.markdown(f'<p class="tile-sub">{subtitle}</p>', unsafe_allow_html=True)
        vcomp(html, height)


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
            '<div class="txtwrap"><div class="name">FundaCheck</div>'
            '<div class="tag">FUNDAMENTAL TERMINAL</div></div></div>',
            unsafe_allow_html=True,
        )

        # ---- minimize / expand (the design's sidebar toggle) ----
        collapsed = bool(st.session_state.get("nav_min", False))
        if st.button("\u00bb" if collapsed else "\u00ab  Minimize",
                     key="side-min", use_container_width=True):
            st.session_state.nav_min = not collapsed
            st.rerun()

        # ---- navigation ----
        current = st.session_state.setdefault("page", "overview")
        # The click is recorded here but acted on at the very end of the
        # sidebar. Rerunning from inside this loop would abort the script before
        # the widgets below (the uploader above all) are instantiated, and
        # Streamlit discards the state of any widget a run did not render — which
        # is how navigating between pages used to throw the uploaded file away.
        navigate_to = None
        for key, label in NAV_PAGES:
            shown = label[0] if collapsed else label
            active = key == current
            if st.button(shown, key=f"nav-{key}", use_container_width=True,
                         type="primary" if active else "secondary",
                         help=None if collapsed else label):
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
    """The Export Report button: one PDF snapshotting every section."""
    try:
        return REP.build_pdf(model, result)
    except Exception as exc:                        # noqa: BLE001 - never block UI
        LOGGER.exception("PDF export failed")
        st.warning(f"PDF export failed, falling back to a plain-text report. ({exc})")
        lines = [
            f"FundaCheck report - {model.company.title()}",
            f"Sector lens : {result.sector.name}",
            f"Score       : {result.total_score:.0f}/100 ({result.verdict})",
            "",
        ]
        for m in result.metrics:
            lines.append(f"{S.short_name(m.metric):<28}{m.display(m.latest):>14}"
                         f"  score {round(m.score)}")
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
                file_name=f"{model.company}_fundacheck_report.pdf",
                mime="application/pdf", key="export-report",
                use_container_width=True,
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


def _page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div style="display:flex;align-items:baseline;gap:14px;padding:2px 4px 0;'
        f'flex-wrap:wrap"><span style="font-size:26px;font-weight:800;'
        f'letter-spacing:-.7px;color:#15201a">{title}</span>'
        f'<span style="font-size:13.5px;color:#8b918e">{subtitle}</span></div>',
        unsafe_allow_html=True,
    )


def ratios_tab(model, result) -> None:
    """Ratio deep dive - an exact port of the reference page's section."""
    years = S.full_years(model)
    latest_year = years[-1] if years else model.latest_year

    _page_header("Ratio deep dive",
                 "All nine categories from the Ratio Analysis sheet.")

    # ---- stat cards + ROCE spark | dials + cost donut -----------------------
    def pct_val(*names):
        s = S.pct_series(S.ser(model, *names))
        return float(s.iloc[-1]) if not s.empty else None

    npg = pct_val("Net Profit Growth")
    rev_g = pct_val("Sales Growth")
    cogs_v = S.last_two(S.ser(model, "COGS"))
    rev_v = S.last_two(S.ser(model, "Sales"))
    np_v = S.last_two(S.ser(model, "Net Profit"))
    other_v = S.last_two(S.ser(model, "Other Income"))
    ebit_v = S.last_two(S.ser(model, "EBIT (OPM)", "EBIT (Operating Profit)", "EBITDA"))

    left_col, right_col = st.columns([1.15, 1.6])
    with left_col:
        if npg is not None and np_v[0]:
            arrow = "\u25b2" if npg >= 0 else "\u25bc"
            prev_lab = f"{years[-2]} cr" if len(years) > 1 else "prev yr"
            st.markdown(
                '<div style="display:grid;grid-template-columns:repeat(auto-fit,'
                'minmax(min(180px,100%),1fr));gap:14px">' +
                S.stat_card(arrow, "good" if npg >= 30 else "warn",
                            f"{npg:.1f}%", "Net profit growth",
                            S.cr(np_v[0]), f"{latest_year} cr",
                            S.cr(np_v[1]) if np_v[1] else "n/a", prev_lab) +
                "</div>", unsafe_allow_html=True)
        st.write("")
        if rev_g is not None:
            arrow = "\u25b2" if rev_g >= 0 else "\u25bc"
            tone = "good" if rev_g >= 10 else ("warn" if rev_g > 0 else "bad")
            st.markdown(
                '<div style="display:grid;grid-template-columns:repeat(auto-fit,'
                'minmax(min(180px,100%),1fr));gap:14px">' +
                S.stat_card(arrow, tone, f"{rev_g:.1f}%", "Revenue growth",
                            S.cr(rev_v[0]), f"{latest_year} cr",
                            S.cr(rev_v[1]) or "n/a", f"{years[-2]} cr") +
                "</div>", unsafe_allow_html=True)
        st.write("")
        st.markdown(f'<div style="width:min(350px,100%)">'
                    f'{S.roce_card(model, result)}</div>', unsafe_allow_html=True)

    with right_col:
        if other_v[0] is not None:
            note = (f"above EBIT of {S.cr(ebit_v[0])}"
                    if ebit_v[0] and other_v[0] > ebit_v[0]
                    else "within operating income")
            st.markdown(
                '<div style="display:grid;grid-template-columns:repeat(auto-fit,'
                'minmax(min(180px,100%),1fr));gap:14px">' +
                S.simple_card(f"Other income, {latest_year}",
                              S.cr(other_v[0]), note) + "</div>",
                unsafe_allow_html=True)
            st.write("")
        dials_html, dials_h = S.dials_row(model)
        with card("Overall profit margin"):
            st.markdown('<p class="tile-sub">Latest year, dial scaled 0-30%</p>',
                        unsafe_allow_html=True)
            vcomp(dials_html, dials_h + 40)
        with card("Where each \u20b9100 of sales goes"):
            st.markdown('<p class="tile-sub">Latest-year cost structure</p>',
                        unsafe_allow_html=True)
            cost_html, cost_h = S.cost_card(model)
            vcomp(cost_html, cost_h)

    # ---- scorecard strip ------------------------------------------------------
    st.write("")
    rows = [(S.short_name(m.metric), m.display(m.latest), float(m.score))
            for m in result.metrics]
    sc_html, sc_h = viz.scorecard_chart(rows)
    with card("Ratio scorecard - scored against sector bands"):
        vcomp(sc_html, max(200, sc_h))

    # ---- the eight-chart grid -------------------------------------------------
    charts = S.deepdive_charts(model)
    st.write("")
    pairs = [
        ("Margin ladder", "Gross \u2192 EBITDA \u2192 EBIT \u2192 Net", "margins"),
        ("Returns", "ROE \u00b7 ROCE \u00b7 ROA", "returns"),
        ("Leverage & solvency", "Debt/equity bars \u00b7 interest cover line", "leverage"),
        ("Working capital cycle", "Debtor + inventory \u2212 payable days", "wc"),
        ("Cash flow mix", "Operating \u00b7 investing \u00b7 financing, \u20b9 cr", "cash"),
        ("Turnover & efficiency", "Times per year, latest vs 10-yr mean", "turnover"),
        ("Total assets, by component", "Stacked, \u20b9 crore", "assets"),
        ("Total liabilities & equity, by component",
         "Stacked, \u20b9 crore", "liab"),
    ]
    for i in range(0, len(pairs), 2):
        cols = st.columns(2)
        for col, (title, sub, key) in zip(cols, pairs[i:i + 2]):
            if key in charts:
                html, height = charts[key]
                with col:
                    chart_card(title, sub, html, max(260, height))


def statements_tab(model) -> None:
    """Statements - pill tabs, % change under every value, design table."""
    query = (st.session_state.get("search_q") or "").strip().lower()
    tab_names = ["Income Statement", "Ratio Analysis", "Common Size"]
    tabs = st.tabs(tab_names)
    sources = {"Income Statement": "Income Statement",
               "Ratio Analysis": "Ratio Analysis",
               "Common Size": "Common Size"}
    show_pct = st.toggle("Show % change", key="stmt-pct", value=True)
    for label, tab in zip(tab_names, tabs):
        with tab:
            html = S.statements_html(model, sources[label], show_pct, query)
            st.markdown(html, unsafe_allow_html=True)
    st.markdown(
        '<div style="display:flex;align-items:center;gap:12px;padding-top:12px">'
        '<span style="margin-left:auto;font-size:12px;color:#9aa09d">'
        'Above figures are in \u20b9 crores</span></div>',
        unsafe_allow_html=True,
    )


def sector_lens_tab(model, result) -> None:
    """Sector lens - exact port of the reference section."""
    _page_header("Sector lens", "One set of numbers, nine rule books.")
    st.markdown(S.why_card(), unsafe_allow_html=True)
    st.write("")

    sectors, hot_name = S.sector_scores(model, result)
    bars_html, bars_h = viz.sector_bars(sectors, hot_name)
    with card("Same numbers, every sector rule book"):
        vcomp(bars_html, max(220, bars_h))
    st.write("")

    gauge_html, gauge_h = viz.gauge(float(result.total_score),
                                    f"{result.total_score:.0f}%", compact=False)
    legend = viz.gauge_legend(compact=True)
    left, right = st.columns([1.05, 1])
    with left:
        with card("Financial health"):
            st.markdown('<p class="tile-sub">Composite index under this lens</p>',
                        unsafe_allow_html=True)
            vcomp(gauge_html, gauge_h + 16)
    with right:
        st.markdown('<div class="card-title">&nbsp;</div>'
                    f'<div style="padding-top:26px">{legend}</div>',
                    unsafe_allow_html=True)
    st.write("")

    hm_html, hm_h = S.heatmap_block(model)
    left, right = st.columns([1, 1])
    with left:
        with card("How the ratios move together"):
            st.markdown('<p class="tile-sub">Pairwise correlation across history</p>',
                        unsafe_allow_html=True)
            vcomp(hm_html, max(300, hm_h))
    with right:
        with card("Applied benchmarks"):
            st.markdown(f'<p class="tile-sub">{result.sector.name}</p>',
                        unsafe_allow_html=True)
            st.markdown(S.bench_table(result), unsafe_allow_html=True)


def qa_tab(result, config: LLMConfig) -> None:
    _page_header("Ask the analyst",
                 "Answers grounded only in the loaded model.")
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
                answer = answer_question(result, question.strip(), config)
                vcomp(f'<div style="font-size:13.5px;line-height:1.65;'
                      f'color:#3f4744;padding:4px 2px">{answer}</div>', 180)


# SPLICE_END

# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load(file_bytes: bytes | None, path: str | None):
    return load_model(path) if path else load_model(pd.io.common.BytesIO(file_bytes))


def main() -> None:
    mode = "dark" if st.session_state.get("dark_mode", False) else "light"
    inject_css(mode, minimized=bool(st.session_state.get("nav_min", False)))
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

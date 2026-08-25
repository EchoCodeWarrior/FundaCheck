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
from core import shell as SH
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

NAV_PAGES = [
    ("overview", "Dashboard"),
    ("ratios", "Ratio deep dive"),
    ("lens", "Sector lens"),
    ("statements", "Statements"),
    ("qa", "Ask the analyst"),
]

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


def _get_note(model, result, sector_key: str, config: LLMConfig) -> dict:
    """
    The analyst note is written once per loaded workbook: it is cached in
    session state against a fingerprint of the model, so reruns and page
    switches never re-call the LLM. Upload a different file (or change the
    sector lens) and it writes a fresh one.
    """
    fingerprint = "|".join([
        model.company, sector_key, f"{result.total_score:.1f}",
        str(len(result.metrics)), str(model.years[0]), str(model.latest_year),
    ])
    if st.session_state.get("note_fp") == fingerprint \
            and isinstance(st.session_state.get("note"), dict):
        return st.session_state["note"]
    with st.spinner("Writing the analyst note…"):
        note = analyse(result, config)
    st.session_state["note"] = note
    st.session_state["note_fp"] = fingerprint
    return note


def _render_shell(html: str, height: int) -> None:
    """One design-exact page, top to bottom, in a single frame."""
    components.html(html, height=height, scrolling=False)


def _export_row(model, result) -> None:
    """Real Export Report button (the hero carries an in-page copy too)."""
    _, btn = st.columns([5.4, 1])
    with btn:
        st.download_button(
            "⤓  Export Report", data=_export_report(model, result),
            file_name=f"{model.company}_fundacheck_report.pdf",
            mime="application/pdf", key="export-report",
            use_container_width=True,
        )


def _page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div style="display:flex;align-items:baseline;gap:14px;'
        f'padding:2px 4px 0;flex-wrap:wrap">'
        f'<span style="font-size:26px;font-weight:800;'
        f'letter-spacing:-.7px;color:#15201a">{title}</span>'
        f'<span style="font-size:13.5px;color:#8b918e">{subtitle}</span>'
        '</div>',
        unsafe_allow_html=True,
    )

def ratios_tab(model, result) -> None:
    """Ratio deep dive - the reference section, one shell, hover everywhere."""
    html, height = SH.ratios_shell(model, result)
    _export_row(model, result)
    _render_shell(html, height)

def statements_tab(model) -> None:
    """Statements - pill tabs + % change table inside the design shell."""
    query = (st.session_state.get("search_q") or "").strip().lower()
    html, height = SH.statements_shell(model, query)
    _render_shell(html, height)

def sector_lens_tab(model, result) -> None:
    """Sector lens - the reference section, one shell."""
    html, height = SH.sector_shell(model, result)
    _render_shell(html, height)

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

    if page == "overview":
        note = _get_note(model, result, sector_key, config)
        peers = st.session_state.setdefault("peers", [])
        html, height = SH.dashboard_shell(model, result, note, peers)
        _export_row(model, result)
        _render_shell(html, height)
        if note.get("_error"):
            st.caption(f"AI analyst unreachable ({note['_error']}) - showing the "
                       "rule-based reading.")
        if result.data_gaps:
            st.caption(
                "Metrics not found in this workbook (excluded from the score): "
                + ", ".join(result.data_gaps)
            )
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

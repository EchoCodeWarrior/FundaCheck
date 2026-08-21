"""
FinTerminal — an AI-assisted fundamental analysis terminal.

Upload a 3-statement Excel model, pick the sector, and the terminal turns it
into an interactive dashboard plus a STRONG / NEUTRAL / WEAK verdict that is
judged against sector-specific benchmarks rather than one universal rule book.

Run it with:   streamlit run app.py
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import streamlit as st

from core import charts as C
from core import ratio_charts as R
from core.llm import PROVIDERS, LLMConfig, analyse, answer_question, config_from_env
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

APP_DIR = Path(__file__).parent
SAMPLE = APP_DIR / "sample_data" / "3S_model_sample.xlsx"

st.set_page_config(
    page_title="FinTerminal · Fundamental Analysis",
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
             spark: str = "", period: str = "", footer: str = "") -> None:
    delta_html = f'<div class="delta {direction}">{delta}</div>' if delta else ""
    # Sheets do not always run to the same last period (the ratio sheet may stop
    # at FY26 while the P&L carries a TTM column), so every tile states its own.
    period_html = f'<span class="period">{period}</span>' if period else ""
    # Word values ("Profitability") need a smaller size than figures, or they
    # break mid-word inside a narrow tile.
    size_class = " value-text" if not any(ch.isdigit() for ch in value) else ""
    st.markdown(
        f'<div class="kpi"><div class="label">{label}{period_html}</div>'
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


def step(number: int, label: str) -> None:
    st.markdown(
        f'<div class="step"><span class="n">{number}</span>{label}'
        f'<span class="rule"></span></div>',
        unsafe_allow_html=True,
    )


def sidebar() -> tuple[object, str, LLMConfig, str]:
    with st.sidebar:
        st.markdown(
            '<div class="side-brand"><div class="side-mark">F</div>'
            '<div><div class="name">FinTerminal</div>'
            '<div class="tag">FUNDAMENTAL ANALYSIS</div></div></div>',
            unsafe_allow_html=True,
        )

        # ---- navigation ----
        st.markdown('<div class="nav-head">MENU</div>', unsafe_allow_html=True)
        current = st.session_state.setdefault("page", "overview")
        for key, label in NAV_PAGES:
            active = key == current
            if st.button(label, key=f"nav-{key}", use_container_width=True,
                         type="primary" if active else "secondary"):
                st.session_state.page = key
                st.rerun()

        st.markdown('<div class="nav-head">GENERAL</div>', unsafe_allow_html=True)
        st.session_state.setdefault("dark_mode", True)
        dark = st.toggle(
            "Dark mode", key="dark_mode",
            help="Both themes use their own validated palette — the light one is "
                 "a separate set of colours, not the dark set inverted.",
        )

        step(1, "Your data")
        upload = st.file_uploader(
            "3-statement model (.xlsx)", type=["xlsx", "xlsm"],
            label_visibility="collapsed",
            help="Any Screener.in-style workbook with a HistoricalFS sheet.",
        )
        use_sample = st.toggle(
            "Load the demo model instead", value=upload is None,
            disabled=not SAMPLE.exists() or upload is not None,
            help="A real 3-statement model, so you can try the terminal before uploading.",
        )

        if upload is not None:
            source, source_label = upload, upload.name
            detail = f"{len(upload.getvalue()) / 1024:,.0f} KB · your upload"
        elif use_sample:
            source, source_label = SAMPLE, "3S_model_sample.xlsx"
            detail = "bundled demo · Adani Enterprises"
        else:
            source, source_label, detail = None, "", ""

        if source is not None:
            st.markdown(
                f'<div class="loaded-chip"><span class="dot"></span>'
                f'<span class="txt"><b>{source_label}</b><span>{detail}</span></span></div>',
                unsafe_allow_html=True,
            )

        step(2, "Sector lens")
        choices = sector_choices()
        keys = [k for k, _ in choices]
        # The sector is detected from the loaded workbook (see main()); the
        # selectbox owns it from then on, so the user can always override.
        # Held in a plain state key rather than the widget's own key: Streamlit
        # forbids writing to a widget key once the widget exists, and detection
        # (in main(), after the workbook loads) has to be able to set it.
        preferred = st.session_state.setdefault("sector_pref", "generic")
        sector_key = st.selectbox(
            "Sector", options=keys, format_func=lambda k: dict(choices)[k],
            index=keys.index(preferred) if preferred in keys else 0,
            label_visibility="collapsed",
            help="Benchmarks and pillar weights change with the sector you pick.",
        )
        st.session_state.sector_pref = sector_key
        why = st.session_state.get("sector_why", "")
        if why:
            st.markdown(
                f'<p class="detected">Auto-detected · {why}</p>', unsafe_allow_html=True
            )
        st.caption(get_sector(sector_key).notes)

        step(3, "AI analyst")
        provider = st.selectbox(
            "Provider", options=["groq", "openrouter", "offline"],
            format_func=lambda p: PROVIDERS[p]["label"] if p in PROVIDERS else "Offline (no key)",
            label_visibility="collapsed",
        )

        config = LLMConfig(provider="offline")
        if provider in PROVIDERS:
            spec = PROVIDERS[provider]
            key = st.text_input(
                "API key", value=os.getenv(spec["key_env"], ""), type="password",
                placeholder=f"{spec['key_env']} …", label_visibility="collapsed",
            )
            model_name = st.selectbox("Model", spec["models"], label_visibility="collapsed")
            config = LLMConfig(provider=provider, api_key=key.strip(), model=model_name)
            if not key:
                st.caption(f"Free key: {spec['signup']}")

        st.markdown(
            '<span class="pill live">● LLM connected</span>' if config.is_live
            else '<span class="pill offline">● Rule-based mode</span>',
            unsafe_allow_html=True,
        )
        st.caption(
            "The score is always computed by the deterministic engine. "
            "The LLM only writes the commentary, so numbers stay auditable."
        )

    C.set_theme("dark" if dark else "light")
    return source, sector_key, config, source_label


# --------------------------------------------------------------------------
# page sections
# --------------------------------------------------------------------------
def masthead(model, sector_name: str) -> None:
    price = model.meta.get("current_price")
    mcap = model.meta.get("market_cap")
    right = []
    if price:
        right.append(f"PRICE {price:,.1f}")
    if mcap:
        right.append(f"MCAP {mcap:,.0f} Cr")
    right.append(f"{len(model.years)} PERIODS")

    st.markdown(
        f"""
        <div class="masthead">
          <div>
            <h1><span class="brand-dot"></span>{model.company}</h1>
            <div class="sub">{sector_name.upper()} &nbsp;·&nbsp; {model.years[0]}–{model.latest_year}</div>
          </div>
          <div class="sub" style="text-align:right">{' &nbsp;·&nbsp; '.join(right)}</div>
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
    for chunk in (HEADLINE_RATIOS[:5], HEADLINE_RATIOS[5:]):
        columns = st.columns(len(chunk))
        for column, (metric, label, higher_better) in zip(columns, chunk):
            series = model.series(metric).dropna()
            with column:
                if series.empty:
                    kpi_tile(label, "n/a", "not in this workbook")
                    continue

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
                    tone = ("good" if scored.score >= 70
                            else "warn" if scored.score >= 45 else "bad")
                    band_html = (
                        f'<span class="band {tone}">{scored.verdict} for sector</span>'
                    )

                kpi_tile(
                    label, fmt(latest, metric), delta_text, direction,
                    spark=C.sparkline_svg(series.tail(9), higher_better),
                    period=str(series.index[-1]), footer=band_html,
                )
        st.write("")


def verdict_panel(result, note: dict) -> None:
    left, right = st.columns([1.35, 1])
    with left:
        st.markdown(
            f"""
            <div class="verdict" style="--accent:{result.colour}">
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
        with card("Composite score"):
            st.markdown(
                C.score_ring(result.total_score, result.verdict, result.colour),
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="card-title" style="margin-top:.9rem">Pillar scores</div>'
                + C.pillar_meters(result.pillar_scores),
                unsafe_allow_html=True,
            )


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


def overview_tab(model, result) -> None:
    """
    The ten headline ratios, one chart each, in a bento grid.

    Tile sizes are deliberately uneven: the ratios that carry the most weight in
    a fundamental call get the wider tiles, so the layout itself ranks them.
    """
    # Row 1 — the two return ratios, side by side and directly comparable
    left, right = st.columns([1, 1])
    with left:
        bento("Return on equity", "How hard shareholder money is working",
              "roe", R.return_trend(model, result, "Return on Equity (ROE) %"))
    with right:
        bento("Return on capital employed", "The same question, but debt counts too",
              "roce", R.return_trend(model, result, "Return on Capital Employed (ROCE) %"))

    # Row 2 — margins: the ladder, then the one number against its target
    left, right = st.columns([1.35, 1])
    with left:
        bento("Sales to profit", "Which rung of the ladder loses the most",
              "ladder", R.profit_ladder(model))
    with right:
        bento("EBITDA margin vs sector", "Bar is today, tick is the 3-year average",
              "bullet", R.margin_bullet(model, result))
        bento("Momentum", "Growth above the line, contraction below",
              "growth", R.growth_columns(model, "Sales Growth"))

    # Row 3 — risk: how it is funded, and whether it can service that funding
    left, right = st.columns([1, 1])
    with left:
        bento("Funding mix", "Share of capital that is borrowed, year by year",
              "mix", R.funding_mix(model))
    with right:
        bento("Interest cover", "Distance from the line where profit stops covering interest",
              "cover", R.interest_cover_zone(model, result))

    # Row 4 — cash: quality, then the working-capital cycle behind it
    left, right = st.columns([1, 1.15])
    with left:
        bento("Earnings quality", "The gap between reported profit and actual cash",
              "cashq", R.cash_quality_dumbbell(model))
    with right:
        bento("Cash conversion cycle", "Collected and held, minus what suppliers fund",
              "ccc", R.cash_cycle_bridge(model))

    # Row 5 — what the market already thinks
    bento("Valuation", "Today's P/E against the company's own history",
          "pe", R.valuation_strip(model))


def ratios_tab(model, result) -> None:
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
    mode = "dark" if st.session_state.get("dark_mode", True) else "light"
    inject_css(mode)
    source, sector_key, config, source_label = sidebar()

    if source is None:
        st.markdown(
            '<div class="masthead"><div><h1><span class="brand-dot"></span>FinTerminal</h1>'
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
        if hasattr(source, "read"):
            model = _load(source.getvalue(), None)
        else:
            model = _load(None, str(source))
    except ParseError as exc:
        st.error(f"That workbook could not be read: {exc}")
        return
    except Exception as exc:                       # noqa: BLE001
        st.error(f"Unexpected problem reading the workbook: {exc}")
        return

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
        st.session_state.sector_why = why
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

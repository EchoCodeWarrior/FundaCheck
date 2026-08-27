# FundaCheck

**An AI-assisted fundamental analysis terminal.** Upload a 3-statement Excel
model, pick the company's sector, and get an interactive dashboard plus a
**STRONG / NEUTRAL / WEAK** verdict — judged against *sector-specific*
benchmarks rather than one universal rule book.

![Python](https://img.shields.io/badge/Python-3.10%2B-1e6b45)
![Flask](https://img.shields.io/badge/Flask-API-147a4b)
![License](https://img.shields.io/badge/license-MIT-777)

---

## The problem it solves

Reading a 3-statement model means holding forty ratios in your head at once and
— the harder part — remembering that each one means something different
depending on the industry:

| Ratio | Software company | Bank | Infrastructure developer |
|---|---|---|---|
| Debt / equity of 8x | solvency alarm | completely normal | over-levered |
| ROCE of 12% | disappointing | not a meaningful metric | respectable |
| 130-day working capital cycle | broken collections | not applicable | business as usual |

A single scorecard applied to every company produces confident nonsense.
FundaCheck keeps one rule book per sector and applies the right one.

## What it does

1. **Parses** any Screener.in-style 3-statement workbook — income statement,
   balance sheet, cash flow, ratio analysis and common-size sheets.
2. **Scores** twelve key ratios against that sector's weak/strong bands, rolls
   them into five pillars (growth, profitability, returns, leverage,
   efficiency) and weights those pillars by what the sector actually rewards.
3. **Visualises** everything as a responsive light/dark dashboard that works on
   desktop, tablet, and mobile screens.
4. **Explains** the result through a configured LLM writing a sector-aware analyst
   note — and answers follow-up questions about the loaded company.

### The core idea, made visible

The **Sector lens** tab runs all nine sector rule books over the same company at
once. The financials never change; only the yardstick does — and the verdict
moves with it. That single chart is the whole thesis of the project.

## Screens

The sidebar is permanent — the upload, the sector lens, the AI settings and the
day/night switch stay on screen on every page, and the collapse control is
removed so the nav can't be dismissed.

| Page | What's in it |
|---|---|
| **Dashboard** | Headline ratios with their sector verdict, the composite score ring, the analyst note, and a clean responsive chart layout |
| **Ratio deep dive** | Every ratio scored 0-100 against its sector band, leverage & solvency, working-capital cycle, and any ratio plotted through time with the sector bands shaded |
| **Sector lens** | The same company scored under all nine sector rule books, plus a ratio correlation matrix |
| **Statements** | The parsed sheets as heat-shaded tables, exportable to CSV |
| **Ask the analyst** | Free-text Q&A grounded strictly in the loaded model |

## Getting started

```bash
git clone <your-repo-url>
cd Financial-dashboard

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python app.py
```

The app opens at `http://127.0.0.1:5000`. A real 3-statement model ships in
`sample_data/`, so it is usable the moment it starts — no upload needed.

The frontend is plain browser JavaScript and CSS served by Flask. There is no
Streamlit runtime. The backend keeps uploaded workbooks in memory for the
current process, and the browser receives an opaque dataset id for subsequent
sector changes, questions, and PDF export. XLSX, XLSM, and simple metric-by-year
CSV files are accepted.

### Connecting the AI analyst

The analyst chat uses xAI's Grok API when an xAI key is configured. The default
model is `grok-4.3`, sent through xAI's OpenAI-compatible chat endpoint. Create a
key in the [xAI console](https://console.x.ai), then either copy `.env.example`
to `.env` and fill in `XAI_API_KEY`, or set `XAI_API_KEY` (or the
comma-separated `XAI_API_KEYS`) before starting Flask. `.env` is ignored by git
and loaded automatically:

```bash
cp .env.example .env
# edit .env and add your key
python app.py
```

You can also set the variable for one shell session:

```bash
XAI_API_KEY=xai-your-key-here python app.py
```

In PowerShell, use `$env:XAI_API_KEY="xai-your-key-here"` and then run
`python app.py`.

For a deployment, keep the key in its secret store; it is read only by Flask
and is never sent to the browser. Set `LLM_PROVIDER=xai` (or `grok`) to force
Grok explicitly. Existing Groq and OpenRouter configurations remain supported;
when `LLM_PROVIDER` is unset, the server chooses xAI first when an xAI key is
present, then Groq or OpenRouter if those are configured.

Two or more keys are supported for each provider: when a provider rate-limits a
key, the app tries the next key instead of dropping to its offline answer.

With no keys configured the app still works end to end — chat falls back to a
deterministic, rule-based answer.

For a safe connection check, open `/api/health`; its `ai` block reports whether
the provider is configured and which model is selected, never the key itself.

## How the score is built

```
raw ratio ──► sector band ──► 0-100 sub-score ──► pillar ──► weighted total ──► verdict
              (weak/strong)    60% latest year        (5)      (sector weights)   STRONG / NEUTRAL / WEAK
                               40% 3-year average
                               ± trend adjustment
```

Design decisions worth defending in an interview:

- **60/40 latest vs 3-year average.** One good year can be luck; three years is
  character. Neither alone is enough.
- **Linear scaling between the bands**, not a pass/fail cutoff, so a company
  just short of "strong" is not lumped in with one in real trouble.
- **A trend adjustment (±6 points)** so a deteriorating 15% ROCE scores below an
  improving one.
- **An earnings-quality override.** If three-year average CFO/PAT is below 0.5 —
  profit that never becomes cash — the total is docked five points regardless of
  how good the margins look.
- **The LLM never touches a number.** It receives the finished scorecard and
  writes the explanation, so every figure on screen is traceable to the
  workbook. That ordering is deliberate and is the honest way to put an LLM in a
  finance tool.

Thresholds live in `core/sectors.py` and are ordinary Python dictionaries —
adding a sector or tuning a band is a few lines, no code changes elsewhere.

## Design notes

The chart layer follows a few rules that are worth knowing, because they are the
difference between "looks like a dashboard" and "can be trusted":

- **No dual-axis charts.** Revenue-vs-margin and leverage-vs-cover used to be
  single charts with a second y-scale. Two scales let you imply any relationship
  you like by choosing the ranges, so both are now stacked small multiples on a
  shared x-axis — same story, no manufactured crossover.
- **Colour is assigned by the job it does.** Identity gets the fixed categorical
  order (never cycled, never reassigned by rank); the common-size stack gets one
  hue dark-to-light because it is magnitude; growth and correlation grids get a
  diverging pair with a **gray** midpoint because they have polarity. Status
  colours (good/warning/critical) are reserved and never double as a series.
- **The palette was validated, not eyeballed.** The five categorical slots were
  checked against the dark surface for lightness band, chroma floor,
  colourblind separation and 3:1 contrast. All five pass on the adjacent
  pairlist that bars, stacks and lines use; forms that compare every pair at
  once are capped at three slots and always direct-labelled.
- **Identity never rests on colour alone** — every multi-series chart carries a
  legend, key points are direct-labelled, and the tables carry the same numbers.
- **One chart form per ratio, chosen by the data's job.** Returns get a banded
  area against the sector threshold; net margin gets a profit ladder; EBITDA
  margin gets a bullet against its target band; debt gets a funding-mix area;
  interest cover gets a shaded danger zone; growth gets diverging columns;
  cash quality gets a dumbbell, because the gap between profit and cash *is*
  the question; valuation gets a strip against the company's own median.
- **A workbook that only contains formulas still analyses.** Derived sheets
  often carry no cached values, so they read as empty. The statements are
  rebuilt from the raw Data Sheet and any missing benchmark ratio is computed
  from them — the workbook's own numbers always win where it supplies them.
- **The sector follows the company.** It is detected from the workbook — name
  first, balance-sheet shape as a fallback — and the sidebar says which signal
  decided it. The dropdown still overrides.
- **Small multiples wherever one scale would lie.** The cost structure used to
  be a 100% stacked bar, but COGS is 75-90% of sales, so everything else was an
  invisible sliver. Each line now gets its own panel and its own y-scale.
  Cash flow got the same treatment for the same reason.
- **Both themes are selected, not flipped.** The light palette's five series
  colours were validated against the light surface on their own; inverting the
  dark set would have failed the lightness band.
- **Motion respects `prefers-reduced-motion`.** The entrance animations, the
  score ring sweep and the meter fills all collapse to nothing for anyone who
  has asked their OS for less movement.

## Project layout

```
app.py               Flask API and static-file server
core/
  parser.py          Excel → clean DataFrames (layout-tolerant)
  sectors.py         Nine sector rule books: bands, weights, context notes
  scoring.py         Ratio → sub-score → pillar → verdict engine
  llm.py             LLM clients (xAI Grok / Groq / OpenRouter) + offline fallback
  charts.py          Legacy chart helpers retained for the report engine
assets/app.css       Responsive light/dark product UI
assets/app.js        Browser interactions, charts, upload flow, and navigation
sample_data/         A real 3-statement model to demo with
```

The parser makes no assumption about which rows exist. It finds the row labelled
`Year`, treats `#` in the left margin as a section break, and reads everything
else as a metric — which is why a workbook with extra or missing rows still
loads. Summary columns (`Mean`, `Median`, `CAGR`) are detected and excluded so
they never contaminate a time series.

## Limitations (stated honestly)

- Sector bands are calibrated from general Indian large-cap norms, not from a
  live peer database. They are a defensible starting point, not gospel.
- Banks and NBFCs are scored on a reduced metric set — turnover and
  working-capital ratios are meaningless for lenders, so they are down-weighted
  rather than reinterpreted.
- The verdict is a screening aid. It is not investment advice, and it cannot see
  management quality, governance, or anything outside the workbook.

## Roadmap

- [ ] Peer comparison — load several models and rank them side by side
- [ ] Auto-detect the sector from the revenue mix instead of asking
- [ ] Export the analyst note as a formatted PDF tearsheet
- [ ] Altman Z-score and Piotroski F-score alongside the composite
- [x] Responsive light and dark themes with mobile navigation
- [ ] Live peer comparison — add a market-data provider when external data is desired

---

MIT licensed. Built as a portfolio project — issues and forks welcome.

# FinTerminal

**An AI-assisted fundamental analysis terminal.** Upload a 3-statement Excel
model, pick the company's sector, and get an interactive dashboard plus a
**STRONG / NEUTRAL / WEAK** verdict — judged against *sector-specific*
benchmarks rather than one universal rule book.

![Python](https://img.shields.io/badge/Python-3.10%2B-1e6b45)
![Streamlit](https://img.shields.io/badge/Streamlit-app-37d67a)
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
FinTerminal keeps one rule book per sector and applies the right one.

## What it does

1. **Parses** any Screener.in-style 3-statement workbook — income statement,
   balance sheet, cash flow, ratio analysis and common-size sheets.
2. **Scores** twelve key ratios against that sector's weak/strong bands, rolls
   them into five pillars (growth, profitability, returns, leverage,
   efficiency) and weights those pillars by what the sector actually rewards.
3. **Visualises** everything as an interactive dark-terminal dashboard.
4. **Explains** the result through a free LLM writing a sector-aware analyst
   note — and answers follow-up questions about the loaded company.

### The core idea, made visible

The **Sector lens** tab runs all nine sector rule books over the same company at
once. The financials never change; only the yardstick does — and the verdict
moves with it. That single chart is the whole thesis of the project.

## Screens

| Tab | What's in it |
|---|---|
| **Overview** | Revenue / profit / margin small multiples, five-pillar radar, common-size revenue stack, cash flow by activity, and a growth history grid |
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
streamlit run app.py
```

The app opens at `http://localhost:8501`. A real 3-statement model ships in
`sample_data/`, so it is usable the moment it starts — no upload needed.

### Connecting a free LLM (optional)

The terminal runs fine with no API key: commentary falls back to a
deterministic, rule-based note. To switch on the AI analyst, get one free key —

| Provider | Free tier | Key |
|---|---|---|
| **Groq** | generous, very fast | <https://console.groq.com/keys> |
| **OpenRouter** | `:free` models | <https://openrouter.ai/keys> |

— and either paste it into the sidebar, or export it:

```bash
export GROQ_API_KEY="gsk_..."        # or OPENROUTER_API_KEY
streamlit run app.py
```

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
- **Motion respects `prefers-reduced-motion`.** The entrance animations, the
  score ring sweep and the meter fills all collapse to nothing for anyone who
  has asked their OS for less movement.

## Project layout

```
app.py               Streamlit UI — layout, tabs, and nothing else
core/
  parser.py          Excel → clean DataFrames (layout-tolerant)
  sectors.py         Nine sector rule books: bands, weights, context notes
  scoring.py         Ratio → sub-score → pillar → verdict engine
  llm.py             Free LLM clients (Groq / OpenRouter) + offline fallback
  charts.py          Every Plotly figure, one house style
assets/style.css     Terminal theme
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
- [ ] A light theme (the dark palette would need re-validating against a light surface, not just flipped)

---

MIT licensed. Built as a portfolio project — issues and forks welcome.

"""
parser.py
---------
Reads a "3-statement model" Excel workbook (the layout produced by Screener.in
style templates) and turns it into clean pandas DataFrames.

The workbook layout we expect on every sheet:

      col A   col B                      col C, D, E ...
      -----   ------------------------   -------------------------
              Historical Financial Data - COMPANY NAME     <- title row
              Year                       2017-03-31  2018-03-31 ...
      #       Income Statement                              <- section header
              Sales                      36532.86    35923.92 ...
              COGS                       33410.81    32775.11 ...

So: a row is a *section header* when column A holds "#", and a *metric* row
when column B holds a label and column A is empty. That single rule is enough
to parse every sheet in the workbook, which is why the parser is short.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# Sheet names we look for, and the friendly key we store them under.
# Matching is fuzzy (lower-cased, spaces stripped) so small naming differences
# between workbooks do not break the import.
SHEET_ALIASES: dict[str, tuple[str, ...]] = {
    "historical": ("historicalfs", "historical", "financials", "3smodel", "model"),
    "ratios": ("ratioanalysis", "ratios", "ratio"),
    "common_size": ("commonsizestatement", "commonsize"),
    "data": ("datasheet", "data", "raw"),
}


class ParseError(Exception):
    """Raised when a workbook does not look like a 3-statement model."""


@dataclass
class FinancialModel:
    """Everything we managed to extract from one uploaded workbook."""

    company: str = "Unknown Company"
    years: list[str] = field(default_factory=list)
    historical: pd.DataFrame = field(default_factory=pd.DataFrame)
    ratios: pd.DataFrame = field(default_factory=pd.DataFrame)
    common_size: pd.DataFrame = field(default_factory=pd.DataFrame)
    meta: dict[str, Any] = field(default_factory=dict)
    # True when the statements had to be rebuilt from the raw Data Sheet
    rebuilt_from_data_sheet: bool = False
    # metric label -> the section it was found under ("PROFITABILITY & MARGINS")
    sections: dict[str, str] = field(default_factory=dict)

    @property
    def latest_year(self) -> str:
        return self.years[-1] if self.years else ""

    def series(self, metric: str) -> pd.Series:
        """Return one metric across all years, from whichever sheet has it."""
        for frame in (self.ratios, self.historical, self.common_size):
            if not frame.empty and metric in frame.index:
                return frame.loc[metric].dropna()
        return pd.Series(dtype="float64")

    def latest(self, metric: str, default: float | None = None) -> float | None:
        """Most recent non-empty value of a metric."""
        s = self.series(metric)
        return float(s.iloc[-1]) if not s.empty else default

    def metrics_in_section(self, section: str) -> list[str]:
        return [m for m, sec in self.sections.items() if sec == section]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _norm(text: Any) -> str:
    """Lower-case, strip everything that is not a letter or digit."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _clean_label(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


# Summary columns some templates append to the right of the year columns.
# They are not periods, so they must never enter a time series.
AGGREGATE_COLUMNS = {
    "mean", "median", "average", "avg", "cagr", "min", "max", "sum",
    "total", "stdev", "std", "change", "growth",
}


def _is_period(label: str) -> bool:
    """True for a real reporting period (FY24, TTM), False for Mean/Median/CAGR."""
    if not label:
        return False
    return _norm(label) not in AGGREGATE_COLUMNS


def _year_label(value: Any) -> str:
    """Turn a date cell (or anything else) into a short year label like FY25."""
    if isinstance(value, pd.Timestamp) or hasattr(value, "year"):
        year = value.year
        # Indian financial years end in March, so a 2025-03-31 column is FY25.
        return f"FY{str(year)[-2:]}"
    text = str(value).strip()
    match = re.search(r"(19|20)\d{2}", text)
    if match:
        return f"FY{match.group(0)[-2:]}"
    return text


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if text in ("", "-", "NA", "nan", "#DIV/0!", "#VALUE!", "#REF!"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _find_sheet(book: dict[str, pd.DataFrame], key: str) -> pd.DataFrame | None:
    wanted = SHEET_ALIASES[key]
    for name, frame in book.items():
        normalised = _norm(name)
        if any(normalised.startswith(alias) or alias in normalised for alias in wanted):
            return frame
    return None


# --------------------------------------------------------------------------
# the actual sheet parser
# --------------------------------------------------------------------------
def _parse_statement_sheet(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str], str]:
    """
    Convert one raw sheet into (values DataFrame, metric->section map, title).

    The returned DataFrame is indexed by metric label with one column per year.
    """
    title = ""
    header_row = None
    year_labels: list[str] = []
    first_value_col = None

    for row_idx in range(min(len(raw), 15)):
        row = raw.iloc[row_idx]
        for col_idx, cell in enumerate(row):
            if cell is None or (isinstance(cell, float) and pd.isna(cell)):
                continue
            text = str(cell).strip()
            if not title and len(text) > 12 and "-" in text:
                title = text
            if _norm(text) == "year":
                header_row = row_idx
                first_value_col = col_idx + 1
                for value in row.iloc[first_value_col:]:
                    if value is None or (isinstance(value, float) and pd.isna(value)):
                        year_labels.append("")
                    else:
                        year_labels.append(_year_label(value))
                break
        if header_row is not None:
            break

    if header_row is None:
        raise ParseError("Could not find a row labelled 'Year' on this sheet.")

    # Drop trailing empty year columns.
    while year_labels and year_labels[-1] == "":
        year_labels.pop()
    n_years = len(year_labels)
    label_col = first_value_col - 1

    records: dict[str, list[float | None]] = {}
    sections: dict[str, str] = {}
    current_section = "GENERAL"

    for row_idx in range(header_row + 1, len(raw)):
        row = raw.iloc[row_idx]
        marker = row.iloc[label_col - 1] if label_col >= 1 else None
        label_cell = row.iloc[label_col]

        if label_cell is None or (isinstance(label_cell, float) and pd.isna(label_cell)):
            continue
        label = _clean_label(label_cell)
        if not label:
            continue

        # A "#" in the column left of the labels marks a section heading.
        if marker is not None and str(marker).strip() == "#":
            current_section = label.upper()
            continue

        values = [_to_float(v) for v in row.iloc[first_value_col:first_value_col + n_years]]
        if all(v is None for v in values):
            continue

        # Duplicate labels (e.g. "Total") get a suffix so nothing is lost.
        unique_label = label
        suffix = 2
        while unique_label in records:
            unique_label = f"{label} ({suffix})"
            suffix += 1

        records[unique_label] = values
        sections[unique_label] = current_section

    frame = pd.DataFrame.from_dict(records, orient="index", columns=year_labels)
    frame = frame.loc[:, [c for c in frame.columns if _is_period(c)]]
    # Templates often end with a decorative sparkline column ("TREND") that
    # holds no values. Drop anything completely empty.
    frame = frame.dropna(axis=1, how="all")
    return frame, sections, title


def _parse_data_sheet(raw: pd.DataFrame) -> dict[str, Any]:
    """Pull the small 'META' block (share count, price, market cap) if present."""
    meta: dict[str, Any] = {}
    wanted = {
        "numberofshares": "shares_outstanding",
        "facevalue": "face_value",
        "currentprice": "current_price",
        "marketcapitalization": "market_cap",
        "companyname": "company",
    }
    for _, row in raw.iterrows():
        cells = [c for c in row.tolist() if c is not None and not (isinstance(c, float) and pd.isna(c))]
        if len(cells) < 2:
            continue
        key = _norm(cells[0])
        if key in wanted:
            target = wanted[key]
            meta[target] = str(cells[1]).strip() if target == "company" else _to_float(cells[1])
    return meta


def _company_from_title(title: str) -> str:
    """'Historical Financial Data - ADANI ENTERPRISES LTD' -> 'Adani Enterprises Ltd'."""
    if "-" in title:
        title = title.split("-", 1)[1]
    return _clean_label(title).title() or "Unknown Company"



# --------------------------------------------------------------------------
# rebuilding statements from the raw Data Sheet
# --------------------------------------------------------------------------
# The derived sheets (HistoricalFS, Ratio Analysis) are grids of formulas. Some
# exports carry no cached results, so those sheets read as empty even though the
# Data Sheet next to them holds every raw number. This rebuilds the statements
# from those raw values so such a workbook still analyses.
DATA_SHEET_ALIASES: dict[str, str] = {
    "sales": "Sales",
    "netprofit": "Net Profit",
    "profitbeforetax": "Earnings Before Tax",
    "tax": "Tax",
    "interest": "Interest",
    "depreciation": "Depreciation",
    "otherincome": "Other Income ",
    "equitysharecapital": "Equity Share Capital",
    "reserves": "Reserves",
    "borrowings": "Borrowings",
    "otherliabilities": "Other Liabilities",
    "netblock": "Net Block",
    "capitalworkinprogress": "Capital Work in Progress",
    "investments": "Investments",
    "receivables": "Receivables",
    "inventory": "Inventory",
    "cashbank": "Cash & Bank",
    "cashfromoperatingactivity": "Cash from Operating Activity",
    "cashfrominvestingactivity": "Cash from Investing Activity",
    "cashfromfinancingactivity": "Cash from Financing Activity",
    "netcashflow": "Net Cash Flow",
    "noofequityshares": "No of Equity Shares",
}

# Everything that sits above EBITDA in an Indian P&L.
OPERATING_COST_KEYS = (
    "rawmaterialcost", "changeininventory", "powerandfuel", "othermfrexp",
    "employeecost", "sellingandadmin", "otherexpenses", "expenses",
)


def _parse_data_sheet_statements(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Read the Data Sheet's raw blocks into one metric-by-year frame.

    Each block ("PROFIT & LOSS", "BALANCE SHEET", "CASH FLOW:") restates its own
    "Report Date" header, so the year columns are picked up per block. The
    quarterly block is skipped: its dates are quarters, not financial years.
    """
    records: dict[str, dict[str, float]] = {}
    costs: dict[str, dict[str, float]] = {}
    years: list[str] = []
    in_quarters = False

    for _, row in raw.iterrows():
        cells = row.tolist()
        label_cell = next(
            (c for c in cells if c is not None and not (isinstance(c, float) and pd.isna(c))),
            None,
        )
        if label_cell is None:
            continue
        label = _clean_label(label_cell)
        key = _norm(label)
        start = cells.index(label_cell) + 1

        if key in ("quarters",):
            in_quarters = True
            continue
        if key in ("balancesheet", "cashflow", "profitloss", "price", "derived", "meta"):
            in_quarters = False
            continue
        if key == "reportdate":
            if not in_quarters:
                years = [
                    _year_label(v) for v in cells[start:]
                    if v is not None and not (isinstance(v, float) and pd.isna(v))
                ]
            continue
        if in_quarters or not years:
            continue

        values = [_to_float(v) for v in cells[start:start + len(years)]]
        if all(v is None for v in values):
            continue
        row_map = {y: v for y, v in zip(years, values) if v is not None}

        if key in OPERATING_COST_KEYS:
            costs[label] = row_map
        elif key in DATA_SHEET_ALIASES:
            records.setdefault(DATA_SHEET_ALIASES[key], {}).update(row_map)

    if not records:
        return pd.DataFrame()

    frame = pd.DataFrame.from_dict(records, orient="index")
    frame = frame.loc[:, [c for c in frame.columns if _is_period(c)]]
    frame = frame.reindex(sorted(frame.columns, key=lambda c: (len(c), c)), axis=1)

    # EBITDA is not reported directly: it is sales less the operating cost lines.
    if costs and "Sales" in frame.index:
        cost_frame = pd.DataFrame.from_dict(costs, orient="index").reindex(
            columns=frame.columns
        )
        total_cost = cost_frame.sum(axis=0, min_count=1)
        frame.loc["COGS"] = total_cost
        frame.loc["EBITDA"] = frame.loc["Sales"] - total_cost
        if "Depreciation" in frame.index:
            frame.loc["EBIT (OPM)"] = frame.loc["EBITDA"] - frame.loc["Depreciation"]

    if "Equity Share Capital" in frame.index and "Reserves" in frame.index:
        frame.loc["Total Asset"] = frame.loc[
            ["Equity Share Capital", "Reserves", "Borrowings", "Other Liabilities"]
        ].reindex(["Equity Share Capital", "Reserves", "Borrowings",
                   "Other Liabilities"]).sum(axis=0, min_count=1)

    if "Net Profit" in frame.index and "No of Equity Shares" in frame.index:
        shares = frame.loc["No of Equity Shares"].replace(0, pd.NA)
        # Screener stores the absolute share count; the statements use crore.
        if shares.dropna().max() and float(shares.dropna().max()) > 1e6:
            shares = shares / 1e7
        frame.loc["No of Equity Shares"] = shares
        frame.loc["Earnings per Share"] = frame.loc["Net Profit"] / shares

    return frame.dropna(axis=1, how="all")


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------
def load_model(source: Any) -> FinancialModel:
    """
    Parse an uploaded 3-statement workbook.

    `source` can be a file path or any file-like object (which is what the web
    API passes after receiving an upload).
    """
    book = pd.read_excel(source, sheet_name=None, header=None, engine="openpyxl")
    if not book:
        raise ParseError("The workbook appears to be empty.")

    model = FinancialModel()
    title = ""

    hist_sheet = _find_sheet(book, "historical")
    if hist_sheet is None:
        raise ParseError(
            "No historical financials sheet found. Expected a sheet named "
            "something like 'HistoricalFS'."
        )
    model.historical, sections, title = _parse_statement_sheet(hist_sheet)
    model.sections.update(sections)
    model.years = list(model.historical.columns)

    ratio_sheet = _find_sheet(book, "ratios")
    if ratio_sheet is not None:
        try:
            model.ratios, ratio_sections, ratio_title = _parse_statement_sheet(ratio_sheet)
            model.sections.update(ratio_sections)
            title = title or ratio_title
        except ParseError:
            pass

    cs_sheet = _find_sheet(book, "common_size")
    if cs_sheet is not None:
        try:
            model.common_size, cs_sections, _ = _parse_statement_sheet(cs_sheet)
            for label, section in cs_sections.items():
                model.sections.setdefault(label, section)
        except ParseError:
            pass

    data_sheet = _find_sheet(book, "data")
    if data_sheet is not None:
        model.meta = _parse_data_sheet(data_sheet)

        # A workbook whose formula sheets carry no cached values parses to
        # almost nothing. The Data Sheet holds the raw numbers, so rebuild from
        # it rather than failing the upload.
        if len(model.historical) < 8:
            rebuilt = _parse_data_sheet_statements(data_sheet)
            if not rebuilt.empty:
                model.historical = rebuilt
                model.years = list(rebuilt.columns)
                model.rebuilt_from_data_sheet = True
                for label in rebuilt.index:
                    model.sections.setdefault(label, "REBUILT FROM DATA SHEET")

    model.company = model.meta.get("company") or _company_from_title(title)
    return model

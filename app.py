"""FundaCheck web application.

The original project used Streamlit for its presentation layer. This module is
now a small Flask API and static-file server so the same parser/scoring engine
can power a responsive frontend without coupling the product to Streamlit.
"""

from __future__ import annotations

import os
import re
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file, send_from_directory

from core import sections as S
from core.derive import fill_missing_ratios
from core.llm import LLMRequestError, answer_question, config_from_env, offline_note
from core.parser import FinancialModel, ParseError, load_model
from core.report import build_pdf
from core.scoring import Assessment, assess
from core.sectors import detect_sector, get_sector, sector_choices


APP_DIR = Path(__file__).resolve().parent
SAMPLE = APP_DIR / "sample_data" / "3S_model_sample.xlsx"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Local development convenience: .env is ignored by git and never sent to the
# browser. Existing process/deployment variables win because load_dotenv does
# not override variables that are already set.
load_dotenv(APP_DIR / ".env")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

# A dataset is intentionally session-scoped in memory for this lightweight
# portfolio app. The browser holds the opaque id; uploaded workbooks never get
# written to disk. A production deployment can swap this dict for Redis or a
# database without changing the frontend contract.
DATASETS: dict[str, dict[str, Any]] = {}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(value) else value


def _clean_name(value: str) -> str:
    return re.sub(r"\s+", " ", Path(value).stem.replace("_", " ")).strip().title()


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _csv_model(raw: bytes, filename: str) -> FinancialModel:
    """Read a simple metric-by-year CSV as a FinancialModel.

    Excel remains the full-fidelity format. CSV support is deliberately
    forgiving for users who export a single statement: either the first column
    contains metric names, or the first column is Year and the remaining
    columns contain metrics.
    """
    try:
        frame = pd.read_csv(BytesIO(raw))
    except Exception as exc:  # noqa: BLE001 - converted to a user-facing error
        raise ParseError(f"Could not read this CSV file: {exc}") from exc
    if frame.empty or len(frame.columns) < 2:
        raise ParseError("The CSV needs a metric column and at least one year column.")

    first = str(frame.columns[0])
    if _norm(first) == "year":
        years = [str(value).strip() for value in frame.iloc[:, 0].tolist()]
        metrics = frame.iloc[:, 1:].copy()
        metrics.index = years
        historical = metrics.T
    else:
        metric_col = frame.columns[0]
        year_labels = [str(column).strip() for column in frame.columns[1:]]
        historical = frame.set_index(metric_col).iloc[:, :len(year_labels)].copy()
        historical.columns = year_labels

    historical = historical.apply(
        lambda column: pd.to_numeric(
            column.astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("%", "", regex=False),
            errors="coerce",
        )
    )
    historical = historical.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if historical.empty:
        raise ParseError("No numeric financial rows were found in this CSV.")

    return FinancialModel(
        company=_clean_name(filename),
        years=[str(column) for column in historical.columns],
        historical=historical,
        sections={str(label): "CSV IMPORT" for label in historical.index},
    )


def _load_source(raw: bytes, filename: str) -> FinancialModel:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return _csv_model(raw, filename)
    if suffix not in {".xlsx", ".xlsm"}:
        raise ParseError("Please upload an .xlsx, .xlsm, or .csv file.")
    try:
        return load_model(BytesIO(raw))
    except ParseError:
        raise
    except Exception as exc:  # noqa: BLE001 - keep the API error readable
        raise ParseError(f"Could not read this workbook: {exc}") from exc


def _detect(model: FinancialModel) -> tuple[str, str]:
    return detect_sector(
        model.company,
        {
            "Debt to Equity Ratio": model.latest("Debt to Equity Ratio"),
            "Interest % Sales": model.latest("Interest % Sales"),
            "EBITDA Margin": model.latest("EBITDA Margin"),
            "Fixed Asset Turnover": model.latest("Fixed Asset Turnover"),
            "Net Profit Margin": model.latest("Net Profit Margin"),
        },
    )


def _metric(result: Assessment, *names: str):
    for name in names:
        found = result.metric(name)
        if found is not None:
            return found
    return None


def _series(model: FinancialModel, *names: str) -> list[float | None]:
    for name in names:
        series = pd.to_numeric(model.series(name), errors="coerce")
        if not series.empty:
            return [
                _number(series.get(year)) if year in series.index else None
                for year in model.years
            ]
    return [None for _ in model.years]


def _metric_json(metric) -> dict[str, Any]:
    if metric is None:
        return {}
    return {
        "metric": metric.metric,
        "pillar": metric.pillar,
        "latest": _number(metric.latest),
        "average3y": _number(metric.average_3y),
        "weakAt": _number(metric.weak_at),
        "strongAt": _number(metric.strong_at),
        "score": round(float(metric.score), 1),
        "trend": round(float(metric.trend), 4),
        "verdict": metric.verdict,
        "lowerIsBetter": bool(metric.lower_is_better),
        "displayLatest": metric.display(metric.latest),
        "displayStrongAt": metric.display(metric.strong_at),
        "displayWeakAt": metric.display(metric.weak_at),
    }


def _value_json(model: FinancialModel, *names: str) -> dict[str, Any]:
    for name in names:
        series = pd.to_numeric(model.series(name), errors="coerce")
        if not series.empty:
            return {
                "value": _number(series.iloc[-1]),
                "series": _series(model, name),
                "source": name,
            }
    return {"value": None, "series": [None for _ in model.years], "source": None}


def _statement_rows(model: FinancialModel, tab: str) -> list[dict[str, Any]]:
    if tab in {"Income Statement", "Ratio Analysis", "Common Size"}:
        rows = S.stmt_source(model, tab)
    else:
        keywords = (
            ("asset", "liabil", "borrow", "equity", "reserve", "capital",
             "receiv", "inventory", "cash", "net block", "investment", "payable")
            if tab == "Balance Sheet"
            else ("cash", "operating", "investing", "financing", "dividend", "flow")
        )
        rows = []
        for label in model.historical.index:
            name = str(label)
            lowered = name.lower()
            if not any(keyword in lowered for keyword in keywords):
                continue
            series = pd.to_numeric(model.historical.loc[label], errors="coerce")
            values = [
                _number(series.get(year)) if year in series.index else None
                for year in model.years
            ]
            if any(value is not None for value in values):
                rows.append((name, values, name.lower().startswith("total")))
    return [
        {
            "name": name,
            "values": [_number(value) for value in values],
            "headline": bool(headline),
        }
        for name, values, headline in rows
    ]


def _metric_json_for_sector(metric, latest: float | None, benchmark: float | None) -> dict[str, Any]:
    return {
        "company": _number(latest),
        "benchmark": _number(benchmark),
        "companyDisplay": metric.display(latest) if latest is not None else "—",
        "benchmarkDisplay": metric.display(benchmark) if benchmark is not None else "—",
    }


def _sector_rows(result: Assessment) -> list[dict[str, Any]]:
    specs = [
        ("ROCE", "Return on Capital Employed (ROCE) %"),
        ("Operating margin", "EBITDA Margin"),
        ("Revenue growth", "Sales Growth"),
        ("Debt / Equity", "Debt to Equity Ratio"),
        ("Interest coverage", "Interest Coverage Ratio"),
        ("Cash conversion cycle", "Cash Conversion Cycle"),
    ]
    rows = []
    for label, metric_name in specs:
        metric = _metric(result, metric_name)
        if metric is None:
            continue
        latest = metric.latest
        strong = metric.strong_at
        weak = metric.weak_at
        if latest is None or strong is None:
            continue
        if metric.lower_is_better:
            company_score = max(0.08, min(1.0, strong / max(abs(latest), 1e-6)))
            benchmark_score = max(0.08, min(1.0, strong / max(abs(weak), 1e-6)))
        else:
            company_score = max(0.08, min(1.0, latest / max(abs(strong), 1e-6)))
            benchmark_score = 1.0
        rows.append(
            {
                "label": label,
                "metric": metric_name,
                "company": _number(latest),
                "benchmark": _number(strong),
                "weak": _number(weak),
                "companyDisplay": metric.display(latest),
                "benchmarkDisplay": metric.display(strong),
                "companyScore": round(company_score, 3),
                "benchmarkScore": round(benchmark_score, 3),
                "lowerIsBetter": bool(metric.lower_is_better),
            }
        )
    return rows


def _peer_rows(model: FinancialModel, result: Assessment) -> list[dict[str, Any]]:
    """Return honest comparison rows without pretending we fetched peer data."""
    metrics = {
        "ROCE": _metric(result, "Return on Capital Employed (ROCE) %"),
        "Revenue growth": _metric(result, "Sales Growth"),
        "Debt / Equity": _metric(result, "Debt to Equity Ratio"),
    }
    company = {
        "name": model.company,
        "kind": "company",
        "score": round(result.total_score),
        "values": {
            label: metric.display(metric.latest) if metric else "—"
            for label, metric in metrics.items()
        },
    }
    benchmark = {
        "name": f"{result.sector.name} benchmark",
        "kind": "benchmark",
        "score": 66,
        "values": {
            label: metric.display(metric.strong_at) if metric else "—"
            for label, metric in metrics.items()
        },
    }
    return [company, benchmark]


def _note(result: Assessment) -> dict[str, Any]:
    note = offline_note(result)
    return {
        "summary": note.get("summary", ""),
        "sectorContext": note.get("sector_context", ""),
        "strengths": note.get("strengths", []),
        "risks": note.get("risks", []),
        "whatToWatch": note.get("what_to_watch", []),
        "confidence": note.get("confidence", "medium"),
        "offline": True,
    }


def serialize_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    model: FinancialModel = dataset["model"]
    result: Assessment = dataset["result"]
    sector_key = dataset["sector_key"]
    revenue = _value_json(model, "Sales", "Revenue", "Net Sales")
    cash_flow = _value_json(
        model,
        "Free Cash Flow",
        "Cash from Operating Activity",
        "Cash from Operations",
    )
    ebitda = _value_json(model, "EBITDA")
    net_profit = _value_json(model, "Net Profit", "PAT")
    roce = _metric(result, "Return on Capital Employed (ROCE) %")
    debt_equity = _metric(result, "Debt to Equity Ratio")

    return {
        "datasetId": dataset["id"],
        "sourceLabel": dataset["source_label"],
        "ai": _analyst_status(),
        "company": model.company,
        "years": list(model.years),
        "latestYear": model.latest_year,
        "rebuiltFromDataSheet": bool(model.rebuilt_from_data_sheet),
        "sector": {
            "key": sector_key,
            "name": result.sector.name,
            "notes": result.sector.notes,
            "peerContext": result.sector.peer_context,
            "detectedKey": dataset["detected_key"],
            "detectedWhy": dataset["detected_why"],
        },
        "availableSectors": [
            {"key": key, "name": name} for key, name in sector_choices()
        ],
        "score": {
            "total": result.total_score,
            "verdict": result.verdict,
            "headline": result.headline,
            "pillars": result.pillar_scores,
            "earningsQuality": _number(result.earnings_quality),
        },
        "metrics": [_metric_json(metric) for metric in result.metrics],
        "strengths": result.strengths,
        "concerns": result.concerns,
        "dataGaps": result.data_gaps,
        "note": _note(result),
        "kpis": {
            "revenue": revenue,
            "ebitda": ebitda,
            "netProfit": net_profit,
            "cashFlow": cash_flow,
            "roce": _metric_json(roce),
            "debtEquity": _metric_json(debt_equity),
        },
        "charts": {
            "revenue": {"years": list(model.years), "values": revenue["series"]},
            "cashFlow": {"years": list(model.years), "values": cash_flow["series"]},
            "roce": {
                "years": list(model.years),
                "values": _series(model, "Return on Capital Employed (ROCE) %", "ROCE"),
            },
            "operatingMargin": {
                "years": list(model.years),
                "values": _series(model, "EBITDA Margin", "EBITDA Margins"),
            },
        },
        "sectorRows": _sector_rows(result),
        "peerRows": _peer_rows(model, result),
        "statements": {
            "Income Statement": _statement_rows(model, "Income Statement"),
            "Balance Sheet": _statement_rows(model, "Balance Sheet"),
            "Cash Flow": _statement_rows(model, "Cash Flow"),
            "Ratio Analysis": _statement_rows(model, "Ratio Analysis"),
            "Common Size": _statement_rows(model, "Common Size"),
        },
        "meta": {
            "currentPrice": _number(model.meta.get("current_price")),
            "marketCap": _number(model.meta.get("market_cap")),
        },
    }


def _create_dataset(model: FinancialModel, source_label: str) -> dict[str, Any]:
    derived = fill_missing_ratios(model)
    detected_key, detected_why = _detect(model)
    result = assess(model, get_sector(detected_key))
    dataset_id = uuid.uuid4().hex
    dataset = {
        "id": dataset_id,
        "model": model,
        "result": result,
        "sector_key": detected_key,
        "detected_key": detected_key,
        "detected_why": detected_why,
        "source_label": source_label,
        "derived": derived,
    }
    DATASETS[dataset_id] = dataset
    return dataset


def _dataset_or_error(dataset_id: str | None):
    if not dataset_id or dataset_id not in DATASETS:
        return None, (
            jsonify({
                "error": "This analysis session is no longer available. Upload the file again."
            }),
            404,
        )
    return DATASETS[dataset_id], None


def _local_answer(result: Assessment, question: str) -> str:
    """Useful no-key fallback so the analyst screen works for free."""
    lowered = question.lower()
    best = sorted(result.metrics, key=lambda metric: metric.score, reverse=True)
    worst = sorted(result.metrics, key=lambda metric: metric.score)
    if any(word in lowered for word in ("strength", "strong", "best")):
        items = [
            f"{metric.metric} is {metric.display(metric.latest)} with a {metric.score:.0f}/100 sub-score."
            for metric in best[:3]
        ]
        return "The clearest strengths in the uploaded data are " + "; ".join(items)
    if any(word in lowered for word in ("risk", "attention", "weak", "concern")):
        items = [
            f"{metric.metric} is {metric.display(metric.latest)} with a {metric.score:.0f}/100 sub-score."
            for metric in worst[:3]
        ]
        return "The ratios that deserve the closest attention are " + "; ".join(items)
    if any(word in lowered for word in ("sector", "peer", "benchmark")):
        return f"The company scores {result.total_score:.0f}/100 against the {result.sector.name} rule book. {result.sector.notes}"
    if any(word in lowered for word in ("cash", "free cash", "cfo")):
        cash_metric = next(
            (metric for metric in result.metrics if "CFO" in metric.metric), None
        )
        if cash_metric:
            return f"Cash quality is represented by {cash_metric.metric} at {cash_metric.display(cash_metric.latest)}, scoring {cash_metric.score:.0f}/100 against the {result.sector.name} benchmark."
    return f"{result.company} scores {result.total_score:.0f}/100 and is classified as {result.verdict.lower()} against {result.sector.name} expectations. The result is driven by {', '.join(result.pillar_scores.keys())}."


def _analyst_config():
    """Choose the configured chat provider without exposing credentials."""
    requested = os.getenv("LLM_PROVIDER", "").strip().lower()
    requested = {"grok": "xai"}.get(requested, requested)
    if requested:
        return config_from_env(requested)

    # Prefer xAI when an xAI key is present, while keeping the existing Groq and
    # OpenRouter integrations available for deployments that already use them.
    for provider, env_names in (
        ("xai", ("XAI_API_KEYS", "XAI_API_KEY")),
        ("groq", ("GROQ_API_KEYS", "GROQ_API_KEY")),
        ("openrouter", ("OPENROUTER_API_KEYS", "OPENROUTER_API_KEY")),
    ):
        if any(os.getenv(name, "").strip() for name in env_names):
            return config_from_env(provider)
    return config_from_env("xai")


def _analyst_status(config=None) -> dict[str, Any]:
    """Return safe connection metadata without ever returning an API key."""
    config = config or _analyst_config()
    return {
        "configured": bool(config.is_live),
        "provider": config.provider,
        "model": config.model or None,
    }


@app.get("/")
def index():
    return send_from_directory(APP_DIR, "index.html")


@app.get("/assets/<path:filename>")
def assets(filename: str):
    return send_from_directory(APP_DIR / "assets", filename)


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "service": "fundacheck",
        "framework": "flask",
        "ai": _analyst_status(),
    })


@app.post("/api/analyze")
def analyze():
    try:
        uploaded = request.files.get("file")
        demo = request.form.get("demo") == "true"
        if uploaded and uploaded.filename:
            filename = uploaded.filename
            raw = uploaded.read()
            if not raw:
                return jsonify({"error": "The uploaded file is empty."}), 400
            model = _load_source(raw, filename)
            source_label = filename
        elif demo:
            model = load_model(SAMPLE)
            source_label = "Demo model · 3S_model_sample.xlsx"
        else:
            return jsonify({"error": "Choose an XLSX, XLSM, or CSV file first."}), 400

        dataset = _create_dataset(model, source_label)
        return jsonify(serialize_dataset(dataset))
    except ParseError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:  # noqa: BLE001 - API never returns a traceback
        app.logger.exception("analysis failed")
        return jsonify({"error": f"The analysis could not be completed: {exc}"}), 500


@app.post("/api/sector")
def change_sector():
    body = request.get_json(silent=True) or {}
    dataset, error = _dataset_or_error(body.get("datasetId"))
    if error:
        return error
    sector_key = str(body.get("sectorKey") or "generic")
    profile = get_sector(sector_key)
    try:
        dataset["result"] = assess(dataset["model"], profile)
        valid_keys = {key for key, _ in sector_choices()}
        dataset["sector_key"] = sector_key if sector_key in valid_keys else "generic"
        return jsonify(serialize_dataset(dataset))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422


@app.post("/api/ask")
def ask():
    body = request.get_json(silent=True) or {}
    dataset, error = _dataset_or_error(body.get("datasetId"))
    if error:
        return error
    question = str(body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Write a question first."}), 400

    result: Assessment = dataset["result"]
    config = _analyst_config()
    provider_error = None
    using_live_model = False
    if config.is_live:
        try:
            answer = answer_question(result, question, config)
            using_live_model = True
        except LLMRequestError as exc:
            provider_error = str(exc)
            app.logger.warning("analyst request failed: %s", provider_error)
            answer = _local_answer(result, question)
    else:
        answer = _local_answer(result, question)

    ai_status = _analyst_status(config)
    if config.is_live:
        # `configured` only means a key exists; `available` reflects this
        # request so the UI cannot claim Grok answered when it did not.
        ai_status["available"] = using_live_model
    if provider_error:
        ai_status["error"] = provider_error

    return jsonify(
        {
            "answer": answer,
            "question": question,
            "grounded": True,
            "offline": not using_live_model,
            "ai": ai_status,
            "provider": config.provider if using_live_model else None,
            "model": config.model if using_live_model else None,
            "sources": [
                "Ratio Analysis · " + result.company,
                "Sector benchmark rules · " + result.sector.name,
            ],
        }
    )


@app.get("/api/report/<dataset_id>")
def report(dataset_id: str):
    dataset, error = _dataset_or_error(dataset_id)
    if error:
        return error
    try:
        pdf = build_pdf(dataset["model"], dataset["result"])
        return send_file(
            BytesIO(pdf),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"fundacheck-{_clean_name(dataset['model'].company)}.pdf",
        )
    except Exception as exc:  # noqa: BLE001 - keep export failure readable
        app.logger.exception("report export failed")
        return jsonify({"error": f"The report could not be exported: {exc}"}), 500


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "That file is larger than the 25 MB upload limit."}), 413


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )

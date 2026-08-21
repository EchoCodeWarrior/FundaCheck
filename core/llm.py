"""
llm.py
------
The "AI analyst" layer.

The numbers are already decided by scoring.py. The language model's only job is
to read those numbers *in sector context* and write the paragraph a human
analyst would write. That ordering matters: the model can never quietly change
a ratio, so the output stays auditable.

Two free providers are supported out of the box, both with generous free tiers:

  Groq        - https://console.groq.com/keys      (fast, free)
  OpenRouter  - https://openrouter.ai/keys         (free ':free' models)

If no key is configured the terminal still works — it falls back to a written
summary generated from the scoring engine itself, so the app never hard-fails
on a missing API key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import requests

from .scoring import Assessment

TIMEOUT_SECONDS = 60


@dataclass
class LLMConfig:
    """
    Connection settings for the analyst.

    `api_keys` is a pool rather than a single key: free tiers rate-limit per
    key, so a second key lets a busy session keep working instead of silently
    dropping to the offline note.
    """

    provider: str = "groq"          # "groq" | "openrouter" | "offline"
    api_keys: list[str] = field(default_factory=list)
    model: str = ""
    temperature: float = 0.2
    reasoning_effort: str = "high"

    @property
    def api_key(self) -> str:
        return self.api_keys[0] if self.api_keys else ""

    @property
    def is_live(self) -> bool:
        return self.provider != "offline" and bool(self.api_keys)


PROVIDERS = {
    "groq": {
        "label": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        # Reasoning-capable models only: the verdict is a judgement call across
        # a dozen interacting ratios, which is exactly where a model that thinks
        # before answering beats one that does not.
        "models": [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3-32b",
        ],
        "key_env": "GROQ_API_KEY",
        "signup": "https://console.groq.com/keys",
    },
    "openrouter": {
        "label": "OpenRouter (free models)",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "models": [
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemma-2-9b-it:free",
            "mistralai/mistral-7b-instruct:free",
        ],
        "key_env": "OPENROUTER_API_KEY",
        "signup": "https://openrouter.ai/keys",
    },
}


def _keys_from(source: dict | None, env_name: str) -> list[str]:
    """
    Collect API keys from Streamlit secrets or the environment.

    Accepted shapes, in order: a `groq.api_keys` list, a `GROQ_API_KEYS`
    comma-separated string, or a single `GROQ_API_KEY`. Keys are never held in
    source — they come from the deployment's secret store.
    """
    keys: list[str] = []

    if source:
        block = source.get(env_name.split("_")[0].lower(), {})
        if isinstance(block, dict):
            listed = block.get("api_keys") or block.get("keys")
            if isinstance(listed, (list, tuple)):
                keys.extend(str(k) for k in listed)
            elif isinstance(listed, str):
                keys.extend(listed.split(","))
        single = source.get(env_name) or source.get(f"{env_name}S")
        if isinstance(single, str):
            keys.extend(single.split(","))

    for name in (f"{env_name}S", env_name):
        raw = os.getenv(name, "")
        if raw:
            keys.extend(raw.split(","))

    seen, unique = set(), []
    for key in (k.strip() for k in keys):
        if key and key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def config_from_env(provider: str = "groq", model: str = "",
                    secrets: dict | None = None) -> LLMConfig:
    spec = PROVIDERS.get(provider)
    if not spec:
        return LLMConfig(provider="offline")
    keys = _keys_from(secrets, spec["key_env"])
    return LLMConfig(
        provider=provider,
        api_keys=keys,
        model=model or spec["models"][0],
    )


SYSTEM_PROMPT = """You are a buy-side equity analyst writing an internal note.

Rules you must follow:
- The numeric score and verdict were produced by a deterministic scoring engine.
  Do NOT contradict them or invent your own score. Explain them.
- Judge every ratio against the SECTOR the company operates in. A debt/equity of
  8x is normal for a bank and alarming for a software firm. Say so explicitly
  where it applies.
- Be specific: quote the actual numbers you are given. Never invent a figure,
  a competitor name, or a news event that is not in the data.
- If a metric is missing, say it is missing rather than guessing.
- Write in plain, confident English. No hype, no disclaimers about being an AI.

Return STRICT JSON with exactly these keys and no markdown fencing:
{
  "summary": "3-4 sentence verdict explaining WHY the company scores where it does, in sector terms",
  "sector_context": "2-3 sentences on what 'good' looks like in this sector and how this company compares",
  "strengths": ["3 to 4 specific bullet points, each quoting a number"],
  "risks": ["3 to 4 specific bullet points, each quoting a number"],
  "what_to_watch": ["2 to 3 forward-looking items an analyst should track next"],
  "confidence": "high | medium | low, based on how complete the data is"
}"""


def build_user_prompt(result: Assessment) -> str:
    gaps = ", ".join(result.data_gaps) if result.data_gaps else "none"
    quality = (
        f"{result.earnings_quality:.2f}x" if result.earnings_quality is not None else "not available"
    )
    pillars = ", ".join(f"{name}: {score:.0f}/100" for name, score in result.pillar_scores.items())

    return f"""COMPANY: {result.company}
SECTOR APPLIED: {result.sector.name}
SECTOR CHARACTERISTICS: {result.sector.notes}
SECTOR PEER CONTEXT: {result.sector.peer_context or "not supplied"}

ENGINE OUTPUT
Composite score: {result.total_score}/100
Verdict: {result.verdict}
Pillar scores: {pillars}
Earnings quality (3Y average CFO/PAT): {quality}
Metrics that could not be found in the workbook: {gaps}

RATIO DETAIL (latest year, 3-year average, 0-100 sub-score, and the sector's
weak/strong bands — note the bands are sector-specific, not universal):
{result.as_prompt_table()}

Write the analyst note as JSON."""


def _post(config: LLMConfig, messages: list[dict]) -> str:
    """
    Call the provider, trying each key in the pool.

    A rate-limited or rejected key moves to the next one rather than failing the
    request; only when every key is exhausted does the caller fall back.
    """
    spec = PROVIDERS[config.provider]
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": 2600,
    }
    if config.reasoning_effort and "gpt-oss" in config.model:
        payload["reasoning_effort"] = config.reasoning_effort

    last_error = "no API key configured"
    for key in config.api_keys:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if config.provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/fundacheck"
            headers["X-Title"] = "FundaCheck"
        try:
            response = requests.post(spec["url"], headers=headers, json=payload,
                                     timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue

        if response.status_code == 200:
            message = response.json()["choices"][0]["message"]
            # Reasoning models may return their thinking separately; the answer
            # is always in content.
            return message.get("content") or ""
        if response.status_code in (401, 402, 403, 429):
            last_error = f"{response.status_code} on one key"
            continue        # try the next key in the pool
        raise RuntimeError(f"{spec['label']} returned {response.status_code}: "
                           f"{response.text[:200]}")

    raise RuntimeError(f"every key failed — last error: {last_error}")


def _extract_json(text: str) -> dict:
    """LLMs sometimes wrap JSON in prose or code fences. Dig it out."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in the model response.")
    return json.loads(text[start:end + 1])


def offline_note(result: Assessment) -> dict:
    """
    Deterministic fallback so the terminal is fully usable with no API key.
    Built from the same scoring output the LLM would have received.
    """
    best = sorted(result.metrics, key=lambda m: m.score, reverse=True)
    worst = sorted(result.metrics, key=lambda m: m.score)
    strong_pillars = [p for p, s in result.pillar_scores.items() if s >= 60]
    weak_pillars = [p for p, s in result.pillar_scores.items() if s < 45]

    summary = (
        f"{result.company} scores {result.total_score}/100 against "
        f"{result.sector.name} expectations, which places it in the "
        f"{result.verdict.lower()} band. "
        + (f"It is carried by {', '.join(strong_pillars)}. " if strong_pillars else "")
        + (f"It is held back by {', '.join(weak_pillars)}. " if weak_pillars else "")
        + "This is the rule-based reading — the AI analyst could not be reached "
          "for its narrative view."
    )

    return {
        "summary": summary,
        "sector_context": result.sector.notes,
        "strengths": [
            f"{m.metric}: {m.display(m.latest)} (sub-score {m.score:.0f}/100)"
            for m in best[:4] if m.score >= 55
        ] or ["No metric currently clears its sector's strong threshold."],
        "risks": [
            f"{m.metric}: {m.display(m.latest)} against a sector weak band of "
            f"{m.display(m.weak_at)} (sub-score {m.score:.0f}/100)"
            for m in worst[:4] if m.score < 60
        ] or ["No metric falls into the sector's weak band."],
        "what_to_watch": [
            f"Direction of {m.metric} — currently "
            f"{'improving' if m.trend > 0.05 else 'deteriorating' if m.trend < -0.05 else 'flat'}."
            for m in worst[:3]
        ],
        "confidence": "low" if result.data_gaps else "medium",
        "_offline": True,
    }


def analyse(result: Assessment, config: LLMConfig) -> dict:
    """
    Ask the language model for a sector-aware analyst note.
    Falls back to the offline note on any failure, with the error attached
    so the UI can tell the user what went wrong.
    """
    if not config.is_live:
        return offline_note(result)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(result)},
    ]
    try:
        note = _extract_json(_post(config, messages))
    except Exception as exc:                      # noqa: BLE001 - surfaced in the UI
        fallback = offline_note(result)
        fallback["_error"] = str(exc)
        return fallback

    note["_offline"] = False
    note["_model"] = config.model
    return note


def answer_question(result: Assessment, question: str, config: LLMConfig) -> str:
    """Free-text Q&A about the loaded company (the 'ask the analyst' box)."""
    if not config.is_live:
        return (
            "The analyst is not connected. Add Groq API keys to the app's secrets "
            "(see the README) and ask again."
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You are an equity analyst answering a question about one company. "
                "Use only the data provided. Judge everything in sector context. "
                "If the data does not answer the question, say so. "
                "Answer in under 150 words, plain prose, no markdown headings."
            ),
        },
        {"role": "user", "content": f"{build_user_prompt(result)}\n\nANALYST QUESTION: {question}"},
    ]
    try:
        return _post(config, messages).strip()
    except Exception as exc:                      # noqa: BLE001
        return f"The model could not be reached: {exc}"

"""LLM backends for the agent nodes.

LLM=fallback   no model; the rules in fallbacks.py (tests, the Pi, demo insurance).
LLM=gemini     ranker + narrator on Gemini via Vertex AI (langchain-google-vertexai); the skeptic
               on OpenRouter (a different model family) when OPENROUTER_API_KEY is set, else Gemini.
LLM=openrouter every node on OpenRouter (the plan's backup runtime).

Env: GEMINI_MODEL, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION (default 'global'),
GOOGLE_APPLICATION_CREDENTIALS, OPENROUTER_API_KEY, SKEPTIC_MODEL (OpenRouter slug),
OPENROUTER_MODEL (non-skeptic nodes under LLM=openrouter; default SKEPTIC_MODEL).

langchain is imported lazily inside the backend constructors, so LLM=fallback never builds a
client and needs no credentials.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

PROMPTS = Path(__file__).resolve().parent / "prompts"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODES = ("fallback", "gemini", "openrouter")
MAX_TOKENS = 2000
# the models the 2026-11-07 runs used (docs/m2_results.md); .env overrides
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_SKEPTIC_MODEL = "openai/gpt-5.4-mini"
T = TypeVar("T", bound=BaseModel)


def mode(explicit: str | None = None) -> str:
    m = (explicit or os.environ.get("LLM") or "fallback").strip().lower()
    if m not in MODES:
        raise ValueError(f"LLM must be one of {MODES}, got {m!r}")
    return m


def prompt(name: str, **fields: str) -> str:
    """prompts/<name>.md with {{field}} placeholders filled (plain replace, so JSON braces in
    the prompt are safe)."""
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for k, v in fields.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name, default)
    return v.strip().strip('"').strip("'") if v else v


def _gemini():
    from langchain_google_vertexai import ChatVertexAI

    model = _env("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    if not _env("GOOGLE_CLOUD_PROJECT"):
        # fail fast and offline instead of letting the SDK guess a project from the machine
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is not set")
    chat = ChatVertexAI(
        model=model,
        project=_env("GOOGLE_CLOUD_PROJECT"),
        location=_env("GOOGLE_CLOUD_LOCATION", "global"),
        temperature=0,
        max_retries=3,  # Vertex returns 429 under burst load; retries back off
    )
    return chat, f"vertex:{model}"


def _openrouter(model: str | None):
    from langchain_openai import ChatOpenAI

    if not _env("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    if model and "/" not in model and model.startswith("gpt"):
        model = f"openai/{model}"  # OpenRouter slugs carry the vendor: openai/gpt-5.4-mini

    chat = ChatOpenAI(
        model=model,
        base_url=OPENROUTER_BASE,
        api_key=_env("OPENROUTER_API_KEY"),
        temperature=0,
        max_tokens=MAX_TOKENS,  # OpenRouter reserves credit for max_tokens; its default is 65k
        max_retries=1,
        timeout=60,
    )
    return chat, f"openrouter:{model}"


def backend(role: str, llm_mode: str):
    """(chat model, label) for a node role ('ranker' | 'skeptic' | 'narrator'), or None for
    fallback."""
    if llm_mode == "fallback":
        return None
    skeptic_model = _env("SKEPTIC_MODEL", DEFAULT_SKEPTIC_MODEL)
    if llm_mode == "openrouter":
        return _openrouter(
            _env("OPENROUTER_MODEL") or skeptic_model if role != "skeptic" else skeptic_model
        )
    if role == "skeptic" and _env("OPENROUTER_API_KEY"):
        return _openrouter(skeptic_model)
    return _gemini()


async def structured(
    role: str, llm_mode: str, schema: type[T], system: str, user: str
) -> tuple[T, dict[str, Any]]:
    """Call the role's model for a `schema` object. Raises on any failure (the graph catches it
    and uses the deterministic fallback). Returns (object, meta with model, tokens, seconds)."""
    chat, label = backend(role, llm_mode)
    t0 = time.perf_counter()
    runnable = chat.with_structured_output(schema, include_raw=True)
    out = await runnable.ainvoke([("system", system), ("human", user)])
    dt = time.perf_counter() - t0
    if out.get("parsing_error") or out.get("parsed") is None:
        raise ValueError(f"{label} returned no valid {schema.__name__}: {out.get('parsing_error')}")
    usage = getattr(out.get("raw"), "usage_metadata", None) or {}
    meta = {
        "model": label,
        "input_tokens": int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "seconds": round(dt, 2),
    }
    parsed = out["parsed"]
    if isinstance(parsed, dict):
        parsed = schema.model_validate(parsed)
    return parsed, meta

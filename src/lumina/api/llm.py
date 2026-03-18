"""LLM client abstraction — provider-routed dispatch."""

from __future__ import annotations

import os

from lumina.api.config import ANTHROPIC_MODEL, LLM_PROVIDER, OPENAI_MODEL


def _call_openai(system: str, user: str, model: str | None = None) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    client = OpenAI()
    response = client.chat.completions.create(
        model=model or OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.4,
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


def _call_anthropic(system: str, user: str, model: str | None = None) -> str:
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    client = Anthropic()
    response = client.messages.create(
        model=model or ANTHROPIC_MODEL,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=0.4,
        max_tokens=1024,
    )
    return response.content[0].text


def _validate_provider_api_key(provider: str) -> None:
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required for live anthropic mode. "
                "Set the key in your runtime environment. "
                "Deterministic mode (deterministic_response=true) does not require provider keys."
            )
        return

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is required for live openai mode. "
            "Set the key in your runtime environment. "
            "Deterministic mode (deterministic_response=true) does not require provider keys."
        )


def call_llm(system: str, user: str, model: str | None = None) -> str:
    _validate_provider_api_key(LLM_PROVIDER)
    if LLM_PROVIDER == "anthropic":
        return _call_anthropic(system, user, model)
    return _call_openai(system, user, model)

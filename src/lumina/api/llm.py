"""LLM client abstraction — provider-routed dispatch.

Supported providers (LUMINA_LLM_PROVIDER):
  openai    — OpenAI API (default)
  anthropic — Anthropic API
  local     — Any OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, TGI, OpenRouter, cluster)
  google    — Google Gemini API (google-generativeai SDK)
  azure     — Azure OpenAI Service
  mistral   — Mistral AI API
"""

from __future__ import annotations

import os

from lumina.api.config import (
    ANTHROPIC_MODEL,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    GOOGLE_MODEL,
    LLM_ENDPOINT,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT,
    MISTRAL_MODEL,
    OPENAI_MODEL,
)

_LLM_TEMPERATURE = 0.4
_LLM_MAX_TOKENS = 1024


# ─────────────────────────────────────────────────────────────
# Provider Implementations
# ─────────────────────────────────────────────────────────────


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
        temperature=_LLM_TEMPERATURE,
        max_tokens=_LLM_MAX_TOKENS,
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
        temperature=_LLM_TEMPERATURE,
        max_tokens=_LLM_MAX_TOKENS,
    )
    return response.content[0].text


def _call_local_llm(system: str, user: str, model: str | None = None) -> str:
    """Call any OpenAI-compatible local endpoint (Ollama, vLLM, LM Studio, TGI, OpenRouter)."""
    try:
        import httpx
    except ImportError:
        raise RuntimeError(
            "httpx package is required for local LLM provider. "
            "Run: pip install httpx"
        )

    url = f"{LLM_ENDPOINT.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model or LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": _LLM_TEMPERATURE,
        "max_tokens": _LLM_MAX_TOKENS,
    }
    resp = httpx.post(url, json=payload, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"] or ""


def _call_google_llm(system: str, user: str, model: str | None = None) -> str:
    """Call the Google Gemini API via google-generativeai SDK."""
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError(
            "google-generativeai package not installed. "
            "Run: pip install google-generativeai"
        )

    genai.configure(api_key=os.environ.get("GOOGLE_API_KEY", ""))
    gemini = genai.GenerativeModel(
        model_name=model or GOOGLE_MODEL,
        system_instruction=system,
    )
    response = gemini.generate_content(
        user,
        generation_config=genai.GenerationConfig(
            temperature=_LLM_TEMPERATURE,
            max_output_tokens=_LLM_MAX_TOKENS,
        ),
    )
    return response.text or ""


def _call_azure_llm(system: str, user: str, model: str | None = None) -> str:
    """Call Azure OpenAI Service."""
    try:
        from openai import AzureOpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    client = AzureOpenAI(
        api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_version=AZURE_OPENAI_API_VERSION,
    )
    deployment = model or AZURE_OPENAI_DEPLOYMENT
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=_LLM_TEMPERATURE,
        max_tokens=_LLM_MAX_TOKENS,
    )
    return response.choices[0].message.content or ""


def _call_mistral_llm(system: str, user: str, model: str | None = None) -> str:
    """Call Mistral AI API."""
    try:
        from mistralai import Mistral
    except ImportError:
        raise RuntimeError(
            "mistralai package not installed. Run: pip install mistralai"
        )

    client = Mistral(api_key=os.environ.get("MISTRAL_API_KEY", ""))
    response = client.chat.complete(
        model=model or MISTRAL_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=_LLM_TEMPERATURE,
        max_tokens=_LLM_MAX_TOKENS,
    )
    return response.choices[0].message.content or ""


# ─────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────


def _validate_provider_api_key(provider: str) -> None:
    if provider == "local":
        # Local provider health is checked at call time; no key required.
        return

    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required for live anthropic mode. "
                "Set the key in your runtime environment. "
                "Deterministic mode (deterministic_response=true) does not require provider keys."
            )
        return

    if provider == "google":
        if not os.environ.get("GOOGLE_API_KEY"):
            raise RuntimeError(
                "GOOGLE_API_KEY is required for live google mode. "
                "Set the key in your runtime environment. "
                "Deterministic mode (deterministic_response=true) does not require provider keys."
            )
        return

    if provider == "azure":
        if not os.environ.get("AZURE_OPENAI_API_KEY"):
            raise RuntimeError(
                "AZURE_OPENAI_API_KEY is required for live azure mode. "
                "Set the key in your runtime environment. "
                "Deterministic mode (deterministic_response=true) does not require provider keys."
            )
        if not AZURE_OPENAI_ENDPOINT:
            raise RuntimeError(
                "LUMINA_AZURE_OPENAI_ENDPOINT is required for live azure mode. "
                "Set the endpoint URL in your runtime environment."
            )
        return

    if provider == "mistral":
        if not os.environ.get("MISTRAL_API_KEY"):
            raise RuntimeError(
                "MISTRAL_API_KEY is required for live mistral mode. "
                "Set the key in your runtime environment. "
                "Deterministic mode (deterministic_response=true) does not require provider keys."
            )
        return

    # Default: openai
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is required for live openai mode. "
            "Set the key in your runtime environment. "
            "Deterministic mode (deterministic_response=true) does not require provider keys."
        )


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────


def call_llm(system: str, user: str, model: str | None = None) -> str:
    """Send a request to the configured LLM provider.

    Raises ``RuntimeError`` on configuration or transport errors.
    """
    _validate_provider_api_key(LLM_PROVIDER)
    if LLM_PROVIDER == "anthropic":
        return _call_anthropic(system, user, model)
    if LLM_PROVIDER == "local":
        return _call_local_llm(system, user, model)
    if LLM_PROVIDER == "google":
        return _call_google_llm(system, user, model)
    if LLM_PROVIDER == "azure":
        return _call_azure_llm(system, user, model)
    if LLM_PROVIDER == "mistral":
        return _call_mistral_llm(system, user, model)
    return _call_openai(system, user, model)

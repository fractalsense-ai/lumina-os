"""Tests for lumina.api.llm — LLM provider dispatch layer.

Covers backend dispatch, provider validation, custom model pass-through,
and correct use of endpoint/timeout for the local provider.
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lumina.api.llm import (
    _call_anthropic,
    _call_azure_llm,
    _call_google_llm,
    _call_local_llm,
    _call_mistral_llm,
    _call_openai,
    _validate_provider_api_key,
    call_llm,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _openai_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _anthropic_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _httpx_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    resp.raise_for_status.return_value = None
    return resp


# ── OpenAI backend ────────────────────────────────────────────────────────────


class TestCallOpenai:

    @pytest.mark.unit
    def test_returns_content(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _openai_response("gpt result")
        with patch("openai.OpenAI", return_value=mock_client):
            result = _call_openai("sys", "usr")
        assert result == "gpt result"

    @pytest.mark.unit
    def test_custom_model_forwarded(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _openai_response("")
        with patch("openai.OpenAI", return_value=mock_client):
            _call_openai("sys", "usr", model="gpt-4-turbo")
        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "gpt-4-turbo"

    @pytest.mark.unit
    def test_import_error_raises_runtime_error(self) -> None:
        with patch.dict(sys.modules, {"openai": None}):
            with pytest.raises(RuntimeError, match="openai package not installed"):
                _call_openai("sys", "usr")


# ── Anthropic backend ─────────────────────────────────────────────────────────


class TestCallAnthropic:

    @pytest.mark.unit
    def test_returns_text(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _anthropic_response("claude result")
        with patch("anthropic.Anthropic", return_value=mock_client):
            result = _call_anthropic("sys", "usr")
        assert result == "claude result"

    @pytest.mark.unit
    def test_custom_model_forwarded(self) -> None:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _anthropic_response("")
        with patch("anthropic.Anthropic", return_value=mock_client):
            _call_anthropic("sys", "usr", model="claude-3-opus-20240229")
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-3-opus-20240229"

    @pytest.mark.unit
    def test_import_error_raises_runtime_error(self) -> None:
        with patch.dict(sys.modules, {"anthropic": None}):
            with pytest.raises(RuntimeError, match="anthropic package not installed"):
                _call_anthropic("sys", "usr")


# ── Local backend ─────────────────────────────────────────────────────────────


class TestCallLocalLlm:

    @pytest.mark.unit
    @patch("lumina.api.llm.LLM_ENDPOINT", "http://cluster:8080")
    @patch("lumina.api.llm.LLM_TIMEOUT", 90.0)
    def test_posts_to_correct_url(self) -> None:
        with patch("httpx.post", return_value=_httpx_response("local reply")) as mock_post:
            result = _call_local_llm("sys", "usr")
        assert result == "local reply"
        mock_post.assert_called_once()
        url_arg = mock_post.call_args.args[0]
        assert url_arg == "http://cluster:8080/v1/chat/completions"

    @pytest.mark.unit
    @patch("lumina.api.llm.LLM_TIMEOUT", 55.0)
    def test_timeout_passed_to_httpx(self) -> None:
        with patch("httpx.post", return_value=_httpx_response("ok")) as mock_post:
            _call_local_llm("sys", "usr")
        assert mock_post.call_args.kwargs["timeout"] == 55.0

    @pytest.mark.unit
    @patch("lumina.api.llm.LLM_MODEL", "mistral-7b")
    def test_default_model_used_when_no_override(self) -> None:
        with patch("httpx.post", return_value=_httpx_response("ok")) as mock_post:
            _call_local_llm("sys", "usr")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["model"] == "mistral-7b"

    @pytest.mark.unit
    def test_custom_model_overrides_default(self) -> None:
        with patch("httpx.post", return_value=_httpx_response("ok")) as mock_post:
            _call_local_llm("sys", "usr", model="llama3:70b")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["model"] == "llama3:70b"

    @pytest.mark.unit
    def test_trailing_slash_stripped_from_endpoint(self) -> None:
        with patch("lumina.api.llm.LLM_ENDPOINT", "http://localhost:11434/"):
            with patch("httpx.post", return_value=_httpx_response("ok")) as mock_post:
                _call_local_llm("sys", "usr")
        url_arg = mock_post.call_args.args[0]
        assert not url_arg.count("//v1")

    @pytest.mark.unit
    def test_import_error_raises_runtime_error(self) -> None:
        with patch.dict(sys.modules, {"httpx": None}):
            with pytest.raises(RuntimeError, match="httpx package is required"):
                _call_local_llm("sys", "usr")


# ── Google backend ────────────────────────────────────────────────────────────


class TestCallGoogleLlm:

    @pytest.mark.unit
    def test_returns_text(self) -> None:
        mock_genai = MagicMock()
        mock_model_inst = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "gemini result"
        mock_model_inst.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model_inst
        mock_genai.GenerationConfig = MagicMock(return_value={})

        # The import `import google.generativeai as genai` resolves via
        # sys.modules["google"].generativeai — so both entries must agree.
        mock_google_pkg = MagicMock()
        mock_google_pkg.generativeai = mock_genai

        with patch.dict(sys.modules, {"google.generativeai": mock_genai, "google": mock_google_pkg}):
            result = _call_google_llm("sys", "usr")
        assert result == "gemini result"

    @pytest.mark.unit
    def test_import_error_raises_runtime_error(self) -> None:
        with patch.dict(sys.modules, {"google.generativeai": None, "google": None}):
            with pytest.raises(RuntimeError, match="google-generativeai package not installed"):
                _call_google_llm("sys", "usr")


# ── Azure backend ─────────────────────────────────────────────────────────────


class TestCallAzureLlm:

    @pytest.mark.unit
    def test_returns_content(self) -> None:
        mock_azure_client = MagicMock()
        mock_azure_client.chat.completions.create.return_value = _openai_response("azure result")

        with patch("openai.AzureOpenAI", return_value=mock_azure_client):
            with patch("lumina.api.llm.AZURE_OPENAI_ENDPOINT", "https://my-resource.openai.azure.com/"):
                result = _call_azure_llm("sys", "usr")
        assert result == "azure result"

    @pytest.mark.unit
    def test_custom_model_used_as_deployment(self) -> None:
        mock_azure_client = MagicMock()
        mock_azure_client.chat.completions.create.return_value = _openai_response("")

        with patch("openai.AzureOpenAI", return_value=mock_azure_client):
            _call_azure_llm("sys", "usr", model="gpt-4o-deploy")
        call_kwargs = mock_azure_client.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "gpt-4o-deploy"


# ── Mistral backend ───────────────────────────────────────────────────────────


class TestCallMistralLlm:

    @pytest.mark.unit
    def test_returns_content(self) -> None:
        mock_mistral_cls = MagicMock()
        mock_client = MagicMock()
        mock_mistral_cls.return_value = mock_client

        msg = MagicMock()
        msg.content = "mistral result"
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        mock_client.chat.complete.return_value = resp

        mock_mistralai = MagicMock()
        mock_mistralai.Mistral = mock_mistral_cls

        with patch.dict(sys.modules, {"mistralai": mock_mistralai}):
            result = _call_mistral_llm("sys", "usr")
        assert result == "mistral result"

    @pytest.mark.unit
    def test_import_error_raises_runtime_error(self) -> None:
        with patch.dict(sys.modules, {"mistralai": None}):
            with pytest.raises(RuntimeError, match="mistralai package not installed"):
                _call_mistral_llm("sys", "usr")


# ── Provider Validation ───────────────────────────────────────────────────────


class TestValidateProviderApiKey:

    @pytest.mark.unit
    def test_local_requires_no_key(self) -> None:
        # Should not raise regardless of env state.
        with patch.dict("os.environ", {}, clear=True):
            _validate_provider_api_key("local")  # no exception

    @pytest.mark.unit
    def test_openai_raises_when_no_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
                _validate_provider_api_key("openai")

    @pytest.mark.unit
    def test_openai_passes_when_key_set(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            _validate_provider_api_key("openai")  # no exception

    @pytest.mark.unit
    def test_anthropic_raises_when_no_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                _validate_provider_api_key("anthropic")

    @pytest.mark.unit
    def test_anthropic_passes_when_key_set(self) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            _validate_provider_api_key("anthropic")  # no exception

    @pytest.mark.unit
    def test_google_raises_when_no_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
                _validate_provider_api_key("google")

    @pytest.mark.unit
    def test_google_passes_when_key_set(self) -> None:
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "AIza-test"}):
            _validate_provider_api_key("google")  # no exception

    @pytest.mark.unit
    def test_azure_raises_when_no_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("lumina.api.llm.AZURE_OPENAI_ENDPOINT", "https://x.openai.azure.com/"):
                with pytest.raises(RuntimeError, match="AZURE_OPENAI_API_KEY"):
                    _validate_provider_api_key("azure")

    @pytest.mark.unit
    def test_azure_raises_when_no_endpoint(self) -> None:
        with patch.dict("os.environ", {"AZURE_OPENAI_API_KEY": "az-test"}):
            with patch("lumina.api.llm.AZURE_OPENAI_ENDPOINT", ""):
                with pytest.raises(RuntimeError, match="LUMINA_AZURE_OPENAI_ENDPOINT"):
                    _validate_provider_api_key("azure")

    @pytest.mark.unit
    def test_azure_passes_when_key_and_endpoint_set(self) -> None:
        with patch.dict("os.environ", {"AZURE_OPENAI_API_KEY": "az-test"}):
            with patch("lumina.api.llm.AZURE_OPENAI_ENDPOINT", "https://x.openai.azure.com/"):
                _validate_provider_api_key("azure")  # no exception

    @pytest.mark.unit
    def test_mistral_raises_when_no_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
                _validate_provider_api_key("mistral")

    @pytest.mark.unit
    def test_mistral_passes_when_key_set(self) -> None:
        with patch.dict("os.environ", {"MISTRAL_API_KEY": "ms-test"}):
            _validate_provider_api_key("mistral")  # no exception

    @pytest.mark.unit
    def test_unknown_provider_falls_through_to_openai_check(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
                _validate_provider_api_key("unknown_provider")


# ── call_llm Dispatch ─────────────────────────────────────────────────────────


class TestCallLlmDispatch:

    @pytest.mark.unit
    @patch("lumina.api.llm.LLM_PROVIDER", "openai")
    @patch("lumina.api.llm._call_openai", return_value="openai resp")
    @patch("lumina.api.llm._validate_provider_api_key")
    def test_openai_dispatch(self, _v: Any, mock_fn: MagicMock) -> None:
        assert call_llm("sys", "usr") == "openai resp"
        mock_fn.assert_called_once_with("sys", "usr", None)

    @pytest.mark.unit
    @patch("lumina.api.llm.LLM_PROVIDER", "anthropic")
    @patch("lumina.api.llm._call_anthropic", return_value="anthropic resp")
    @patch("lumina.api.llm._validate_provider_api_key")
    def test_anthropic_dispatch(self, _v: Any, mock_fn: MagicMock) -> None:
        assert call_llm("sys", "usr") == "anthropic resp"
        mock_fn.assert_called_once_with("sys", "usr", None)

    @pytest.mark.unit
    @patch("lumina.api.llm.LLM_PROVIDER", "local")
    @patch("lumina.api.llm._call_local_llm", return_value="local resp")
    @patch("lumina.api.llm._validate_provider_api_key")
    def test_local_dispatch(self, _v: Any, mock_fn: MagicMock) -> None:
        assert call_llm("sys", "usr") == "local resp"
        mock_fn.assert_called_once_with("sys", "usr", None)

    @pytest.mark.unit
    @patch("lumina.api.llm.LLM_PROVIDER", "google")
    @patch("lumina.api.llm._call_google_llm", return_value="google resp")
    @patch("lumina.api.llm._validate_provider_api_key")
    def test_google_dispatch(self, _v: Any, mock_fn: MagicMock) -> None:
        assert call_llm("sys", "usr") == "google resp"
        mock_fn.assert_called_once_with("sys", "usr", None)

    @pytest.mark.unit
    @patch("lumina.api.llm.LLM_PROVIDER", "azure")
    @patch("lumina.api.llm._call_azure_llm", return_value="azure resp")
    @patch("lumina.api.llm._validate_provider_api_key")
    def test_azure_dispatch(self, _v: Any, mock_fn: MagicMock) -> None:
        assert call_llm("sys", "usr") == "azure resp"
        mock_fn.assert_called_once_with("sys", "usr", None)

    @pytest.mark.unit
    @patch("lumina.api.llm.LLM_PROVIDER", "mistral")
    @patch("lumina.api.llm._call_mistral_llm", return_value="mistral resp")
    @patch("lumina.api.llm._validate_provider_api_key")
    def test_mistral_dispatch(self, _v: Any, mock_fn: MagicMock) -> None:
        assert call_llm("sys", "usr") == "mistral resp"
        mock_fn.assert_called_once_with("sys", "usr", None)

    @pytest.mark.unit
    @patch("lumina.api.llm.LLM_PROVIDER", "local")
    @patch("lumina.api.llm._call_local_llm", return_value="resp")
    @patch("lumina.api.llm._validate_provider_api_key")
    def test_custom_model_passed_through(self, _v: Any, mock_fn: MagicMock) -> None:
        call_llm("sys", "usr", model="llama3:70b")
        mock_fn.assert_called_once_with("sys", "usr", "llama3:70b")

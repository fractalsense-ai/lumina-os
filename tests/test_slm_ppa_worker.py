"""Tests for lumina.core.slm_ppa_worker — async SLM PPA enrichment worker.

Covers lifecycle (start/stop/is_running), enrichment dispatch, and
graceful shutdown via sentinel.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lumina.core.slm_ppa_worker import (
    EnrichmentKind,
    EnrichmentRequest,
    enqueue,
    is_running,
    start,
    stop,
)


def _run(coro):
    """Run an async coroutine in a fresh event loop."""
    return asyncio.run(coro)


def _reset_worker():
    """Reset worker module-level state between tests."""
    import lumina.core.slm_ppa_worker as w
    w._running = False
    w._worker_task = None
    w._queue = asyncio.Queue()


# ── Lifecycle ─────────────────────────────────────────────────────────────────


class TestWorkerLifecycle:

    @pytest.mark.unit
    def test_start_sets_running(self) -> None:
        async def _test():
            _reset_worker()
            await start()
            assert is_running()
            await stop()
            assert not is_running()
        _run(_test())

    @pytest.mark.unit
    def test_duplicate_start_is_noop(self) -> None:
        async def _test():
            import lumina.core.slm_ppa_worker as w
            _reset_worker()
            await start()
            task1 = w._worker_task
            await start()  # duplicate — should be no-op
            assert w._worker_task is task1
            await stop()
        _run(_test())

    @pytest.mark.unit
    def test_stop_without_start_is_safe(self) -> None:
        async def _test():
            _reset_worker()
            await stop()  # should not raise
        _run(_test())


# ── Enrichment Dispatch ───────────────────────────────────────────────────────


class TestEnrichmentDispatch:

    @pytest.mark.unit
    def test_physics_enrichment(self) -> None:
        async def _test():
            _reset_worker()
            with patch(
                "lumina.core.slm_ppa_worker._enrich_physics",
                new_callable=AsyncMock,
                return_value={"matched_invariants": ["inv1"]},
            ) as mock_physics:
                await start()
                result = await enqueue(
                    EnrichmentKind.PHYSICS_CONTEXT,
                    {"incoming_signals": {"x": 1}, "domain_physics": {}},
                )
                assert result == {"matched_invariants": ["inv1"]}
                mock_physics.assert_awaited_once()
                await stop()
        _run(_test())

    @pytest.mark.unit
    def test_command_enrichment(self) -> None:
        async def _test():
            _reset_worker()
            with patch(
                "lumina.core.slm_ppa_worker._enrich_command",
                new_callable=AsyncMock,
                return_value={"operation": "update_domain_physics", "target": "t", "params": {}},
            ) as mock_cmd:
                await start()
                result = await enqueue(
                    EnrichmentKind.COMMAND_PARSE,
                    {"natural_language": "update something"},
                )
                assert result is not None
                assert result["operation"] == "update_domain_physics"
                mock_cmd.assert_awaited_once()
                await stop()
        _run(_test())

    @pytest.mark.unit
    def test_enrichment_failure_propagates(self) -> None:
        async def _test():
            _reset_worker()
            with patch(
                "lumina.core.slm_ppa_worker._enrich_physics",
                new_callable=AsyncMock,
                side_effect=RuntimeError("SLM unavailable"),
            ):
                await start()
                with pytest.raises(RuntimeError, match="SLM unavailable"):
                    await enqueue(
                        EnrichmentKind.PHYSICS_CONTEXT,
                        {"incoming_signals": {}, "domain_physics": {}},
                    )
                await stop()
        _run(_test())


# ── EnrichmentRequest ─────────────────────────────────────────────────────────


class TestEnrichmentRequest:

    @pytest.mark.unit
    def test_request_has_future(self) -> None:
        async def _test():
            req = EnrichmentRequest(
                kind=EnrichmentKind.PHYSICS_CONTEXT,
                payload={"incoming_signals": {}, "domain_physics": {}},
            )
            assert isinstance(req.future, asyncio.Future)
        _run(_test())

    @pytest.mark.unit
    def test_enrichment_kind_values(self) -> None:
        assert EnrichmentKind.PHYSICS_CONTEXT.value == "physics_context"
        assert EnrichmentKind.COMMAND_PARSE.value == "command_parse"

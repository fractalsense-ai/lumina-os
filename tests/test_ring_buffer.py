"""Tests for lumina.session.ring_buffer — ConversationRingBuffer."""
from __future__ import annotations

import threading

import pytest

from lumina.session.ring_buffer import ConversationRingBuffer, TurnRecord


@pytest.mark.unit
def test_push_and_len() -> None:
    rb = ConversationRingBuffer(maxlen=5)
    rb.push("hello", "hi there", 1, "edu")
    assert len(rb) == 1


@pytest.mark.unit
def test_eviction() -> None:
    """Pushing beyond maxlen evicts oldest entries."""
    rb = ConversationRingBuffer(maxlen=3)
    for i in range(5):
        rb.push(f"msg-{i}", f"resp-{i}", i, "edu")
    assert len(rb) == 3
    snap = rb.snapshot()
    assert snap[0].user_message == "msg-2"
    assert snap[-1].user_message == "msg-4"


@pytest.mark.unit
def test_snapshot_returns_frozen_copy() -> None:
    rb = ConversationRingBuffer(maxlen=5)
    rb.push("a", "b", 1, "edu")
    snap1 = rb.snapshot()
    rb.push("c", "d", 2, "edu")
    snap2 = rb.snapshot()
    assert len(snap1) == 1
    assert len(snap2) == 2


@pytest.mark.unit
def test_clear() -> None:
    rb = ConversationRingBuffer(maxlen=5)
    rb.push("a", "b", 1, "edu")
    rb.clear()
    assert len(rb) == 0
    assert rb.snapshot() == []


@pytest.mark.unit
def test_turn_record_fields() -> None:
    rb = ConversationRingBuffer(maxlen=5)
    rb.push("user msg", "llm resp", 42, "agriculture")
    rec = rb.snapshot()[0]
    assert isinstance(rec, TurnRecord)
    assert rec.user_message == "user msg"
    assert rec.llm_response == "llm resp"
    assert rec.turn_number == 42
    assert rec.domain_id == "agriculture"
    assert rec.timestamp > 0


@pytest.mark.unit
def test_maxlen_property() -> None:
    rb = ConversationRingBuffer(maxlen=10)
    assert rb.maxlen == 10


@pytest.mark.unit
def test_thread_safety() -> None:
    """Concurrent pushes should not corrupt the buffer."""
    rb = ConversationRingBuffer(maxlen=100)
    errors: list[Exception] = []

    def pusher(start: int) -> None:
        try:
            for i in range(50):
                rb.push(f"msg-{start}-{i}", f"resp-{start}-{i}", start + i, "edu")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=pusher, args=(t * 100,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(rb) == 100  # 4 * 50 = 200, but maxlen=100
    snap = rb.snapshot()
    assert len(snap) == 100


# ─────────────────────────────────────────────────────────────
# Hydrate — restore from verified transcript entries
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_hydrate_populates_buffer() -> None:
    rb = ConversationRingBuffer(maxlen=10)
    rb.hydrate([
        {"turn_number": 1, "user_message": "a", "llm_response": "b", "timestamp": 1.0, "domain_id": "d"},
        {"turn_number": 2, "user_message": "c", "llm_response": "d", "timestamp": 2.0, "domain_id": "d"},
    ])
    assert len(rb) == 2
    snap = rb.snapshot()
    assert snap[0].user_message == "a"
    assert snap[1].turn_number == 2


@pytest.mark.unit
def test_hydrate_clears_existing_data() -> None:
    rb = ConversationRingBuffer(maxlen=10)
    rb.push("old", "old-resp", 0, "d")
    rb.hydrate([
        {"turn_number": 1, "user_message": "new", "llm_response": "new-resp", "timestamp": 1.0, "domain_id": "d"},
    ])
    assert len(rb) == 1
    assert rb.snapshot()[0].user_message == "new"


@pytest.mark.unit
def test_hydrate_rejects_non_monotonic_turns() -> None:
    rb = ConversationRingBuffer(maxlen=10)
    with pytest.raises(ValueError, match="Non-monotonic"):
        rb.hydrate([
            {"turn_number": 3, "user_message": "a", "llm_response": "b", "timestamp": 1.0, "domain_id": "d"},
            {"turn_number": 2, "user_message": "c", "llm_response": "d", "timestamp": 2.0, "domain_id": "d"},
        ])


@pytest.mark.unit
def test_hydrate_rejects_duplicate_turn_numbers() -> None:
    rb = ConversationRingBuffer(maxlen=10)
    with pytest.raises(ValueError, match="Non-monotonic"):
        rb.hydrate([
            {"turn_number": 1, "user_message": "a", "llm_response": "b", "timestamp": 1.0, "domain_id": "d"},
            {"turn_number": 1, "user_message": "c", "llm_response": "d", "timestamp": 2.0, "domain_id": "d"},
        ])


@pytest.mark.unit
def test_hydrate_empty_list() -> None:
    rb = ConversationRingBuffer(maxlen=10)
    rb.push("a", "b", 1, "d")
    rb.hydrate([])
    assert len(rb) == 0


@pytest.mark.unit
def test_hydrate_respects_maxlen() -> None:
    """If more records than maxlen are hydrated, oldest are evicted."""
    rb = ConversationRingBuffer(maxlen=3)
    rb.hydrate([
        {"turn_number": i, "user_message": f"u{i}", "llm_response": f"r{i}", "timestamp": float(i), "domain_id": "d"}
        for i in range(1, 6)
    ])
    assert len(rb) == 3
    snap = rb.snapshot()
    assert snap[0].turn_number == 3
    assert snap[-1].turn_number == 5

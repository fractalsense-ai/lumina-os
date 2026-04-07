"""ring_buffer.py — Per-session conversation ring buffer.

Dashcam-style circular buffer of the last *N* turn-pairs (user message +
LLM response).  Ephemeral by design — dies with the session and is
**never** persisted.  Only crystallised when a black-box trigger fires.

Thread-safe (``threading.Lock``), following the ``alert_store.py``
pattern.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


DEFAULT_BUFFER_SIZE: int = 10


@dataclass
class TurnRecord:
    """One conversation exchange (user message + LLM response)."""

    timestamp: float
    user_message: str
    llm_response: str
    turn_number: int
    domain_id: str


class ConversationRingBuffer:
    """Bounded ring buffer of ``TurnRecord`` entries.

    Parameters
    ----------
    maxlen:
        Maximum number of turn-pairs retained.  Oldest entries are
        automatically evicted when the limit is reached.
    """

    def __init__(self, maxlen: int = DEFAULT_BUFFER_SIZE) -> None:
        from collections import deque

        self._buf: deque[TurnRecord] = deque(maxlen=max(maxlen, 1))
        self._lock = threading.Lock()

    # ── Mutators ──────────────────────────────────────────────

    def push(
        self,
        user_message: str,
        llm_response: str,
        turn_number: int,
        domain_id: str,
    ) -> None:
        """Record one exchange.  Automatically evicts the oldest if full."""
        record = TurnRecord(
            timestamp=time.time(),
            user_message=user_message,
            llm_response=llm_response,
            turn_number=turn_number,
            domain_id=domain_id,
        )
        with self._lock:
            self._buf.append(record)

    def clear(self) -> None:
        """Discard all buffered turns."""
        with self._lock:
            self._buf.clear()

    def hydrate(self, records: list[dict[str, Any]]) -> None:
        """Re-populate the buffer from verified transcript entries.

        Parameters
        ----------
        records:
            Dicts with keys ``turn_number``, ``user_message``,
            ``llm_response``, ``timestamp``, ``domain_id``.
        """
        with self._lock:
            self._buf.clear()
            for idx, r in enumerate(records):
                self._buf.append(
                    TurnRecord(
                        timestamp=float(r.get("timestamp", 0.0)),
                        user_message=str(r.get("user_message", "")),
                        llm_response=str(r.get("llm_response", "")),
                        turn_number=idx,
                        domain_id=str(r.get("domain_id", "")),
                    )
                )

    # ── Queries ───────────────────────────────────────────────

    def snapshot(self) -> list[TurnRecord]:
        """Return a frozen copy of the current buffer contents."""
        with self._lock:
            return list(self._buf)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)

    @property
    def maxlen(self) -> int:
        return self._buf.maxlen  # type: ignore[return-value]

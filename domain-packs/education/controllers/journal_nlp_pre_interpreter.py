"""Journal NLP pre-interpreter — entity hashing + SVA extraction.

Called from processing.py BEFORE the orchestrator is invoked.  Entity
names are discarded immediately after hashing; only stable opaque hashes
flow forward into the domain step and DB.

Privacy guarantee:
    ``entity_hash = "Entity_" + sha256((salt + entity_name.lower()).encode()).hexdigest()[:4].upper()``

    Without the device-local salt (which is never stored server-side) the
    4-char hex suffix (65 536 possible values) cannot be reversed.  The
    full SHA-256 digest is discarded after slicing.

Heuristic SVA extraction (no LLM):
    salience_direct  — proxy: how much did the writer write?  word_count/50,
                       capped at 1.0.
    valence_direct   — positive/negative keyword scoring, normalised to [-1, 1].
    arousal_direct   — caps ratio + extreme punctuation density +
                       sentence fragmentation.

These heuristic values augment (not replace) the evidence-based SVA that
the affect_monitor already computes from structured turn fields.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any


# ─────────────────────────────────────────────────────────────
# Keyword lexicons
# ─────────────────────────────────────────────────────────────

_POSITIVE_WORDS: frozenset[str] = frozenset({
    "happy", "great", "good", "love", "wonderful", "excited", "joyful",
    "thankful", "grateful", "fantastic", "amazing", "awesome", "proud",
    "confident", "hopeful", "calm", "peaceful", "better", "pleased",
    "glad", "relieved", "appreciated", "supported", "safe",
})

_NEGATIVE_WORDS: frozenset[str] = frozenset({
    "sad", "upset", "angry", "anxious", "worried", "scared", "afraid",
    "hate", "terrible", "horrible", "awful", "frustrated", "stressed",
    "overwhelmed", "hopeless", "lost", "alone", "ignored", "hurt",
    "unfair", "wrong", "bad", "mean", "cruel", "harsh", "difficult",
    "hard", "struggle", "struggling", "can't", "cannot", "unable",
    "failing", "failed", "stupid", "dumb", "worthless",
})

# Sentence-ending patterns
_SENTENCE_END_RE = re.compile(r"[.!?]+")
# Extreme punctuation
_EXTREME_PUNCT_RE = re.compile(r"([!?])\1{1,}")


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────


def extract_journal_evidence(
    input_text: str,
    entity_salt: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Extract privacy-preserving journal evidence from ``input_text``.

    Args:
        input_text:    The raw journal turn text.
        entity_salt:   Device-local hex salt (sent by client, never stored).
                       Pass an empty string to skip entity hashing.
        params:        Reserved for future threshold overrides.

    Returns:
        A dict with keys:
            entity_mentions  — ``{entity_hash: {valence_delta, arousal_delta}}``
            sva_direct       — ``{salience, valence, arousal}``  (heuristic)
            entity_count     — number of distinct entities found
    """
    entity_mentions: dict[str, dict[str, float]] = {}
    entity_count = 0

    # ── Named entity extraction + hashing ───────────────────
    if entity_salt:
        entity_texts: list[str] = _extract_entity_texts(input_text)
        for raw_name in entity_texts:
            h = _hash_entity(raw_name, entity_salt)
            # Per-entity affective signal: weight the surrounding-sentence
            # valence to build an entity-specific deviation hint.
            nearby_valence = _local_sentence_valence(input_text, raw_name)
            nearby_arousal = _local_sentence_arousal(input_text, raw_name)
            # Accumulate (multiple mentions of same hash → average later)
            if h not in entity_mentions:
                entity_mentions[h] = {"valence_delta": nearby_valence, "arousal_delta": nearby_arousal, "_count": 1}
            else:
                prev = entity_mentions[h]
                n = prev["_count"] + 1
                prev["valence_delta"] = (prev["valence_delta"] * (n - 1) + nearby_valence) / n
                prev["arousal_delta"] = (prev["arousal_delta"] * (n - 1) + nearby_arousal) / n
                prev["_count"] = n
        entity_count = len(entity_mentions)
        # Remove internal _count key
        for h in entity_mentions:
            entity_mentions[h].pop("_count", None)

    # ── Heuristic SVA extraction ──────────────────────────────
    sva = _heuristic_sva(input_text)

    return {
        "entity_mentions": entity_mentions,
        "sva_direct": sva,
        "entity_count": entity_count,
    }


# ─────────────────────────────────────────────────────────────
# Entity extraction — spaCy with regex fallback
# ─────────────────────────────────────────────────────────────


def _extract_entity_texts(text: str) -> list[str]:
    """Return raw entity name strings from *text*.

    Tries spaCy (PERSON + ORG spans) then falls back to a capitalised-word
    heuristic so the function works even without a loaded spaCy model.
    """
    try:
        from lumina.core.nlp import get_nlp
        nlp = get_nlp()
        if nlp is not None:
            doc = nlp(text)
            return [ent.text.strip() for ent in doc.ents if ent.label_ in ("PERSON", "ORG") and ent.text.strip()]
    except Exception:
        pass

    # Fallback: find sequences of 2–4 capitalised words (e.g. "Mr Davis")
    # that are not sentence-initial (crude but privacy-safe for tests).
    pattern = re.compile(
        r"(?<![.!?\n])\b([A-Z][a-z]{1,15}(?:\s+[A-Z][a-z]{1,15}){1,3})\b"
    )
    return [m.group(1).strip() for m in pattern.finditer(text)]


# ─────────────────────────────────────────────────────────────
# Entity hashing
# ─────────────────────────────────────────────────────────────


def _hash_entity(raw_name: str, salt: str) -> str:
    """Return a stable, unrecoverable hash for *raw_name* given *salt*.

    Format: ``Entity_XXXX``  where XXXX is 4 uppercase hex characters
    derived from the first 2 bytes of SHA-256(salt + name.lower()).
    """
    payload = (salt + raw_name.strip().lower()).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return "Entity_" + digest[:4].upper()


# ─────────────────────────────────────────────────────────────
# Heuristic SVA
# ─────────────────────────────────────────────────────────────


def _heuristic_sva(text: str) -> dict[str, float]:
    """Compute heuristic Salience/Valence/Arousal from raw journal text."""
    words = text.split()
    word_count = len(words)

    # Salience — proxy: writing volume (engagement = they had something to say)
    salience = min(word_count / 50.0, 1.0)

    # Valence — keyword counting
    lower_words = {w.strip(".,!?\"'").lower() for w in words}
    pos_hits = len(lower_words & _POSITIVE_WORDS)
    neg_hits = len(lower_words & _NEGATIVE_WORDS)
    total_hits = pos_hits + neg_hits
    if total_hits == 0:
        valence = 0.0
    else:
        valence = (pos_hits - neg_hits) / total_hits  # range [-1, 1]
    valence = max(-1.0, min(1.0, valence))

    # Arousal — caps ratio + extreme punctuation + fragmentation
    caps_chars = sum(1 for c in text if c.isupper())
    alpha_chars = sum(1 for c in text if c.isalpha())
    caps_ratio = caps_chars / max(alpha_chars, 1)

    extreme_count = len(_EXTREME_PUNCT_RE.findall(text))
    punct_density = min(extreme_count / max(word_count, 1) * 5.0, 1.0)

    # Short sentences → fragmentation (agitated short bursts)
    sentences = [s for s in _SENTENCE_END_RE.split(text) if s.strip()]
    if sentences:
        avg_words_per_sentence = word_count / len(sentences)
        fragmentation = max(0.0, 1.0 - avg_words_per_sentence / 20.0)
    else:
        fragmentation = 0.0

    arousal = min(caps_ratio * 0.4 + punct_density * 0.3 + fragmentation * 0.3, 1.0)

    return {
        "salience": round(salience, 6),
        "valence": round(valence, 6),
        "arousal": round(arousal, 6),
    }


def _local_sentence_valence(text: str, entity_name: str) -> float:
    """Return valence heuristic for the sentence(s) containing *entity_name*."""
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", text) if s.strip()]
    relevant = [s for s in sentences if entity_name.split()[0] in s]
    if not relevant:
        return 0.0
    combined = " ".join(relevant)
    sva = _heuristic_sva(combined)
    return sva["valence"]


def _local_sentence_arousal(text: str, entity_name: str) -> float:
    """Return arousal heuristic for the sentence(s) containing *entity_name*."""
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", text) if s.strip()]
    relevant = [s for s in sentences if entity_name.split()[0] in s]
    if not relevant:
        return 0.0
    combined = " ".join(relevant)
    sva = _heuristic_sva(combined)
    return sva["arousal"]

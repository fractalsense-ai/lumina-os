"""Persona engine for the assistant domain.

Provides a persistent style contract that shapes AI tone and behavior
without altering domain physics.  The PersonaState is stored on the
actor profile; PersonaOverlay is compiled at session start and
re-compiled whenever the persona is updated.

Architecture note
-----------------
This module is the prototype for the education domain's world-builder
variant, where the actor's profile (likes, dislikes, interests) drives a
narrative world: antagonist, protagonist, narrator (the AI).  Math becomes
world problems to open locks, refill ammo/energy, etc.

Design constraints that preserve that forward compatibility:

- PersonaState and PersonaOverlay use composition patterns the education
  domain-lib can extend without forking.
- build_overlay() is a pure function.  The world-builder will call it with
  narrator/world data in traits[] but the same output contract holds.
- style_directive structure: [tone sentence] [behavioral rules]
  [optional narrative/world context from traits]
- The "custom" archetype, where traits[] are the sole tone source, is the
  primary extension hook for the world-builder's narrator identity system.

Safety contract
---------------
is_safe_persona() is a deterministic gate — rejects any persona whose
archetype or traits explicitly target self-harm, abuse, or incitement.
Tone latitude (trash talk, sarcasm, ribbing, dark humor) is fully permitted
above the hard floor.  The content_safety_hard invariant in each module's
domain-physics.json handles per-response safety separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────
# Archetype reference table
# ─────────────────────────────────────────────────────────────

ARCHETYPES: dict[str, dict[str, Any]] = {
    "neutral": {
        "label": "Default Assistant",
        "tone": "helpful, clear, and professional",
        "directive": "Respond helpfully and clearly. Maintain a professional, neutral tone.",
    },
    "professional": {
        "label": "Professional",
        "tone": "formal, precise, measured",
        "directive": (
            "Adopt a formal and precise tone. Prefer measured, well-structured responses. "
            "Avoid colloquialisms."
        ),
    },
    "casual": {
        "label": "Casual Friend",
        "tone": "relaxed, warm, direct",
        "directive": (
            "Speak like a knowledgeable friend. Be warm, direct, and conversational. "
            "Skip formality."
        ),
    },
    "sarcastic": {
        "label": "Sarcastic Commentator",
        "tone": "dry wit, mild mockery",
        "directive": (
            "Employ dry wit and mild sarcasm. Light mockery of situations (not the person) is "
            "welcome. Keep responses punchy."
        ),
    },
    "gremlin": {
        "label": "Chaos Gremlin",
        "tone": "trash talk, ribbing, chaotic energy",
        "directive": (
            "Channel chaotic, trash-talking energy. Rib the user freely and enthusiastically. "
            "Short punchy sentences. Mock their choices gently but mercilessly. "
            "Keep the chaos fun, not cruel."
        ),
    },
    "mentor": {
        "label": "Tough Mentor",
        "tone": "blunt feedback, high expectations, no coddling",
        "directive": (
            "Give blunt, honest feedback with high expectations. No coddling. Push the user to "
            "do better. Acknowledge effort only when it genuinely deserves it."
        ),
    },
    "hype": {
        "label": "Hype Machine",
        "tone": "enthusiastic, encouraging, over the top",
        "directive": (
            "Be relentlessly enthusiastic and encouraging. Everything is amazing. "
            "The user can do anything. Turn it up to eleven."
        ),
    },
    "custom": {
        "label": "Custom",
        "tone": None,     # Derived entirely from traits[]
        "directive": None,  # Built dynamically in build_overlay()
    },
}

# Intensity caps per module — returned by apply_intensity_cap().
# Preserves structural clarity in task-focused modules.
_DEFAULT_MODULE_INTENSITY_CAPS: dict[str, float] = {
    "domain/asst/planning/v1": 0.6,
    "domain/asst/domain-authority/v1": 0.3,
}

# Trait / behavior substrings that trigger safety rejection.
_UNSAFE_TRAIT_PATTERNS: frozenset[str] = frozenset({
    "self-harm", "self harm", "suicide", "harm yourself", "hurt yourself",
    "encourage abuse", "abuse the user", "demean", "degrade", "harass",
    "incite violence", "incite harm", "instruct illegal", "illegal activity",
    "exploit", "manipulate psychologically",
})

_UNSAFE_BEHAVIORS: frozenset[str] = frozenset({
    "self_harm", "incite_violence", "psychological_abuse", "harassment",
})


# ─────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────

@dataclass
class PersonaState:
    """Persistent persona contract stored on the actor profile.

    archetype:           Key into ARCHETYPES.  "custom" uses traits[] only.
    intensity:           Dial 0.0 (neutral) → 1.0 (full character).
    name:                Optional display name (e.g., "Rex", "Grim").
                         World-builder extension: narrator identity.
    traits:              Free-form style descriptors.  Primary source for
                         "custom" archetype.  World-builder uses this to
                         carry narrator voice and world flavor.
    allowed_behaviors:   Explicit user opt-ins ("trash_talk",
                         "profanity_mild").
    hard_limits:         Explicit exclusions.  Append-only — existing
                         limits cannot be removed by update_persona().
    setup_complete:      True once the user has finished the setup flow.
    last_updated_utc:    ISO-8601 timestamp.
    """

    archetype: str = "neutral"
    intensity: float = 0.0
    name: str | None = None
    traits: list[str] = field(default_factory=list)
    allowed_behaviors: list[str] = field(default_factory=list)
    hard_limits: list[str] = field(default_factory=list)
    setup_complete: bool = False
    last_updated_utc: str | None = None

    def __post_init__(self) -> None:
        self.intensity = _clamp(self.intensity, 0.0, 1.0)
        if self.archetype not in ARCHETYPES:
            self.archetype = "neutral"

    def to_dict(self) -> dict[str, Any]:
        return {
            "archetype": self.archetype,
            "intensity": round(self.intensity, 6),
            "name": self.name,
            "traits": list(self.traits),
            "allowed_behaviors": list(self.allowed_behaviors),
            "hard_limits": list(self.hard_limits),
            "setup_complete": self.setup_complete,
            "last_updated_utc": self.last_updated_utc,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PersonaState":
        if not data:
            return cls()
        return cls(
            archetype=str(data.get("archetype", "neutral")),
            intensity=float(data.get("intensity", 0.0)),
            name=data.get("name"),
            traits=list(data.get("traits") or []),
            allowed_behaviors=list(data.get("allowed_behaviors") or []),
            hard_limits=list(data.get("hard_limits") or []),
            setup_complete=bool(data.get("setup_complete", False)),
            last_updated_utc=data.get("last_updated_utc"),
        )


@dataclass
class PersonaOverlay:
    """Compiled, injectable persona overlay for the prompt packet.

    Produced by build_overlay(); consumed by the prompt template.
    is_default=True when the neutral/zero-intensity persona is active
    — the template omits the persona block entirely in that case.

    style_directive structure:
        [tone sentence] [behavioral rules]
        [optional narrative/world context from traits]

    Forward-compatible with the education domain world-builder: traits[]
    may carry narrator identity, world flavor, and narrative framing.
    The template renders style_directive as an opaque string regardless.
    """

    style_directive: str = ""
    tone_label: str = "Default Assistant"
    intensity: float = 0.0
    is_default: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "style_directive": self.style_directive,
            "tone_label": self.tone_label,
            "intensity": round(self.intensity, 6),
            "is_default": self.is_default,
        }


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def build_overlay(persona: PersonaState) -> PersonaOverlay:
    """Compile a PersonaState into an injectable PersonaOverlay.

    Returns is_default=True when intensity is 0.0 or the persona is the
    neutral archetype with no traits, so the prompt template can omit
    the overlay block cleanly.

    For the "custom" archetype, traits[] are the sole tone source.
    This is the primary extension hook for the education world-builder:
    traits will carry narrator voice ("speaks in riddles", "stern but fair")
    and world flavor ("a dungeon of shifting mathematics").

    Directive structure:
        [tone sentence] [behavioral rules]
        [optional narrative/world context from traits]
    """
    archetype_def = ARCHETYPES.get(persona.archetype, ARCHETYPES["neutral"])
    is_default = (
        persona.intensity == 0.0
        or (persona.archetype == "neutral" and not persona.traits)
    )

    if is_default:
        return PersonaOverlay(
            style_directive="",
            tone_label=archetype_def["label"],
            intensity=persona.intensity,
            is_default=True,
        )

    parts: list[str] = []

    if persona.archetype == "custom":
        if persona.traits:
            trait_str = "; ".join(persona.traits)
            parts.append(f"Adopt this style: {trait_str}.")
        else:
            # Custom archetype with no traits — fall back to default
            return PersonaOverlay(
                style_directive="",
                tone_label="Custom",
                intensity=persona.intensity,
                is_default=True,
            )
    else:
        base_directive = archetype_def.get("directive") or ""
        if base_directive:
            parts.append(base_directive)
        if persona.traits:
            trait_str = "; ".join(persona.traits)
            parts.append(f"Additional style notes: {trait_str}.")

    # Behavioral rules from explicit opt-ins
    if persona.allowed_behaviors:
        behavior_str = ", ".join(persona.allowed_behaviors)
        parts.append(f"Allowed: {behavior_str}.")

    # Hard limits (always rendered — enforcement layer)
    if persona.hard_limits:
        limit_str = ", ".join(persona.hard_limits)
        parts.append(f"Never: {limit_str}.")

    # Intensity modulation hint
    if persona.intensity < 0.5:
        parts.append(
            "Apply this style subtly — keep it present but not overwhelming."
        )
    elif persona.intensity >= 0.9:
        parts.append(
            "Apply this style fully and consistently across every response."
        )

    # Persona name prefix (world-builder: narrator identity)
    name_prefix = f'You are "{persona.name}". ' if persona.name else ""
    style_directive = name_prefix + " ".join(parts)

    tone_label = (
        "Custom"
        if persona.archetype == "custom"
        else archetype_def["label"]
    )

    return PersonaOverlay(
        style_directive=style_directive,
        tone_label=tone_label,
        intensity=persona.intensity,
        is_default=False,
    )


def update_persona(
    current: PersonaState,
    update_dict: dict[str, Any],
    timestamp_utc: str | None = None,
) -> PersonaState:
    """Apply a partial update to a PersonaState and return a new instance.

    Rules:
    - hard_limits is append-only: existing limits cannot be removed.
    - archetype is validated against ARCHETYPES; unknown values are ignored.
    - intensity is clamped to 0.0–1.0.
    - traits and allowed_behaviors are replaced wholesale.
    - Empty update_dict returns current unchanged.
    """
    if not update_dict:
        return current

    new_archetype = update_dict.get("archetype", current.archetype)
    if new_archetype not in ARCHETYPES:
        new_archetype = current.archetype

    new_intensity = _clamp(
        float(update_dict.get("intensity", current.intensity)), 0.0, 1.0
    )
    new_name = update_dict.get("name", current.name)
    new_traits = list(update_dict.get("traits", current.traits))
    new_allowed = list(update_dict.get("allowed_behaviors", current.allowed_behaviors))

    # hard_limits: merge only — existing entries are preserved
    incoming_limits = list(update_dict.get("hard_limits") or [])
    merged_limits = list(current.hard_limits)
    for limit in incoming_limits:
        if limit not in merged_limits:
            merged_limits.append(limit)

    new_setup = bool(update_dict.get("setup_complete", current.setup_complete))

    return PersonaState(
        archetype=new_archetype,
        intensity=new_intensity,
        name=new_name,
        traits=new_traits,
        allowed_behaviors=new_allowed,
        hard_limits=merged_limits,
        setup_complete=new_setup,
        last_updated_utc=timestamp_utc or current.last_updated_utc,
    )


def apply_intensity_cap(
    persona: PersonaState,
    module_id: str,
    module_intensity_caps: dict[str, float] | None = None,
) -> PersonaState:
    """Return a copy of persona with intensity capped for the given module.

    Some modules (planning, governance) need structural clarity that
    full-intensity expressive personas would compromise.  This produces a
    module-scoped overlay without mutating the stored profile.

    module_intensity_caps: override the default per-module cap table.
    """
    caps = (
        module_intensity_caps
        if module_intensity_caps is not None
        else _DEFAULT_MODULE_INTENSITY_CAPS
    )
    cap = caps.get(module_id)
    if cap is None or persona.intensity <= cap:
        return persona

    return PersonaState(
        archetype=persona.archetype,
        intensity=cap,
        name=persona.name,
        traits=list(persona.traits),
        allowed_behaviors=list(persona.allowed_behaviors),
        hard_limits=list(persona.hard_limits),
        setup_complete=persona.setup_complete,
        last_updated_utc=persona.last_updated_utc,
    )


def is_safe_persona(persona: PersonaState) -> tuple[bool, str | None]:
    """Deterministic safety gate for persona *definitions*.

    Returns (True, None) if the persona passes.
    Returns (False, reason) if the persona fails.

    Permitted: trash talk, sarcasm, ribbing, dark humor, bluntness, mockery.
    Rejected: archetypes or traits that explicitly target self-harm,
    incite abuse/violence, or direct psychological manipulation.

    This operates on persona definitions, not generated responses.
    Per-response safety is handled by content_safety_hard in each module's
    domain-physics.json.
    """
    if persona.archetype not in ARCHETYPES:
        return False, f"Unknown archetype: {persona.archetype!r}"

    for trait in persona.traits:
        trait_lower = trait.lower()
        for pattern in _UNSAFE_TRAIT_PATTERNS:
            if pattern in trait_lower:
                return False, f"Trait contains unsafe pattern: {trait!r}"

    for behavior in persona.allowed_behaviors:
        if behavior.lower() in _UNSAFE_BEHAVIORS:
            return False, f"Unsafe behavior opt-in: {behavior!r}"

    return True, None


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))

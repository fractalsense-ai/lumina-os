"""Unit tests for lumina.signals.templates."""

from __future__ import annotations

from lumina.signals import render_advisory_message


def test_default_dc_drift_negative_template_substitutes_label():
    msg = render_advisory_message("valence", "dc_drift", "negative")
    assert "valence" in msg
    assert "downward" in msg


def test_default_dc_drift_positive_template():
    msg = render_advisory_message("arousal", "dc_drift", "positive")
    assert "arousal" in msg
    assert "upward" in msg


def test_default_circaseptan_wildcard_direction():
    msg = render_advisory_message("salience", "circaseptan", "*")
    assert "weekly" in msg.lower()
    assert "salience" in msg


def test_default_ultradian_wildcard():
    msg = render_advisory_message("valence", "ultradian", "positive")
    assert "valence" in msg
    assert "multi-day" in msg.lower()


def test_unknown_band_gets_generic_fallback():
    msg = render_advisory_message("soil_pH", "tidal", "positive")
    assert "soil_pH" in msg
    assert "tidal" in msg


def test_signal_overrides_take_precedence_over_defaults():
    overrides = {"dc_drift,negative": "Mood baseline trending down — gentle check-in suggested."}
    msg = render_advisory_message("valence", "dc_drift", "negative",
                                  signal_overrides=overrides)
    assert msg == "Mood baseline trending down — gentle check-in suggested."


def test_signal_overrides_wildcard_direction():
    overrides = {"circaseptan,*": "{label} weekly cycle has shifted."}
    msg = render_advisory_message("soil_moisture", "circaseptan", "negative",
                                  signal_overrides=overrides)
    assert msg == "soil_moisture weekly cycle has shifted."


def test_exact_override_wins_over_wildcard_override():
    overrides = {
        "circaseptan,*": "wildcard wins",
        "circaseptan,positive": "exact wins",
    }
    msg = render_advisory_message("x", "circaseptan", "positive",
                                  signal_overrides=overrides)
    assert msg == "exact wins"


def test_malformed_override_keys_ignored():
    overrides = {"no_comma_here": "ignored", "ok,positive": "{label} ok"}
    msg = render_advisory_message("x", "ok", "positive",
                                  signal_overrides=overrides)
    assert msg == "x ok"


def test_override_with_unknown_placeholder_returns_raw_template():
    overrides = {"x,positive": "{not_a_field} drifted"}
    msg = render_advisory_message("foo", "x", "positive",
                                  signal_overrides=overrides)
    assert "{not_a_field}" in msg


def test_empty_label_falls_back_to_default_phrase():
    msg = render_advisory_message("", "dc_drift", "positive")
    assert "this signal" in msg.lower()

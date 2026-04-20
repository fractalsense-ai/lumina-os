"""Assistant domain tool adapter stubs.

Contains lightweight tool implementations for the assistant domain.
Each tool follows the standard adapter signature and returns structured
results.  These are stubs for v1 — real integrations would call
external APIs.
"""
from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────
# Weather lookup — stub
# ─────────────────────────────────────────────────────────────


def weather_lookup_tool(payload: dict[str, Any]) -> dict[str, Any]:
    location = payload.get("location", "").strip()
    if not location:
        return {"ok": False, "error": "location is required"}
    forecast_days = int(payload.get("forecast_days", 1))
    if forecast_days < 1 or forecast_days > 7:
        forecast_days = 1
    return {
        "ok": True,
        "location": location,
        "temperature_c": 22,
        "conditions": "partly cloudy",
        "humidity_pct": 55,
        "wind_kph": 12,
        "forecast": [
            {"day": i + 1, "high_c": 24, "low_c": 16, "conditions": "fair"}
            for i in range(forecast_days)
        ],
    }


# ─────────────────────────────────────────────────────────────
# Calendar query — stub
# ─────────────────────────────────────────────────────────────


def calendar_query_tool(payload: dict[str, Any]) -> dict[str, Any]:
    date_start = payload.get("date_start", "")
    date_end = payload.get("date_end", "")
    if not date_start:
        return {"ok": False, "error": "date_start is required"}
    return {
        "ok": True,
        "events": [],
        "date_range": {"start": date_start, "end": date_end or date_start},
    }


# ─────────────────────────────────────────────────────────────
# Calendar write — stub
# ─────────────────────────────────────────────────────────────


def calendar_write_tool(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action", "").strip()
    if action not in ("create", "update", "delete"):
        return {"ok": False, "error": "action must be create, update, or delete"}
    event_title = payload.get("event_title", "").strip()
    if action == "create" and not event_title:
        return {"ok": False, "error": "event_title is required for create"}
    return {
        "ok": True,
        "action": action,
        "confirmation": f"Calendar event {action}d successfully (stub).",
    }


# ─────────────────────────────────────────────────────────────
# Web search — stub
# ─────────────────────────────────────────────────────────────


def web_search_tool(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query", "").strip()
    if not query:
        return {"ok": False, "error": "query is required"}
    max_results = min(int(payload.get("max_results", 5)), 10)
    return {
        "ok": True,
        "results": [
            {
                "title": f"Result {i + 1} for '{query}'",
                "snippet": f"Stub snippet for result {i + 1}.",
                "url": f"https://example.com/result-{i + 1}",
                "relevance": round(1.0 - i * 0.1, 2),
            }
            for i in range(max_results)
        ],
    }


# ─────────────────────────────────────────────────────────────
# Planning tools — stub
# ─────────────────────────────────────────────────────────────


def planning_create_tool(payload: dict[str, Any]) -> dict[str, Any]:
    title = payload.get("title", "").strip()
    if not title:
        return {"ok": False, "error": "title is required"}
    return {
        "ok": True,
        "plan_id": "plan-stub-001",
        "title": title,
        "items": payload.get("items", []),
        "confirmation": "Plan created (stub).",
    }


def planning_update_tool(payload: dict[str, Any]) -> dict[str, Any]:
    plan_id = payload.get("plan_id", "").strip()
    if not plan_id:
        return {"ok": False, "error": "plan_id is required"}
    return {
        "ok": True,
        "plan_id": plan_id,
        "confirmation": "Plan updated (stub).",
    }


def planning_list_tool(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "plans": [],
    }

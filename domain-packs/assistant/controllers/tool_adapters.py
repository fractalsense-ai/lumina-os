"""Assistant domain tool adapters.

Contains tool implementations for the assistant domain.
Each tool follows the standard adapter signature: ``payload: dict`` → ``dict``.
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

import httpx

_OWM_BASE = "https://api.openweathermap.org/data/2.5"
_OWM_FORECAST_MAX_DAYS = 5  # free-tier /forecast gives 5 days of 3-hourly data


# ─────────────────────────────────────────────────────────────
# Weather lookup — OpenWeatherMap
# ─────────────────────────────────────────────────────────────


def weather_lookup_tool(payload: dict[str, Any]) -> dict[str, Any]:
    location = payload.get("location", "").strip()
    if not location:
        return {"ok": False, "error": "location is required"}

    forecast_days = int(payload.get("forecast_days", 1))
    if forecast_days < 1 or forecast_days > _OWM_FORECAST_MAX_DAYS:
        forecast_days = 1

    api_key = os.getenv("OPENWEATHERMAP_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "error": "OPENWEATHERMAP_API_KEY not configured"}

    params: dict[str, Any] = {"q": location, "appid": api_key, "units": "metric"}

    try:
        resp = httpx.get(f"{_OWM_BASE}/weather", params=params, timeout=8)
        if resp.status_code == 401:
            return {"ok": False, "error": "invalid API key"}
        if resp.status_code == 404:
            return {"ok": False, "error": f"location not found: {location}"}
        resp.raise_for_status()
        current = resp.json()

        resp_fc = httpx.get(f"{_OWM_BASE}/forecast", params=params, timeout=8)
        resp_fc.raise_for_status()
        fc_data = resp_fc.json()
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"weather service unavailable: {exc}"}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": f"weather service error: {exc.response.status_code}"}

    temperature_c = round(current["main"]["temp"], 1)
    conditions = current["weather"][0]["description"]
    humidity_pct = current["main"]["humidity"]
    wind_kph = round(current["wind"]["speed"] * 3.6, 1)
    resolved_location = current.get("name", location)

    day_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in fc_data.get("list", []):
        day = entry["dt_txt"][:10]
        day_buckets[day].append(entry)

    forecast = []
    for i, (_, entries) in enumerate(list(day_buckets.items())[:forecast_days], start=1):
        high_c = round(max(e["main"]["temp_max"] for e in entries), 1)
        low_c = round(min(e["main"]["temp_min"] for e in entries), 1)
        midday = next((e for e in entries if "12:00:00" in e["dt_txt"]), entries[0])
        forecast.append({
            "day": i,
            "high_c": high_c,
            "low_c": low_c,
            "conditions": midday["weather"][0]["description"],
        })

    return {
        "ok": True,
        "location": resolved_location,
        "temperature_c": temperature_c,
        "conditions": conditions,
        "humidity_pct": humidity_pct,
        "wind_kph": wind_kph,
        "forecast": forecast,
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

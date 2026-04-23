"""Assistant domain tool adapters.

Contains tool implementations for the assistant domain.
Each tool follows the standard adapter signature: ``payload: dict`` → ``dict``.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

_OWM_BASE = "https://api.openweathermap.org/data/2.5"
_OWM_FORECAST_MAX_DAYS = 5  # free-tier /forecast gives 5 days of 3-hourly data
_TAVILY_BASE = "https://api.tavily.com"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CALDAV_DEFAULT_URL = "https://apidata.googleusercontent.com/caldav/v2/primary/"


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
# Calendar query — Google CalDAV via OAuth 2.0 refresh token
# ─────────────────────────────────────────────────────────────


def calendar_query_tool(payload: dict[str, Any]) -> dict[str, Any]:
    import caldav  # runtime import — caldav must be installed (see requirements.txt)

    date_start = (payload.get("date_start") or "").strip()
    if not date_start:
        return {"ok": False, "error": "date_start is required"}
    date_end = (payload.get("date_end") or "").strip() or date_start

    client_id = os.getenv("GOOGLE_CALENDAR_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "").strip()
    if not all([client_id, client_secret, refresh_token]):
        return {"ok": False, "error": "calendar credentials not configured"}

    caldav_url = os.getenv("GOOGLE_CALENDAR_CALDAV_URL", _CALDAV_DEFAULT_URL).strip()

    # ── Exchange refresh token for short-lived access token ────────────────
    try:
        token_resp = httpx.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"token exchange failed: {exc}"}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": f"token exchange error: {exc.response.status_code}"}

    # ── Fetch events via CalDAV ──────────────────────────────────────────
    try:
        client = caldav.DAVClient(
            url=caldav_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        calendar = client.calendar(url=caldav_url)
        start_dt = datetime.fromisoformat(date_start.replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(date_end.replace("Z", "+00:00"))
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        results = calendar.date_search(start=start_dt, end=end_dt, expand=True)
    except Exception as exc:
        return {"ok": False, "error": f"calendar query failed: {exc}"}

    events: list[dict[str, Any]] = []
    for event in results:
        try:
            vevent = event.vobject_instance.vevent
            uid = str(vevent.uid.value) if hasattr(vevent, "uid") else ""
            title = str(vevent.summary.value) if hasattr(vevent, "summary") else "(no title)"
            start_val = vevent.dtstart.value
            try:
                end_val = vevent.dtend.value
            except AttributeError:
                end_val = start_val
            events.append({
                "uid": uid,
                "title": title,
                "start": start_val.isoformat() if hasattr(start_val, "isoformat") else str(start_val),
                "end": end_val.isoformat() if hasattr(end_val, "isoformat") else str(end_val),
            })
        except Exception:
            continue

    return {
        "ok": True,
        "events": events,
        "date_range": {"start": date_start, "end": date_end},
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
# Web search — Tavily
# ─────────────────────────────────────────────────────────────


def web_search_tool(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query", "").strip()
    if not query:
        return {"ok": False, "error": "query is required"}
    max_results = min(int(payload.get("max_results", 5)), 10)

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "error": "TAVILY_API_KEY not configured"}

    try:
        resp = httpx.post(
            f"{_TAVILY_BASE}/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": True,
            },
            timeout=10,
        )
        if resp.status_code == 401:
            return {"ok": False, "error": "invalid API key"}
        resp.raise_for_status()
        data = resp.json()
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"search service unavailable: {exc}"}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": f"search service error: {exc.response.status_code}"}

    results = [
        {
            "title": r.get("title", ""),
            "snippet": r.get("content", ""),
            "url": r.get("url", ""),
            "relevance": round(float(r.get("score", 0.0)), 4),
        }
        for r in data.get("results", [])
    ]

    return {
        "ok": True,
        "query": query,
        "results": results,
        "answer": data.get("answer", ""),
    }


# ─────────────────────────────────────────────────────────────
# Planning tools — stub
# ─────────────────────────────────────────────────────────────


def planning_create_tool(payload: dict[str, Any]) -> dict[str, Any]:
    goal = payload.get("goal", "").strip()
    if not goal:
        return {"ok": False, "error": "goal is required"}

    constraints = payload.get("constraints", [])
    if not isinstance(constraints, list):
        constraints = []
    horizon_days = int(payload.get("horizon_days", 3))
    tool_results: dict[str, Any] = payload.get("tool_results") or {}
    if not isinstance(tool_results, dict):
        tool_results = {}
    sources = list(tool_results.keys())

    return {
        "ok": True,
        "brief": {
            "goal": goal,
            "constraints": constraints,
            "horizon_days": horizon_days,
            "sources": sources,
            "status": "ready_for_synthesis",
        },
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

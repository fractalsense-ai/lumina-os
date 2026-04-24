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

    # OWM accepts "City,CountryCode" but not "City, ST" (US state abbreviation).
    # Normalise "City, ST" → "City,US" so OWM resolves US cities correctly.
    _US_STATE_RE = __import__("re").compile(
        r"^(.+?),\s*([A-Z]{2})\s*$"
    )
    _m = _US_STATE_RE.match(location)
    owm_query = f"{_m.group(1)},US" if _m else location

    params: dict[str, Any] = {"q": owm_query, "appid": api_key, "units": "metric"}

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


# ─────────────────────────────────────────────────────────────
# Trip planning tools
#
# All six tools below are stubs.  The response shapes mirror the
# expected real-API contracts so that filling them in is a drop-in.
# Env vars document which credentials each tool will need.
#
# APIs targeted (integration deferred):
#   flight_search  → Amadeus Self-Service  (AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET)
#   flight_status  → AeroDataBox           (AERODATABOX_API_KEY)
#   hotel_search   → Expedia Rapid API     (EXPEDIA_RAPID_API_KEY)
#   poi_search     → Trueway Places        (TRUEWAY_API_KEY)
#   routing        → Trueway Routing       (TRUEWAY_API_KEY)
#   restaurant_search → Search Restaurant API (RESTAURANT_SEARCH_API_KEY)
# ─────────────────────────────────────────────────────────────

_STUB_NOTE = "API integration pending — stub response"


def flight_search_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """Search for available flights between origin and destination.

    Expected env vars (not yet wired): AMADEUS_CLIENT_ID, AMADEUS_CLIENT_SECRET.
    """
    origin      = (payload.get("origin") or "").strip()
    destination = (payload.get("destination") or "").strip()
    date_start  = (payload.get("date_start") or "").strip()
    date_end    = (payload.get("date_end") or "").strip()
    party_size  = int(payload.get("party_size") or 1)

    if not origin:
        return {"ok": False, "error": "origin is required"}
    if not destination:
        return {"ok": False, "error": "destination is required"}
    if not date_start:
        return {"ok": False, "error": "date_start is required"}

    return {
        "ok": True,
        "stub": True,
        "note": _STUB_NOTE,
        "origin": origin,
        "destination": destination,
        "date_start": date_start,
        "date_end": date_end or None,
        "party_size": party_size,
        "flights": [
            {
                "flight_id": "STUB-001",
                "carrier": "Stub Airways",
                "departs": f"{date_start}T08:00:00",
                "arrives": f"{date_start}T18:00:00",
                "stops": 1,
                "price_usd_per_person": 0,
                "total_price_usd": 0,
            }
        ],
    }


def flight_status_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """Retrieve real-time flight status and airport data.

    Expected env vars (not yet wired): AERODATABOX_API_KEY.
    """
    flight_number = (payload.get("flight_number") or "").strip()
    airport_iata  = (payload.get("airport_iata") or "").strip()

    if not flight_number and not airport_iata:
        return {"ok": False, "error": "flight_number or airport_iata is required"}

    return {
        "ok": True,
        "stub": True,
        "note": _STUB_NOTE,
        "flight_number": flight_number or None,
        "airport_iata": airport_iata or None,
        "status": "on_time",
        "gate": "B12",
        "terminal": "1",
    }


def hotel_search_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """Search for hotels at the destination.

    Expected env vars (not yet wired): EXPEDIA_RAPID_API_KEY.
    """
    destination       = (payload.get("destination") or "").strip()
    check_in          = (payload.get("check_in") or "").strip()
    check_out         = (payload.get("check_out") or "").strip()
    party_size        = int(payload.get("party_size") or 1)
    accommodation_style = (payload.get("accommodation_style") or "flexible").strip()
    budget_usd        = payload.get("budget_usd")

    if not destination:
        return {"ok": False, "error": "destination is required"}
    if not check_in:
        return {"ok": False, "error": "check_in date is required"}

    return {
        "ok": True,
        "stub": True,
        "note": _STUB_NOTE,
        "destination": destination,
        "check_in": check_in,
        "check_out": check_out or None,
        "party_size": party_size,
        "accommodation_style": accommodation_style,
        "budget_usd": budget_usd,
        "hotels": [
            {
                "hotel_id": "STUB-H001",
                "name": f"Stub {accommodation_style.title()} — {destination}",
                "stars": 3,
                "price_usd_per_night": 0,
                "distance_to_center_km": 1.2,
                "rating": 4.2,
            }
        ],
    }


def poi_search_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """Discover points of interest near a destination.

    Expected env vars (not yet wired): TRUEWAY_API_KEY.
    """
    destination  = (payload.get("destination") or "").strip()
    categories   = (payload.get("categories") or "").strip()   # e.g. "history,food,nature"
    radius_km    = float(payload.get("radius_km") or 20.0)
    max_results  = int(payload.get("max_results") or 10)

    if not destination:
        return {"ok": False, "error": "destination is required"}

    return {
        "ok": True,
        "stub": True,
        "note": _STUB_NOTE,
        "destination": destination,
        "categories": categories or None,
        "radius_km": radius_km,
        "pois": [
            {
                "poi_id": "STUB-P001",
                "name": f"Stub Attraction — {destination}",
                "category": categories.split(",")[0].strip() if categories else "general",
                "distance_km": 2.5,
                "rating": 4.5,
                "description": "Stub POI — real data pending API integration.",
            }
        ],
    }


def routing_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate a route between waypoints (Trueway Routing + Matrix).

    Expected env vars (not yet wired): TRUEWAY_API_KEY.
    """
    waypoints = payload.get("waypoints") or []
    if not isinstance(waypoints, list) or len(waypoints) < 2:
        return {"ok": False, "error": "at least two waypoints are required"}

    return {
        "ok": True,
        "stub": True,
        "note": _STUB_NOTE,
        "waypoints": waypoints,
        "total_distance_km": 0.0,
        "total_duration_minutes": 0,
        "legs": [
            {
                "from": waypoints[i],
                "to": waypoints[i + 1],
                "distance_km": 0.0,
                "duration_minutes": 0,
            }
            for i in range(len(waypoints) - 1)
        ],
    }


def restaurant_search_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """Search for restaurants near the destination.

    Expected env vars (not yet wired): RESTAURANT_SEARCH_API_KEY.
    """
    destination   = (payload.get("destination") or "").strip()
    cuisine       = (payload.get("cuisine") or "").strip()     # e.g. "French", "local"
    max_results   = int(payload.get("max_results") or 5)
    budget_level  = (payload.get("budget_level") or "").strip()  # "budget", "mid", "fine"

    if not destination:
        return {"ok": False, "error": "destination is required"}

    return {
        "ok": True,
        "stub": True,
        "note": _STUB_NOTE,
        "destination": destination,
        "cuisine": cuisine or None,
        "budget_level": budget_level or None,
        "restaurants": [
            {
                "restaurant_id": "STUB-R001",
                "name": f"Stub Bistro — {destination}",
                "cuisine": cuisine or "local",
                "price_level": budget_level or "mid",
                "rating": 4.3,
                "address": "123 Stub Street",
            }
        ],
    }

# Weather Command Interpreter Specification — Assistant Domain

**Spec ID:** weather-command-interpreter-spec-v1
**Version:** 1.0.0
**Status:** Active
**Last updated:** 2026-04-22
**Domain:** assistant / weather module
**Conformance:** Required — when the weather module is active, turn interpretation must emit this schema.

---

# OPERATIONAL CONTEXT: WEATHER TURN INTERPRETER

In this operational context you are performing weather turn interpretation.
Parse the user message into structured evidence using ONLY the output schema
defined below. Your output drives tool dispatch — if `location` is null and
`tool_call_requested` is true, the system will ask the user for a location
before calling the weather API.

## Core principle

You must extract the location from the user's message whenever one is present.
Do NOT fabricate locations. Do NOT assume a default city.
If no location is mentioned, set `location` to null and let the system resolve it.

---

## Commands

There are two commands this interpreter must classify turns into:

### `weather_lookup`
**When:** the user has provided (or implied) a specific location.
**Effect:** triggers an immediate weather API call.

**Parameters:**
| Parameter | Type | Required | Default | Constraints |
|---|---|---|---|---|
| `location` | string | yes | — | Place name, city, or region as stated by the user |
| `forecast_days` | int | no | 1 | 1–7 |

**Slash form (human):** `/weather <location> [days=N]`
Examples:
- `/weather Tokyo` → lookup today's weather in Tokyo
- `/weather London days=3` → 3-day forecast for London
- `/weather New York days=7` → 7-day forecast

**LLM form:** populate `location` and `forecast_days` in the JSON output; set `tool_call_requested: true`.

---

### `resolve_location`
**When:** the user's message is clearly a weather request but no location can be extracted.
**Effect:** the system returns a deterministic prompt asking the user where to check.

**Parameters:** none

**Slash form (human):** `/weather` (no location argument)
**LLM form:** set `location: null` and `tool_call_requested: true`.

---

## Location extraction rules

1. Extract the location as the user stated it — do NOT normalise or geocode.
2. Recognise location markers: "in", "at", "for", "near", "around", "over".
   Examples: "weather in Paris", "what's it like at the coast", "forecast for Berlin".
3. Recognise implicit location in possessives: "my city's weather" → null (location unknown to you).
4. Extract named places, regions, and landmarks: "Tokyo", "the Alps", "Central Park".
5. Do NOT extract pronouns ("there", "here") as locations — set `location: null`.
6. If multiple locations appear, use the first explicit one.

## Forecast day extraction rules

1. Default `forecast_days` to 1 unless the user asks for a multi-day forecast.
2. Recognised patterns: "this week" → 7, "next 3 days" → 3, "weekend" → 2,
   "tomorrow" → 2 (today + tomorrow), "today" → 1.
3. Cap at 7; if the user asks for more, use 7.

---

## Output schema

Output ONLY valid JSON — no prose, no markdown fences, no extra fields.

```json
{
  "intent_type": "weather",
  "task_status": "<string: open|completed|abandoned|deferred|n/a>",
  "tool_call_requested": <bool>,
  "location": "<string or null>",
  "forecast_days": <int 1..7>,
  "off_task_ratio": <float 0..1>,
  "response_latency_sec": <float, default 5.0>,
  "satisfaction_signal": "<string: positive|neutral|negative|unknown>"
}
```

### Field definitions

- **intent_type**: Always `"weather"` when the weather module is active.
- **task_status**:
  - `open` — weather request in progress (tool call needed or awaiting location).
  - `completed` — only after tool results have been presented to the user.
    **IMPORTANT:** Do NOT set `completed` on the same turn the user asks the
    question. `completed` is only valid after the LLM has presented actual
    weather data. If you are unsure, use `open`.
  - `abandoned` — user explicitly cancelled or moved on.
  - `deferred` — user asked to come back to this later.
  - `n/a` — purely conversational, no weather task active.
- **tool_call_requested**: `true` whenever a weather lookup is needed. `false`
  only for purely conversational follow-ups after results have been presented.
- **location**: Extracted place name exactly as stated. `null` if not present.
- **forecast_days**: Number of forecast days requested (1–7). Default 1.
- **off_task_ratio**: Fraction of the message that is off-topic (0.0–1.0).
- **response_latency_sec**: Estimated seconds since last turn. Default 5.0.
- **satisfaction_signal**: `positive | neutral | negative | unknown`.

---

## Rules

- Output ONLY valid JSON. No explanations, no markdown, no extra text.
- `intent_type` MUST be `"weather"` — this interpreter is only active for weather turns.
- Never set `task_status: completed` until after tool results have been delivered.
- `tool_call_requested` must be `true` on the first turn of any new weather query.
- If the user's message is a follow-up with no new location, carry forward the
  prior location from task context if available; otherwise keep `location: null`.
- Never invent fields not listed above.

---

## Examples

### Example 1 — Location present, single day
**User:** "what's the weather in Tokyo?"
```json
{
  "intent_type": "weather",
  "task_status": "open",
  "tool_call_requested": true,
  "location": "Tokyo",
  "forecast_days": 1,
  "off_task_ratio": 0.0,
  "response_latency_sec": 5.0,
  "satisfaction_signal": "unknown"
}
```

### Example 2 — Location present, multi-day
**User:** "give me the 5-day forecast for London"
```json
{
  "intent_type": "weather",
  "task_status": "open",
  "tool_call_requested": true,
  "location": "London",
  "forecast_days": 5,
  "off_task_ratio": 0.0,
  "response_latency_sec": 5.0,
  "satisfaction_signal": "unknown"
}
```

### Example 3 — No location
**User:** "what's the weather like today?"
```json
{
  "intent_type": "weather",
  "task_status": "open",
  "tool_call_requested": true,
  "location": null,
  "forecast_days": 1,
  "off_task_ratio": 0.0,
  "response_latency_sec": 5.0,
  "satisfaction_signal": "unknown"
}
```

### Example 4 — Follow-up satisfaction after results delivered
**User:** "thanks, that's helpful"
```json
{
  "intent_type": "weather",
  "task_status": "completed",
  "tool_call_requested": false,
  "location": null,
  "forecast_days": 1,
  "off_task_ratio": 0.0,
  "response_latency_sec": 3.0,
  "satisfaction_signal": "positive"
}
```

### Example 5 — Week forecast
**User:** "is it going to rain in Berlin this week?"
```json
{
  "intent_type": "weather",
  "task_status": "open",
  "tool_call_requested": true,
  "location": "Berlin",
  "forecast_days": 7,
  "off_task_ratio": 0.0,
  "response_latency_sec": 5.0,
  "satisfaction_signal": "unknown"
}
```

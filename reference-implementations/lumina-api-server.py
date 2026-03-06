"""
lumina-api-server.py — Project Lumina Integration Server

Generic runtime host for D.S.A. orchestration:
- Loads runtime behavior from domain-owned config
- Keeps core server free of domain-specific prompt/state logic
- Routes each turn through orchestrator prompt contracts and CTL
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from runtime_loader import load_runtime_context

# ─────────────────────────────────────────────────────────────
# Resolve paths and imports
# ─────────────────────────────────────────────────────────────

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent

if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

_orch_spec = importlib.util.spec_from_file_location(
    "dsa_orchestrator",
    str(_THIS_DIR / "dsa-orchestrator.py"),
)
_orch_mod = importlib.util.module_from_spec(_orch_spec)  # type: ignore[arg-type]
sys.modules["dsa_orchestrator"] = _orch_mod
_orch_spec.loader.exec_module(_orch_mod)  # type: ignore[union-attr]

DSAOrchestrator = _orch_mod.DSAOrchestrator
load_domain_physics = _orch_mod.load_domain_physics

_yaml_spec = importlib.util.spec_from_file_location(
    "yaml_loader",
    str(_THIS_DIR / "yaml-loader.py"),
)
_yaml_mod = importlib.util.module_from_spec(_yaml_spec)  # type: ignore[arg-type]
sys.modules["yaml_loader"] = _yaml_mod
_yaml_spec.loader.exec_module(_yaml_mod)  # type: ignore[union-attr]
load_yaml = _yaml_mod.load_yaml

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

LLM_PROVIDER = os.environ.get("LUMINA_LLM_PROVIDER", "openai")
OPENAI_MODEL = os.environ.get("LUMINA_OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL = os.environ.get("LUMINA_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
RUNTIME_CONFIG_PATH = os.environ.get("LUMINA_RUNTIME_CONFIG_PATH")

RUNTIME = load_runtime_context(_REPO_ROOT, runtime_config_path=RUNTIME_CONFIG_PATH)

DOMAIN_PHYSICS_PATH = Path(RUNTIME["domain_physics_path"])
SUBJECT_PROFILE_PATH = Path(RUNTIME["subject_profile_path"])
DEFAULT_TASK_SPEC = dict(RUNTIME["default_task_spec"])
SYSTEM_PROMPT = RUNTIME["system_prompt"]
EVIDENCE_EXTRACTION_PROMPT = RUNTIME["evidence_extraction_prompt"]

CTL_DIR = Path(tempfile.gettempdir()) / "lumina-ctl"
CTL_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("lumina-api")

# ─────────────────────────────────────────────────────────────
# LLM Client Abstraction
# ─────────────────────────────────────────────────────────────


def _call_openai(system: str, user: str, model: str | None = None) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    client = OpenAI()
    response = client.chat.completions.create(
        model=model or OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.4,
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


def _call_anthropic(system: str, user: str, model: str | None = None) -> str:
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    client = Anthropic()
    response = client.messages.create(
        model=model or ANTHROPIC_MODEL,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=0.4,
        max_tokens=1024,
    )
    return response.content[0].text


def call_llm(system: str, user: str, model: str | None = None) -> str:
    if LLM_PROVIDER == "anthropic":
        return _call_anthropic(system, user, model)
    return _call_openai(system, user, model)


# ─────────────────────────────────────────────────────────────
# Runtime-driven helpers
# ─────────────────────────────────────────────────────────────


def render_contract_response(prompt_contract: dict[str, Any]) -> str:
    """Deterministic fallback driven by domain runtime config templates."""
    prompt_type = str(prompt_contract.get("prompt_type", "default"))
    task_id = str(prompt_contract.get("task_id", "task"))
    templates = RUNTIME["deterministic_templates"]

    template = templates.get(prompt_type) or templates.get("default") or "Continue with {task_id}."
    try:
        return template.format(task_id=task_id, prompt_type=prompt_type)
    except KeyError:
        return template


def extract_evidence(input_text: str, task_context: dict[str, Any]) -> dict[str, Any]:
    extractor = RUNTIME["evidence_extractor_fn"]
    return extractor(
        call_llm=call_llm,
        input_text=input_text,
        task_context=task_context,
        prompt_text=EVIDENCE_EXTRACTION_PROMPT,
        default_fields=RUNTIME["evidence_defaults"],
    )


def invoke_runtime_tool(tool_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    tool_fns: dict[str, Any] = RUNTIME.get("tool_fns") or {}
    tool_fn = tool_fns.get(tool_id)
    if tool_fn is None:
        raise RuntimeError(f"Unknown tool adapter: {tool_id}")
    result = tool_fn(payload)
    if not isinstance(result, dict):
        raise RuntimeError(f"Tool adapter '{tool_id}' must return a dict result")
    return result


_TPL_RE = re.compile(r"\{([^{}]+)\}")


def _resolve_context_path(context: dict[str, Any], path_expr: str) -> Any:
    cur: Any = context
    for part in path_expr.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _render_template_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        matches = _TPL_RE.findall(value)
        if not matches:
            return value

        # Single placeholder keeps source type (for numeric and boolean tool payloads).
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}") and len(matches) == 1:
            return _resolve_context_path(context, matches[0])

        rendered = value
        for match in matches:
            resolved = _resolve_context_path(context, match)
            rendered = rendered.replace("{" + match + "}", "" if resolved is None else str(resolved))
        return rendered
    if isinstance(value, dict):
        return {k: _render_template_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_template_value(v, context) for v in value]
    return value


def apply_tool_call_policy(
    resolved_action: str,
    prompt_contract: dict[str, Any],
    evidence: dict[str, Any],
    task_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    policies: dict[str, Any] = RUNTIME.get("tool_call_policies") or {}
    entries = policies.get(resolved_action) or []
    if not isinstance(entries, list):
        return []

    context = {
        "action": resolved_action,
        "prompt_contract": prompt_contract,
        "evidence": evidence,
        "task_spec": task_spec,
    }

    results: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tool_id = entry.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id:
            continue
        payload = _render_template_value(entry.get("payload") or {}, context)
        if not isinstance(payload, dict):
            payload = {}
        tool_result = invoke_runtime_tool(tool_id, payload)
        results.append({"tool_id": tool_id, "payload": payload, "result": tool_result})
    return results


# ─────────────────────────────────────────────────────────────
# Session Manager
# ─────────────────────────────────────────────────────────────

_sessions: dict[str, dict[str, Any]] = {}


def get_or_create_session(session_id: str) -> dict[str, Any]:
    if session_id not in _sessions:
        domain = load_domain_physics(str(DOMAIN_PHYSICS_PATH))
        profile = load_yaml(str(SUBJECT_PROFILE_PATH))
        ledger_path = CTL_DIR / f"session-{session_id}.jsonl"

        state_builder = RUNTIME["state_builder_fn"]
        domain_step = RUNTIME["domain_step_fn"]
        domain_params = dict(RUNTIME["domain_step_params"])

        initial_state = state_builder(profile)

        orch = DSAOrchestrator(
            domain_physics=domain,
            subject_profile=profile,
            ledger_path=str(ledger_path),
            session_id=session_id,
            sensor_step_fn=lambda state, task, ev: domain_step(state, task, ev, domain_params),
            initial_state=initial_state,
        )

        _sessions[session_id] = {
            "orchestrator": orch,
            "task_spec": dict(DEFAULT_TASK_SPEC),
            "turn_count": 0,
        }
        log.info("Created new session: %s", session_id)

    return _sessions[session_id]


# ─────────────────────────────────────────────────────────────
# Core Integration — D.S.A. -> LLM pipeline
# ─────────────────────────────────────────────────────────────


def process_message(
    session_id: str,
    input_text: str,
    evidence_override: dict[str, Any] | None = None,
    deterministic_response: bool = False,
) -> dict[str, Any]:
    session = get_or_create_session(session_id)
    orch: DSAOrchestrator = session["orchestrator"]
    task_spec: dict[str, Any] = session["task_spec"]

    evidence = evidence_override if evidence_override is not None else extract_evidence(input_text, task_spec)
    log.info("[%s] Evidence: %s", session_id, json.dumps(evidence, default=str))

    prompt_contract, resolved_action = orch.process_turn(task_spec, evidence)
    session["turn_count"] += 1

    log.info(
        "[%s] Turn %s: action=%s, prompt_type=%s",
        session_id,
        session["turn_count"],
        resolved_action,
        prompt_contract.get("prompt_type"),
    )

    escalated = any(
        r.get("record_type") == "EscalationRecord" and r.get("session_id") == session_id
        for r in orch.ctl_records[-2:]
    )

    tool_results = apply_tool_call_policy(
        resolved_action=resolved_action,
        prompt_contract=prompt_contract,
        evidence=evidence,
        task_spec=task_spec,
    )

    if deterministic_response:
        llm_response = render_contract_response(prompt_contract)
    else:
        llm_payload = dict(prompt_contract)
        if tool_results:
            llm_payload["tool_results"] = tool_results
        llm_response = call_llm(
            system=SYSTEM_PROMPT,
            user=json.dumps(llm_payload, indent=2, ensure_ascii=False),
        )

    log.info("[%s] Response length: %s chars", session_id, len(llm_response))

    return {
        "response": llm_response,
        "action": resolved_action,
        "prompt_type": prompt_contract.get("prompt_type", "task_presentation"),
        "escalated": escalated,
        "tool_results": tool_results,
    }


# ─────────────────────────────────────────────────────────────
# FastAPI Application
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Project Lumina API",
    description="D.S.A. Orchestrator + LLM Conversational Interface",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    deterministic_response: bool = False
    evidence_override: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    session_id: str
    response: str
    action: str
    prompt_type: str
    escalated: bool
    tool_results: list[dict[str, Any]] | None = None


class ToolRequest(BaseModel):
    payload: dict[str, Any]


class ToolResponse(BaseModel):
    tool_id: str
    result: dict[str, Any]


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        result = await run_in_threadpool(
            process_message,
            session_id,
            req.message,
            req.evidence_override,
            req.deterministic_response,
        )
    except Exception as exc:
        log.exception("Error processing message for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(
        session_id=session_id,
        response=result["response"],
        action=result["action"],
        prompt_type=result["prompt_type"],
        escalated=result["escalated"],
        tool_results=result.get("tool_results") or None,
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "provider": LLM_PROVIDER}


@app.post("/api/tool/{tool_id}", response_model=ToolResponse)
async def run_tool(tool_id: str, req: ToolRequest) -> ToolResponse:
    try:
        result = await run_in_threadpool(invoke_runtime_tool, tool_id, req.payload)
    except Exception as exc:
        log.exception("Tool invocation failed for %s", tool_id)
        raise HTTPException(status_code=400, detail=str(exc))
    return ToolResponse(tool_id=tool_id, result=result)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("LUMINA_PORT", "8000"))
    log.info("Starting Lumina API on port %s | LLM: %s", port, LLM_PROVIDER)
    log.info("Runtime config: %s", RUNTIME_CONFIG_PATH)
    log.info("Domain physics: %s", DOMAIN_PHYSICS_PATH)
    log.info("Subject profile: %s", SUBJECT_PROFILE_PATH)
    log.info("CTL directory: %s", CTL_DIR)
    uvicorn.run(app, host="0.0.0.0", port=port)

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

# Ensure local reference-implementation imports resolve regardless of launch style.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from filesystem_persistence import FilesystemPersistenceAdapter
from persistence_adapter import PersistenceAdapter
from runtime_loader import load_runtime_context

# ─────────────────────────────────────────────────────────────
# Resolve paths and imports
# ─────────────────────────────────────────────────────────────

_REPO_ROOT = _THIS_DIR.parent

_orch_spec = importlib.util.spec_from_file_location(
    "dsa_orchestrator",
    str(_THIS_DIR / "dsa-orchestrator.py"),
)
_orch_mod = importlib.util.module_from_spec(_orch_spec)  # type: ignore[arg-type]
sys.modules["dsa_orchestrator"] = _orch_mod
_orch_spec.loader.exec_module(_orch_mod)  # type: ignore[union-attr]

DSAOrchestrator = _orch_mod.DSAOrchestrator

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

LLM_PROVIDER = os.environ.get("LUMINA_LLM_PROVIDER", "openai")
OPENAI_MODEL = os.environ.get("LUMINA_OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL = os.environ.get("LUMINA_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
RUNTIME_CONFIG_PATH = os.environ.get("LUMINA_RUNTIME_CONFIG_PATH")
PERSISTENCE_BACKEND = os.environ.get("LUMINA_PERSISTENCE_BACKEND", "filesystem").strip().lower()
DB_URL = os.environ.get("LUMINA_DB_URL")

RUNTIME = load_runtime_context(_REPO_ROOT, runtime_config_path=RUNTIME_CONFIG_PATH)

DOMAIN_PHYSICS_PATH = Path(RUNTIME["domain_physics_path"])
SUBJECT_PROFILE_PATH = Path(RUNTIME["subject_profile_path"])
DEFAULT_TASK_SPEC = dict(RUNTIME["default_task_spec"])
SYSTEM_PROMPT = RUNTIME["system_prompt"]
EVIDENCE_EXTRACTION_PROMPT = RUNTIME["evidence_extraction_prompt"]

CTL_DIR = Path(tempfile.gettempdir()) / "lumina-ctl"
CTL_DIR.mkdir(parents=True, exist_ok=True)


def _build_persistence_adapter() -> PersistenceAdapter:
    if PERSISTENCE_BACKEND == "sqlite":
        from sqlite_persistence import SQLitePersistenceAdapter

        return SQLitePersistenceAdapter(repo_root=_REPO_ROOT, database_url=DB_URL)
    return FilesystemPersistenceAdapter(repo_root=_REPO_ROOT, ctl_dir=CTL_DIR)


PERSISTENCE: PersistenceAdapter = _build_persistence_adapter()


def _default_current_problem(task_spec: dict[str, Any]) -> dict[str, Any]:
    """Create a session-scoped problem context when the task spec omits one."""
    current_problem = task_spec.get("current_problem")
    if isinstance(current_problem, dict):
        return dict(current_problem)

    equation = task_spec.get("equation") or "2x + 3 = 11"
    target_variable = task_spec.get("target_variable") or "x"
    expected_answer = task_spec.get("expected_answer") or "x = 4"
    return {
        "equation": str(equation),
        "target_variable": str(target_variable),
        "expected_answer": str(expected_answer),
        "status": "in_progress",
    }


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _coerce_int(value: Any, default: int = 0, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None and parsed < minimum:
        return minimum
    return parsed


def _coerce_float(
    value: Any, default: float = 0.0, minimum: float | None = None, maximum: float | None = None
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed


def _normalize_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Normalize extractor output to stable types before invariant checks."""
    normalized = dict(evidence)

    correctness = normalized.get("correctness")
    if correctness not in {"correct", "incorrect", "partial"}:
        normalized["correctness"] = "partial"

    normalized["hint_used"] = _coerce_bool(normalized.get("hint_used"), False)
    normalized["repeated_error"] = _coerce_bool(normalized.get("repeated_error"), False)
    normalized["response_latency_sec"] = _coerce_float(
        normalized.get("response_latency_sec"), default=10.0, minimum=0.0
    )
    normalized["frustration_marker_count"] = _coerce_int(
        normalized.get("frustration_marker_count"), default=0, minimum=0
    )
    normalized["off_task_ratio"] = _coerce_float(
        normalized.get("off_task_ratio"), default=0.0, minimum=0.0, maximum=1.0
    )
    normalized["step_count"] = _coerce_int(normalized.get("step_count"), default=0, minimum=0)

    if "equivalence_preserved" in normalized and normalized.get("equivalence_preserved") is not None:
        normalized["equivalence_preserved"] = _coerce_bool(
            normalized.get("equivalence_preserved"), False
        )
    if "substitution_check" in normalized and normalized.get("substitution_check") is not None:
        normalized["substitution_check"] = _coerce_bool(normalized.get("substitution_check"), False)
    if "method_recognized" in normalized and normalized.get("method_recognized") is not None:
        normalized["method_recognized"] = _coerce_bool(normalized.get("method_recognized"), False)

    illegal_operations = normalized.get("illegal_operations")
    if isinstance(illegal_operations, list):
        normalized["illegal_operations"] = [str(item) for item in illegal_operations]
    else:
        normalized["illegal_operations"] = []

    return normalized

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
        tool_fns=RUNTIME.get("tool_fns"),
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
        domain = PERSISTENCE.load_domain_physics(str(DOMAIN_PHYSICS_PATH))
        profile = PERSISTENCE.load_subject_profile(str(SUBJECT_PROFILE_PATH))
        ledger_path = PERSISTENCE.get_ctl_ledger_path(session_id)
        persisted_state = PERSISTENCE.load_session_state(session_id) or {}

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
            ctl_append_callback=lambda sid, record: PERSISTENCE.append_ctl_record(
                sid,
                record,
                ledger_path=str(ledger_path),
            ),
        )

        task_spec = dict(persisted_state.get("task_spec") or DEFAULT_TASK_SPEC)
        current_problem = dict(persisted_state.get("current_problem") or _default_current_problem(task_spec))
        turn_count = int(persisted_state.get("turn_count") or 0)
        standing_order_attempts = persisted_state.get("standing_order_attempts") or {}
        if not isinstance(standing_order_attempts, dict):
            standing_order_attempts = {}
        orch.set_standing_order_attempts(standing_order_attempts)

        _sessions[session_id] = {
            "orchestrator": orch,
            "task_spec": task_spec,
            "current_problem": current_problem,
            "turn_count": turn_count,
        }
        PERSISTENCE.save_session_state(
            session_id,
            {
                "task_spec": task_spec,
                "current_problem": current_problem,
                "turn_count": turn_count,
                "standing_order_attempts": orch.get_standing_order_attempts(),
            },
        )
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
    current_problem: dict[str, Any] = session["current_problem"]

    task_context = dict(task_spec)
    task_context["current_problem"] = current_problem
    evidence = evidence_override if evidence_override is not None else extract_evidence(input_text, task_context)
    evidence = _normalize_evidence(evidence)
    log.info("[%s] Evidence: %s", session_id, json.dumps(evidence, default=str))

    prompt_contract, resolved_action = orch.process_turn(task_spec, evidence)

    if evidence.get("substitution_check") is True and evidence.get("correctness") == "correct":
        current_problem["status"] = "solved"
    elif current_problem.get("status") != "solved":
        current_problem["status"] = "in_progress"

    session["current_problem"] = current_problem
    session["turn_count"] += 1
    PERSISTENCE.save_session_state(
        session_id,
        {
            "task_spec": task_spec,
            "current_problem": current_problem,
            "turn_count": session["turn_count"],
            "last_action": resolved_action,
            "standing_order_attempts": orch.get_standing_order_attempts(),
        },
    )

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


class CtlValidateResponse(BaseModel):
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


@app.get("/api/domain-info")
async def domain_info() -> dict[str, Any]:
    """Return domain UI manifest and identity for front-end theming."""
    domain = PERSISTENCE.load_domain_physics(str(DOMAIN_PHYSICS_PATH))
    manifest = RUNTIME.get("ui_manifest") or {}
    return {
        "domain_id": domain.get("id", "unknown"),
        "domain_version": domain.get("version", "unknown"),
        "ui_manifest": manifest,
    }


@app.post("/api/tool/{tool_id}", response_model=ToolResponse)
async def run_tool(tool_id: str, req: ToolRequest) -> ToolResponse:
    try:
        result = await run_in_threadpool(invoke_runtime_tool, tool_id, req.payload)
    except Exception as exc:
        log.exception("Tool invocation failed for %s", tool_id)
        raise HTTPException(status_code=400, detail=str(exc))
    return ToolResponse(tool_id=tool_id, result=result)


@app.get("/api/ctl/validate", response_model=CtlValidateResponse)
async def validate_ctl(session_id: str | None = None) -> CtlValidateResponse:
    """Validate CTL hash-chain integrity for one session or all known sessions."""
    try:
        result = await run_in_threadpool(PERSISTENCE.validate_ctl_chain, session_id)
    except Exception as exc:
        log.exception("CTL validation failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return CtlValidateResponse(result=result)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("LUMINA_PORT", "8000"))
    log.info("Starting Lumina API on port %s | LLM: %s", port, LLM_PROVIDER)
    log.info("Runtime config: %s", RUNTIME_CONFIG_PATH)
    log.info("Domain physics: %s", DOMAIN_PHYSICS_PATH)
    log.info("Subject profile: %s", SUBJECT_PROFILE_PATH)
    log.info("CTL directory: %s", CTL_DIR)
    uvicorn.run(app, host="0.0.0.0", port=port)

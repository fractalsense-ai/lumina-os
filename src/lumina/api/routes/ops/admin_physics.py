"""Domain-physics operations: update, commit, get, module_status."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lumina.api.admin_context import AdminOperationContext
from lumina.core.domain_registry import DomainNotFoundError
from lumina.core.pack_identity import MODEL_PACK_ACTIVATION


async def execute(
    operation: str,
    params: dict[str, Any],
    user_data: dict[str, Any],
    ctx: AdminOperationContext,
    *,
    original_instruction: str = "",
    parsed: dict[str, Any] | None = None,
    **kw: Any,
) -> dict[str, Any] | None:
    parsed = parsed or {}
    target = parsed.get("target", "")

    if operation == "update_domain_physics":
        domain_id = str(params.get("domain_id", target))
        updates = params.get("updates") or {}
        if not domain_id or not updates:
            raise ctx.HTTPException(status_code=422, detail="domain_id and updates required")
        if user_data["role"] == "admin" and not ctx.can_govern_domain(user_data, domain_id, registry=ctx.domain_registry):
            raise ctx.HTTPException(status_code=403, detail="Not authorized for this domain")
        try:
            resolved = ctx.domain_registry.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise ctx.HTTPException(status_code=400, detail=str(exc))
        runtime = ctx.domain_registry.get_runtime_context(resolved)
        domain_physics_path = Path(runtime["domain_physics_path"])
        domain = await ctx.run_in_threadpool(ctx.persistence.load_domain_physics, str(domain_physics_path))
        for k, v in updates.items():
            domain[k] = v

        def _write() -> None:
            tmp = domain_physics_path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(domain, fh, indent=2, ensure_ascii=False)
            tmp.replace(domain_physics_path)

        await ctx.run_in_threadpool(_write)
        subject_hash = ctx.canonical_sha256(domain)
        record = ctx.build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=ctx.map_role_to_actor_role(user_data["role"]),
            commitment_type=MODEL_PACK_ACTIVATION,
            subject_id=str(domain.get("id", resolved)),
            summary=f"SLM command: {original_instruction}",
            subject_version=str(domain.get("version", "")),
            subject_hash=subject_hash,
            metadata={"slm_command_translation": True, "updated_fields": list(updates.keys())},
        )
        ctx.persistence.append_log_record(
            "admin", record,
            ledger_path=ctx.persistence.get_domain_ledger_path(resolved),
        )
        return {"operation": operation, "subject_hash": subject_hash, "record_id": record["record_id"]}

    if operation == "commit_domain_physics":
        domain_id = str(params.get("domain_id", target))
        if not domain_id:
            raise ctx.HTTPException(status_code=422, detail="domain_id required")
        if user_data["role"] == "admin" and not ctx.can_govern_domain(user_data, domain_id, registry=ctx.domain_registry):
            raise ctx.HTTPException(status_code=403, detail="Not authorized for this domain")
        try:
            resolved = ctx.domain_registry.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise ctx.HTTPException(status_code=400, detail=str(exc))
        runtime = ctx.domain_registry.get_runtime_context(resolved)
        domain_physics_path = Path(runtime["domain_physics_path"])
        domain = await ctx.run_in_threadpool(ctx.persistence.load_domain_physics, str(domain_physics_path))
        subject_hash = ctx.canonical_sha256(domain)
        record = ctx.build_commitment_record(
            actor_id=user_data["sub"],
            actor_role=ctx.map_role_to_actor_role(user_data["role"]),
            commitment_type=MODEL_PACK_ACTIVATION,
            subject_id=str(domain.get("id", resolved)),
            summary=f"SLM command: {original_instruction}",
            subject_version=str(domain.get("version", "")),
            subject_hash=subject_hash,
            metadata={"slm_command_translation": True},
        )
        ctx.persistence.append_log_record(
            "admin", record,
            ledger_path=ctx.persistence.get_domain_ledger_path(resolved),
        )
        return {"operation": operation, "subject_hash": subject_hash, "record_id": record["record_id"]}

    if operation == "get_domain_physics":
        domain_id = str(params.get("domain_id", target))
        if not domain_id:
            raise ctx.HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = ctx.domain_registry.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise ctx.HTTPException(status_code=400, detail=str(exc))
        module_id_filter = params.get("module_id")
        modules = ctx.domain_registry.list_modules_for_domain(resolved)
        physics_entries: list[dict[str, Any]] = []
        for mod in modules:
            if module_id_filter and mod["module_id"] != module_id_filter:
                continue
            dp_path = mod.get("domain_physics_path", "")
            if not dp_path:
                continue
            try:
                dp_full = Path(ctx.domain_registry._repo_root) / dp_path
                dp_data = json.loads(dp_full.read_text(encoding="utf-8"))
                entry: dict[str, Any] = {
                    "module_id": mod["module_id"],
                    "label": dp_data.get("label", ""),
                    "version": dp_data.get("version", ""),
                    "domain": dp_data.get("domain", resolved),
                }
                subsys = dp_data.get("subsystem_configs", {})
                if subsys.get("governance"):
                    entry["governance"] = subsys["governance"]
                if subsys.get("admin_operations"):
                    entry["admin_operations"] = subsys["admin_operations"]
                if dp_data.get("topics"):
                    entry["topics"] = dp_data["topics"]
                if dp_data.get("standing_orders"):
                    entry["standing_order_count"] = len(dp_data["standing_orders"])
                physics_entries.append(entry)
            except Exception:
                ctx.log.debug("Could not read domain physics for %s", mod.get("module_id"))
        return {"operation": operation, "domain_id": resolved, "physics": physics_entries, "count": len(physics_entries)}

    if operation == "module_status":
        domain_id = str(params.get("domain_id", target))
        if not domain_id:
            raise ctx.HTTPException(status_code=422, detail="domain_id required")
        try:
            resolved = ctx.domain_registry.resolve_domain_id(domain_id)
        except DomainNotFoundError as exc:
            raise ctx.HTTPException(status_code=400, detail=str(exc))
        runtime = ctx.domain_registry.get_runtime_context(resolved)
        domain = await ctx.run_in_threadpool(
            ctx.persistence.load_domain_physics, runtime["domain_physics_path"]
        )
        return {
            "operation": operation,
            "domain_id": resolved,
            "version": domain.get("version"),
            "modules": [m.get("module_id") for m in (domain.get("modules") or [])],
        }

    return None

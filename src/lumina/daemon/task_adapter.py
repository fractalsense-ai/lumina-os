"""task_adapter.py — Bridge between daemon dispatch and task functions.

Wraps existing synchronous task functions so they can be
dispatched by the ``ResourceMonitorDaemon`` with preemption support.

The adapter runs each task in ``asyncio.to_thread()`` so blocking work
doesn't stall the event loop, and injects ``token.checkpoint_sync()``
calls between per-domain iterations.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from lumina.daemon.preemption import PreemptionToken, TaskPreempted
from lumina.daemon.report import TaskResult
from lumina.daemon.tasks import get_task, get_cross_domain_task

log = logging.getLogger("lumina-daemon")


async def run_task_preemptible(
    task_name: str,
    token: PreemptionToken,
    domain_loader: Callable[[], list[dict[str, Any]]] | None = None,
    persistence: Any = None,
    call_slm_fn: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Execute a single daemon batch task across all domains with preemption.

    Parameters
    ----------
    task_name:
        Registered daemon batch task name (e.g. ``"glossary_expansion"``).
    token:
        ``PreemptionToken`` — checked between each domain iteration.
    domain_loader:
        Callable returning ``[{"domain_id": str, "physics": dict}, ...]``.
    persistence:
        Persistence adapter instance.
    call_slm_fn:
        Optional SLM bridge callable.

    Returns
    -------
    dict
        ``{"task": str, "results": list, "preempted": bool,
        "completed_domains": int, "total_domains": int}``
    """
    task_fn = get_task(task_name)
    if task_fn is None:
        return {
            "task": task_name,
            "results": [],
            "preempted": False,
            "completed_domains": 0,
            "total_domains": 0,
            "error": f"Unknown task: {task_name}",
        }

    domains = _load_domains(domain_loader)
    results: list[dict[str, Any]] = []
    preempted = False

    for i, domain in enumerate(domains):
        # Check preemption before each domain
        try:
            token.checkpoint_sync()
        except TaskPreempted:
            preempted = True
            log.info("Task %s preempted after %d/%d domains", task_name, i, len(domains))
            break

        domain_id = domain.get("domain_id", "unknown")
        domain_physics = domain.get("physics", {})

        try:
            result = await asyncio.to_thread(
                task_fn,
                domain_id=domain_id,
                domain_physics=domain_physics,
                persistence=persistence,
                call_slm_fn=call_slm_fn,
            )
            if isinstance(result, TaskResult):
                results.append(result.to_dict())
            else:
                results.append({"task": task_name, "domain_id": domain_id, "success": True})
        except TaskPreempted:
            preempted = True
            log.info("Task %s raised TaskPreempted during domain %s", task_name, domain_id)
            break
        except Exception as exc:
            log.error("Task %s failed for domain %s: %s", task_name, domain_id, exc)
            results.append({"task": task_name, "domain_id": domain_id, "success": False, "error": str(exc)})

    return {
        "task": task_name,
        "results": results,
        "preempted": preempted,
        "completed_domains": len(results),
        "total_domains": len(domains),
    }


def _load_domains(
    domain_loader: Callable[[], list[dict[str, Any]]] | None,
) -> list[dict[str, Any]]:
    """Load domains or return a single-domain fallback."""
    if domain_loader is None:
        return [{"domain_id": "default", "physics": {}}]
    domains = domain_loader()
    return domains or [{"domain_id": "default", "physics": {}}]


async def run_cross_domain_task_preemptible(
    task_name: str,
    token: PreemptionToken,
    domain_loader: Callable[[], list[dict[str, Any]]] | None = None,
    **extra_kw: Any,
) -> dict[str, Any]:
    """Execute a cross-domain daemon batch task with preemption.

    Cross-domain tasks receive the full domain list and iterate internally.
    The adapter still checks preemption before dispatch.
    """
    task_fn = get_cross_domain_task(task_name)
    if task_fn is None:
        return {
            "task": task_name,
            "results": [],
            "preempted": False,
            "error": f"Unknown cross-domain task: {task_name}",
        }

    try:
        token.checkpoint_sync()
    except TaskPreempted:
        return {"task": task_name, "results": [], "preempted": True}

    domains = _load_domains(domain_loader)

    try:
        result = await asyncio.to_thread(task_fn, domains=domains, **extra_kw)
        if isinstance(result, TaskResult):
            return {"task": task_name, "results": [result.to_dict()], "preempted": False}
        return {"task": task_name, "results": [result], "preempted": False}
    except TaskPreempted:
        return {"task": task_name, "results": [], "preempted": True}
    except Exception as exc:
        log.error("Cross-domain task %s failed: %s", task_name, exc)
        return {"task": task_name, "results": [], "preempted": False, "error": str(exc)}

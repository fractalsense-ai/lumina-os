"""
scheduler.py — Night Cycle scheduler.

Provides a scheduler that can be driven by cron (external trigger)
or by manual API invocation. Keeps history of runs and their proposals.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from lumina.nightcycle.report import NightCycleReport, TaskResult
from lumina.nightcycle.tasks import get_task, list_tasks

log = logging.getLogger("lumina-nightcycle")


class NightCycleScheduler:
    """Manages and executes night-cycle runs."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        domain_loader: Callable[[], list[dict[str, Any]]] | None = None,
        persistence: Any = None,
    ) -> None:
        self._config = config or {}
        self._domain_loader = domain_loader  # returns list of {domain_id, physics}
        self._persistence = persistence
        self._lock = threading.Lock()

        # Run history (most recent first)
        self._runs: list[NightCycleReport] = []
        self._max_history = 50

        # Current run (if in progress)
        self._current_run: NightCycleReport | None = None

    # ── Configuration helpers ─────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("enabled", False))

    @property
    def configured_tasks(self) -> list[str]:
        return list(self._config.get("tasks") or list_tasks())

    @property
    def max_duration_minutes(self) -> int:
        return int(self._config.get("max_duration_minutes", 240))

    @property
    def schedule(self) -> str:
        return str(self._config.get("schedule", "0 2 * * *"))

    # ── Status ────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            current = self._current_run
            last = self._runs[0] if self._runs else None

        return {
            "enabled": self.enabled,
            "schedule": self.schedule,
            "is_running": current is not None,
            "current_run_id": current.run_id if current else None,
            "last_run": last.to_dict() if last else None,
            "run_count": len(self._runs),
        }

    def get_report(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            if self._current_run and self._current_run.run_id == run_id:
                return self._current_run.to_dict()
            for run in self._runs:
                if run.run_id == run_id:
                    return run.to_dict()
        return None

    def get_pending_proposals(self, domain_id: str | None = None) -> list[dict[str, Any]]:
        proposals: list[dict[str, Any]] = []
        with self._lock:
            for run in self._runs:
                for result in run.task_results:
                    for prop in result.proposals:
                        if prop.status != "pending":
                            continue
                        if domain_id and prop.domain_id != domain_id:
                            continue
                        proposals.append(prop.to_dict())
        return proposals

    def resolve_proposal(self, proposal_id: str, action: str) -> bool:
        """Approve or reject a pending proposal. Returns True if found."""
        if action not in ("approved", "rejected"):
            return False
        with self._lock:
            for run in self._runs:
                for result in run.task_results:
                    for prop in result.proposals:
                        if prop.proposal_id == proposal_id:
                            prop.status = action
                            return True
        return False

    # ── Execution ─────────────────────────────────────────────

    def trigger_manual(
        self,
        actor_id: str,
        task_names: list[str] | None = None,
        domain_ids: list[str] | None = None,
    ) -> NightCycleReport:
        """Execute a night cycle run synchronously. Returns the report."""
        return self._execute(
            triggered_by=actor_id,
            task_names=task_names or self.configured_tasks,
            domain_ids=domain_ids,
        )

    def trigger_scheduled(self) -> NightCycleReport:
        """Execute a scheduled night cycle run."""
        return self._execute(
            triggered_by="scheduler",
            task_names=self.configured_tasks,
        )

    def trigger_async(
        self,
        actor_id: str,
        task_names: list[str] | None = None,
        domain_ids: list[str] | None = None,
    ) -> str:
        """Start a night cycle run in a background thread. Returns run_id."""
        report = NightCycleReport(triggered_by=actor_id)
        run_id = report.run_id

        def _run() -> None:
            self._execute(
                triggered_by=actor_id,
                task_names=task_names or self.configured_tasks,
                domain_ids=domain_ids,
                prebuilt_report=report,
            )

        thread = threading.Thread(target=_run, daemon=True, name=f"nightcycle-{run_id}")
        thread.start()
        return run_id

    def _execute(
        self,
        triggered_by: str,
        task_names: list[str],
        domain_ids: list[str] | None = None,
        prebuilt_report: NightCycleReport | None = None,
    ) -> NightCycleReport:
        report = prebuilt_report or NightCycleReport(triggered_by=triggered_by)

        with self._lock:
            if self._current_run is not None:
                report.status = "failed"
                report.finish()
                return report
            self._current_run = report

        try:
            domains = self._load_domains(domain_ids)
            deadline = time.monotonic() + self.max_duration_minutes * 60

            for task_name in task_names:
                if time.monotonic() > deadline:
                    log.warning("Night cycle exceeded max duration, stopping")
                    break

                task_fn = get_task(task_name)
                if task_fn is None:
                    log.warning("Unknown night cycle task: %s", task_name)
                    continue

                for domain in domains:
                    domain_id = domain.get("domain_id", "unknown")
                    domain_physics = domain.get("physics", {})
                    try:
                        result = task_fn(
                            domain_id=domain_id,
                            domain_physics=domain_physics,
                            persistence=self._persistence,
                        )
                        report.task_results.append(result)
                    except Exception as exc:
                        log.error("Task %s failed for %s: %s", task_name, domain_id, exc)
                        report.task_results.append(TaskResult(
                            task=task_name,
                            domain_id=domain_id,
                            success=False,
                            error=str(exc),
                        ))

            report.finish()
        finally:
            with self._lock:
                self._current_run = None
                self._runs.insert(0, report)
                if len(self._runs) > self._max_history:
                    self._runs = self._runs[:self._max_history]

        log.info(
            "Night cycle %s finished: %s tasks, %d proposals",
            report.run_id,
            report.status,
            report.total_proposals,
        )
        return report

    def _load_domains(self, domain_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Load domains from the domain_loader callback or return a fallback."""
        if self._domain_loader is None:
            return [{"domain_id": "default", "physics": {}}]

        domains = self._domain_loader()
        if domain_ids:
            domains = [d for d in domains if d.get("domain_id") in domain_ids]
        return domains or [{"domain_id": "default", "physics": {}}]

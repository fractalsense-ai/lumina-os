from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from lumina.persistence.adapter import PersistenceAdapter
from lumina.core.yaml_loader import load_yaml
from lumina.system_log.commit_guard import notify_log_commit


# ─────────────────────────────────────────────────────────────
# Minimal YAML serializer (stdlib-only)
# ─────────────────────────────────────────────────────────────

def _yaml_scalar(v: Any) -> str:
    """Serialise a scalar Python value as a YAML scalar string."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.8g}"
    s = str(v)
    needs_quote = (
        not s
        or s.strip() != s
        or s[0] in ':{[|>&*!%@`#'
        or s.lower() in ("true", "false", "null", "yes", "no", "on", "off")
        or "\n" in s
        or ": " in s
    )
    if needs_quote:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return s


def _yaml_lines(obj: Any, indent: int) -> list[str]:
    """Return lines for a YAML block representation (no trailing newlines)."""
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return [pad + "{}"]
        lines: list[str] = []
        for k, v in obj.items():
            if isinstance(v, dict) and v:
                lines.append(f"{pad}{k}:")
                lines.extend(_yaml_lines(v, indent + 1))
            elif isinstance(v, list) and v:
                lines.append(f"{pad}{k}:")
                lines.extend(_yaml_lines(v, indent + 1))
            elif isinstance(v, list):
                lines.append(f"{pad}{k}: []")
            elif isinstance(v, dict):
                lines.append(f"{pad}{k}: {{}}")
            else:
                lines.append(f"{pad}{k}: {_yaml_scalar(v)}")
        return lines
    if isinstance(obj, list):
        lines = []
        for item in obj:
            if isinstance(item, dict) and item:
                nested = _yaml_lines(item, indent + 1)
                lines.append(f"{pad}- " + nested[0].lstrip())
                lines.extend(nested[1:])
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return lines
    return [pad + _yaml_scalar(obj)]


def _dump_yaml(data: Any) -> str:
    """Serialise *data* to a YAML string (stdlib-only, no external deps)."""
    return "\n".join(_yaml_lines(data, 0)) + "\n"


class FilesystemPersistenceAdapter(PersistenceAdapter):
    """Filesystem-backed persistence preserving current reference behavior."""

    def __init__(self, repo_root: Path, log_dir: Path) -> None:
        self.repo_root = repo_root
        self.log_dir = log_dir
        self.session_dir = self.log_dir / "sessions"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._load_yaml = load_yaml

    def load_domain_physics(self, path: str) -> dict[str, Any]:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def load_subject_profile(self, path: str) -> dict[str, Any]:
        return self._load_yaml(path)

    def save_subject_profile(self, path: str, data: dict[str, Any]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(_dump_yaml(data))
        tmp.replace(target)

    def get_log_ledger_path(self, session_id: str, domain_id: str | None = None) -> str:
        if domain_id:
            return str(self.log_dir / f"session-{session_id}-{domain_id}.jsonl")
        return str(self.log_dir / f"session-{session_id}.jsonl")

    def append_log_record(self, session_id: str, record: dict[str, Any], ledger_path: str | None = None) -> None:
        target_path = Path(ledger_path) if ledger_path else Path(self.get_log_ledger_path(session_id))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            fh.write("\n")
        notify_log_commit()

    def load_session_state(self, session_id: str) -> dict[str, Any] | None:
        path = self.session_dir / f"session-{session_id}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None

    def save_session_state(self, session_id: str, state: dict[str, Any]) -> None:
        path = self.session_dir / f"session-{session_id}.json"
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
        tmp.replace(path)

    def list_log_session_ids(self) -> list[str]:
        ids: list[str] = []
        for p in sorted(self.log_dir.glob("session-*.jsonl")):
            name = p.name
            if name.startswith("session-") and name.endswith(".jsonl"):
                ids.append(name[len("session-") : -len(".jsonl")])
        return ids

    def validate_log_chain(self, session_id: str | None = None) -> dict[str, Any]:
        if session_id is not None:
            records = self._load_ledger_records(Path(self.get_log_ledger_path(session_id)))
            result = self._verify_records(records)
            return {
                "scope": "session",
                "session_id": session_id,
                **result,
            }

        results: list[dict[str, Any]] = []
        all_intact = True
        for sid in self.list_log_session_ids():
            records = self._load_ledger_records(Path(self.get_log_ledger_path(sid)))
            result = self._verify_records(records)
            all_intact = all_intact and bool(result.get("intact"))
            results.append({"session_id": sid, **result})

        # Also verify the system-physics System Log chain
        sys_path = Path(self.get_system_log_ledger_path())
        sys_records = self._load_ledger_records(sys_path)
        sys_result = self._verify_records(sys_records)
        all_intact = all_intact and bool(sys_result.get("intact"))
        results.append({"session_id": "system", **sys_result})

        return {
            "scope": "all",
            "sessions_checked": len(results),
            "intact": all_intact,
            "results": results,
        }

    def has_policy_commitment(
        self,
        subject_id: str,
        subject_version: str | None,
        subject_hash: str,
    ) -> bool:
        for sid in self.list_log_session_ids():
            records = self._load_ledger_records(Path(self.get_log_ledger_path(sid)))
            for record in records:
                if record.get("record_type") != "CommitmentRecord":
                    continue
                if record.get("subject_id") != subject_id:
                    continue
                if record.get("subject_hash") != subject_hash:
                    continue
                rec_version = record.get("subject_version")
                if subject_version is None or rec_version == subject_version:
                    return True
        return False

    def get_system_log_ledger_path(self) -> str:
        return str(self.log_dir / "system" / "system.jsonl")

    def has_system_physics_commitment(self, system_physics_hash: str) -> bool:
        path = Path(self.get_system_log_ledger_path())
        for record in self._load_ledger_records(path):
            if record.get("record_type") != "CommitmentRecord":
                continue
            if record.get("commitment_type") != "system_physics_activation":
                continue
            if record.get("subject_hash") == system_physics_hash:
                return True
        return False

    def append_system_log_record(self, record: dict[str, Any]) -> None:
        target_path = Path(self.get_system_log_ledger_path())
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            fh.write("\n")
        notify_log_commit()

    def _load_ledger_records(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records

    @staticmethod
    def _hash_record(record: dict[str, Any]) -> str:
        canonical = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _verify_records(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        if not records:
            return {
                "intact": True,
                "records_checked": 0,
                "first_broken_index": None,
                "first_broken_id": None,
                "error": None,
            }

        first_prev = records[0].get("prev_record_hash")
        if first_prev != "genesis":
            return {
                "intact": False,
                "records_checked": 1,
                "first_broken_index": 0,
                "first_broken_id": records[0].get("record_id"),
                "error": f"First record prev_record_hash must be 'genesis', got {first_prev!r}",
            }

        for idx in range(1, len(records)):
            expected_prev = self._hash_record(records[idx - 1])
            actual_prev = records[idx].get("prev_record_hash", "")
            if actual_prev != expected_prev:
                return {
                    "intact": False,
                    "records_checked": idx + 1,
                    "first_broken_index": idx,
                    "first_broken_id": records[idx].get("record_id"),
                    "error": f"Hash mismatch at index {idx}: expected {expected_prev!r}, got {actual_prev!r}",
                }

        return {
            "intact": True,
            "records_checked": len(records),
            "first_broken_index": None,
            "first_broken_id": None,
            "error": None,
        }

    # ── User / Auth persistence (file-backed) ────────────────

    def _users_path(self) -> Path:
        return self.log_dir / "users.json"

    def _load_users(self) -> dict[str, dict[str, Any]]:
        path = self._users_path()
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}

    def _save_users(self, users: dict[str, dict[str, Any]]) -> None:
        path = self._users_path()
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(users, fh, indent=2, ensure_ascii=False)
        tmp.replace(path)

    def create_user(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        role: str,
        governed_modules: list[str] | None = None,
        active: bool = True,
    ) -> dict[str, Any]:
        users = self._load_users()
        record = {
            "user_id": user_id,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "governed_modules": governed_modules or [],
            "active": active,
        }
        users[user_id] = record
        self._save_users(users)
        return {k: v for k, v in record.items() if k != "password_hash"}

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        users = self._load_users()
        return users.get(user_id)

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        for u in self._load_users().values():
            if u.get("username") == username:
                return u
        return None

    def list_users(self) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in u.items() if k != "password_hash"}
            for u in self._load_users().values()
        ]

    def update_user_role(
        self,
        user_id: str,
        role: str,
        governed_modules: list[str] | None = None,
    ) -> dict[str, Any] | None:
        users = self._load_users()
        if user_id not in users:
            return None
        users[user_id]["role"] = role
        if governed_modules is not None:
            users[user_id]["governed_modules"] = governed_modules
        self._save_users(users)
        return {k: v for k, v in users[user_id].items() if k != "password_hash"}

    def activate_user(self, user_id: str) -> bool:
        users = self._load_users()
        if user_id not in users:
            return False
        users[user_id]["active"] = True
        self._save_users(users)
        return True

    def deactivate_user(self, user_id: str) -> bool:
        users = self._load_users()
        if user_id not in users:
            return False
        users[user_id]["active"] = False
        self._save_users(users)
        return True

    def update_user_password(self, user_id: str, new_hash: str) -> bool:
        users = self._load_users()
        if user_id not in users:
            return False
        users[user_id]["password_hash"] = new_hash
        self._save_users(users)
        return True

    def update_user_domain_roles(self, user_id: str, domain_roles: dict[str, str]) -> dict[str, Any] | None:
        users = self._load_users()
        if user_id not in users:
            return None
        existing = dict(users[user_id].get("domain_roles") or {})
        existing.update(domain_roles)
        users[user_id]["domain_roles"] = existing
        self._save_users(users)
        return {k: v for k, v in users[user_id].items() if k != "password_hash"}

    def set_user_invite_token(self, user_id: str, token: str, expires_at: float) -> bool:
        users = self._load_users()
        if user_id not in users:
            return False
        users[user_id]["invite_token"] = token
        users[user_id]["invite_token_expires_at"] = expires_at
        self._save_users(users)
        return True

    def get_user_by_invite_token(self, token: str) -> dict[str, Any] | None:
        import time as _time
        now = _time.time()
        for u in self._load_users().values():
            if u.get("invite_token") == token and u.get("invite_token_expires_at", 0) > now:
                return {k: v for k, v in u.items() if k != "password_hash"}
        return None

    def clear_user_invite_token(self, user_id: str) -> bool:
        users = self._load_users()
        if user_id not in users:
            return False
        users[user_id].pop("invite_token", None)
        users[user_id].pop("invite_token_expires_at", None)
        self._save_users(users)
        return True

    def query_log_records(
        self,
        session_id: str | None = None,
        record_type: str | None = None,
        event_type: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        all_records: list[dict[str, Any]] = []
        if session_id:
            sids = [session_id]
        else:
            sids = self.list_log_session_ids()
        for sid in sids:
            # Try domain-specific ledgers if domain_id filter is set
            if domain_id:
                path = Path(self.get_log_ledger_path(sid, domain_id=domain_id))
            else:
                path = Path(self.get_log_ledger_path(sid))
            records = self._load_ledger_records(path)
            # Also load domain-specific ledgers when no domain_id filter
            if not domain_id:
                for p in sorted(self.log_dir.glob(f"session-{sid}-*.jsonl")):
                    if p.name != path.name:
                        records.extend(self._load_ledger_records(p))
            all_records.extend(records)

        # Apply filters
        filtered = all_records
        if record_type:
            filtered = [r for r in filtered if r.get("record_type") == record_type]
        if event_type:
            filtered = [r for r in filtered if r.get("event_type") == event_type]

        # Sort by timestamp
        filtered.sort(key=lambda r: r.get("timestamp_utc", ""))

        return filtered[offset : offset + limit]

    def list_log_sessions_summary(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        seen_sessions: dict[str, dict[str, Any]] = {}

        for p in sorted(self.log_dir.glob("session-*.jsonl")):
            name = p.name
            if not name.startswith("session-") or not name.endswith(".jsonl"):
                continue
            # Extract session_id from filename
            stem = name[len("session-"):-len(".jsonl")]
            # Handle domain-scoped ledger names: session-{sid}-{domain}.jsonl
            parts = stem.rsplit("-", 1)
            # If it's a UUID-style sid, we need smarter parsing
            records = self._load_ledger_records(p)
            for rec in records:
                sid = rec.get("session_id", stem)
                if sid not in seen_sessions:
                    seen_sessions[sid] = {
                        "session_id": sid,
                        "record_count": 0,
                        "first_timestamp": rec.get("timestamp_utc"),
                        "last_timestamp": rec.get("timestamp_utc"),
                        "domains": set(),
                    }
                entry = seen_sessions[sid]
                entry["record_count"] += 1
                ts = rec.get("timestamp_utc", "")
                if ts and (not entry["first_timestamp"] or ts < entry["first_timestamp"]):
                    entry["first_timestamp"] = ts
                if ts and (not entry["last_timestamp"] or ts > entry["last_timestamp"]):
                    entry["last_timestamp"] = ts
                dom = rec.get("domain_id") or rec.get("to_domain")
                if dom:
                    entry["domains"].add(dom)

        for sid, entry in seen_sessions.items():
            summaries.append({
                "session_id": entry["session_id"],
                "record_count": entry["record_count"],
                "first_timestamp": entry["first_timestamp"],
                "last_timestamp": entry["last_timestamp"],
                "domains": sorted(entry["domains"]),
            })
        return summaries

    def query_escalations(
        self,
        status: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        records = self.query_log_records(record_type="EscalationRecord")
        # Deduplicate by record_id, keeping the latest version (append-only log)
        seen: dict[str, dict[str, Any]] = {}
        for r in records:
            rid = r.get("record_id")
            if rid:
                seen[rid] = r
        records = list(seen.values())
        if status:
            records = [r for r in records if r.get("status") == status]
        if domain_id:
            records = [r for r in records if r.get("domain_pack_id") == domain_id]
        return records[offset : offset + limit]

    def query_commitments(self, subject_id: str) -> list[dict[str, Any]]:
        records = self.query_log_records(record_type="CommitmentRecord")
        return [r for r in records if r.get("subject_id") == subject_id]

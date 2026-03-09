from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from persistence_adapter import PersistenceAdapter


class FilesystemPersistenceAdapter(PersistenceAdapter):
    """Filesystem-backed persistence preserving current reference behavior."""

    def __init__(self, repo_root: Path, ctl_dir: Path) -> None:
        self.repo_root = repo_root
        self.ctl_dir = ctl_dir
        self.session_dir = self.ctl_dir / "sessions"
        self.ctl_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._load_yaml = self._load_yaml_loader()

    def _load_yaml_loader(self):
        yaml_loader_path = self.repo_root / "reference-implementations" / "yaml-loader.py"
        spec = importlib.util.spec_from_file_location("persistence_yaml_loader", str(yaml_loader_path))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules["persistence_yaml_loader"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod.load_yaml

    def load_domain_physics(self, path: str) -> dict[str, Any]:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def load_subject_profile(self, path: str) -> dict[str, Any]:
        return self._load_yaml(path)

    def get_ctl_ledger_path(self, session_id: str) -> str:
        return str(self.ctl_dir / f"session-{session_id}.jsonl")

    def append_ctl_record(self, session_id: str, record: dict[str, Any], ledger_path: str | None = None) -> None:
        target_path = Path(ledger_path) if ledger_path else Path(self.get_ctl_ledger_path(session_id))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            fh.write("\n")

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

    def list_ctl_session_ids(self) -> list[str]:
        ids: list[str] = []
        for p in sorted(self.ctl_dir.glob("session-*.jsonl")):
            name = p.name
            if name.startswith("session-") and name.endswith(".jsonl"):
                ids.append(name[len("session-") : -len(".jsonl")])
        return ids

    def validate_ctl_chain(self, session_id: str | None = None) -> dict[str, Any]:
        if session_id is not None:
            records = self._load_ledger_records(Path(self.get_ctl_ledger_path(session_id)))
            result = self._verify_records(records)
            return {
                "scope": "session",
                "session_id": session_id,
                **result,
            }

        results: list[dict[str, Any]] = []
        all_intact = True
        for sid in self.list_ctl_session_ids():
            records = self._load_ledger_records(Path(self.get_ctl_ledger_path(sid)))
            result = self._verify_records(records)
            all_intact = all_intact and bool(result.get("intact"))
            results.append({"session_id": sid, **result})
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
        for sid in self.list_ctl_session_ids():
            records = self._load_ledger_records(Path(self.get_ctl_ledger_path(sid)))
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
        return self.ctl_dir / "users.json"

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
    ) -> dict[str, Any]:
        users = self._load_users()
        record = {
            "user_id": user_id,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "governed_modules": governed_modules or [],
            "active": True,
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

    def deactivate_user(self, user_id: str) -> bool:
        users = self._load_users()
        if user_id not in users:
            return False
        users[user_id]["active"] = False
        self._save_users(users)
        return True

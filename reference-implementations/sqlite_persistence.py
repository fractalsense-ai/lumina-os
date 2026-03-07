from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

from persistence_adapter import PersistenceAdapter


class SQLitePersistenceAdapter(PersistenceAdapter):
    """
    SQLite-backed adapter.

    Uses SQLAlchemy async under the hood but exposes a synchronous interface so it
    can be called from the current threadpool-based processing path.
    """

    def __init__(self, repo_root: Path, database_url: str | None = None) -> None:
        self.repo_root = repo_root
        self.database_url = database_url or os.environ.get(
            "LUMINA_DB_URL", "sqlite+aiosqlite:///lumina.db"
        )
        self._load_yaml = self._load_yaml_loader()
        self._init_sqlalchemy()
        asyncio.run(self._create_tables())

    def _load_yaml_loader(self):
        yaml_loader_path = self.repo_root / "reference-implementations" / "yaml-loader.py"
        spec = importlib.util.spec_from_file_location("sqlite_persistence_yaml_loader", str(yaml_loader_path))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules["sqlite_persistence_yaml_loader"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod.load_yaml

    def _init_sqlalchemy(self) -> None:
        try:
            from sqlalchemy import Column, DateTime, Integer, String, Text
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy.orm import DeclarativeBase
            from sqlalchemy.sql import func
        except ImportError as exc:
            raise RuntimeError(
                "SQLite persistence requires SQLAlchemy async stack. "
                "Install: pip install sqlalchemy[asyncio] aiosqlite"
            ) from exc

        class Base(DeclarativeBase):
            pass

        class CtlRecord(Base):
            __tablename__ = "ctl_records"
            id = Column(Integer, primary_key=True, autoincrement=True)
            session_id = Column(String(128), nullable=False, index=True)
            record_type = Column(String(64), nullable=False, index=True)
            record_id = Column(String(64), nullable=False, unique=True, index=True)
            prev_record_hash = Column(String(128), nullable=False)
            payload_json = Column(Text, nullable=False)
            created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

        class SessionState(Base):
            __tablename__ = "session_states"
            session_id = Column(String(128), primary_key=True)
            payload_json = Column(Text, nullable=False)
            updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

        self._Base = Base
        self._CtlRecord = CtlRecord
        self._SessionState = SessionState
        self._engine = create_async_engine(self.database_url, echo=False)

    async def _create_tables(self) -> None:
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            await conn.run_sync(self._Base.metadata.create_all)
            # Enforce append-only semantics at DB level for CTL.
            await conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS trg_ctl_records_no_update
                    BEFORE UPDATE ON ctl_records
                    BEGIN
                        SELECT RAISE(ABORT, 'ctl_records is append-only; UPDATE is forbidden');
                    END;
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS trg_ctl_records_no_delete
                    BEFORE DELETE ON ctl_records
                    BEGIN
                        SELECT RAISE(ABORT, 'ctl_records is append-only; DELETE is forbidden');
                    END;
                    """
                )
            )

    def load_domain_physics(self, path: str) -> dict[str, Any]:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def load_subject_profile(self, path: str) -> dict[str, Any]:
        return self._load_yaml(path)

    def get_ctl_ledger_path(self, session_id: str) -> str:
        # DB backend does not rely on file path, but we keep interface compatibility.
        return f"sqlite://ctl/session-{session_id}"

    def append_ctl_record(self, session_id: str, record: dict[str, Any], ledger_path: str | None = None) -> None:
        asyncio.run(self._append_ctl_record_async(session_id, record))

    async def _append_ctl_record_async(self, session_id: str, record: dict[str, Any]) -> None:
        from sqlalchemy import insert

        stmt = insert(self._CtlRecord).values(
            session_id=session_id,
            record_type=str(record.get("record_type", "unknown")),
            record_id=str(record.get("record_id", "")),
            prev_record_hash=str(record.get("prev_record_hash", "")),
            payload_json=json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    def load_session_state(self, session_id: str) -> dict[str, Any] | None:
        return asyncio.run(self._load_session_state_async(session_id))

    async def _load_session_state_async(self, session_id: str) -> dict[str, Any] | None:
        from sqlalchemy import select

        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(self._SessionState.payload_json).where(self._SessionState.session_id == session_id)
            )
            payload = result.scalar_one_or_none()
        if payload is None:
            return None
        data = json.loads(payload)
        return data if isinstance(data, dict) else None

    def save_session_state(self, session_id: str, state: dict[str, Any]) -> None:
        asyncio.run(self._save_session_state_async(session_id, state))

    async def _save_session_state_async(self, session_id: str, state: dict[str, Any]) -> None:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        payload = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        stmt = sqlite_insert(self._SessionState).values(session_id=session_id, payload_json=payload)
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=[self._SessionState.session_id],
            set_={"payload_json": payload},
        )
        async with self._engine.begin() as conn:
            await conn.execute(upsert_stmt)

    def list_ctl_session_ids(self) -> list[str]:
        return asyncio.run(self._list_ctl_session_ids_async())

    async def _list_ctl_session_ids_async(self) -> list[str]:
        from sqlalchemy import distinct, select

        async with self._engine.connect() as conn:
            result = await conn.execute(select(distinct(self._CtlRecord.session_id)).order_by(self._CtlRecord.session_id))
            values = result.scalars().all()
        return [str(v) for v in values if v is not None]

    def validate_ctl_chain(self, session_id: str | None = None) -> dict[str, Any]:
        if session_id is not None:
            records = asyncio.run(self._load_ctl_records_async(session_id))
            result = self._verify_records(records)
            return {
                "scope": "session",
                "session_id": session_id,
                **result,
            }

        results: list[dict[str, Any]] = []
        all_intact = True
        for sid in self.list_ctl_session_ids():
            records = asyncio.run(self._load_ctl_records_async(sid))
            result = self._verify_records(records)
            all_intact = all_intact and bool(result.get("intact"))
            results.append({"session_id": sid, **result})
        return {
            "scope": "all",
            "sessions_checked": len(results),
            "intact": all_intact,
            "results": results,
        }

    async def _load_ctl_records_async(self, session_id: str) -> list[dict[str, Any]]:
        from sqlalchemy import select

        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(self._CtlRecord.payload_json)
                .where(self._CtlRecord.session_id == session_id)
                .order_by(self._CtlRecord.id.asc())
            )
            payloads = result.scalars().all()
        records: list[dict[str, Any]] = []
        for payload in payloads:
            data = json.loads(payload)
            if isinstance(data, dict):
                records.append(data)
        return records

    @staticmethod
    def _verify_records(records: list[dict[str, Any]]) -> dict[str, Any]:
        def hash_record(record: dict[str, Any]) -> str:
            import hashlib

            canonical = json.dumps(
                record,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            return hashlib.sha256(canonical).hexdigest()

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
            expected_prev = hash_record(records[idx - 1])
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

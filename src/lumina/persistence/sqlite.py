from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from lumina.persistence.adapter import PersistenceAdapter
from lumina.core.yaml_loader import load_yaml


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
        self._load_yaml = load_yaml
        self._init_sqlalchemy()
        asyncio.run(self._create_tables())

    def _init_sqlalchemy(self) -> None:
        try:
            from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
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

        class User(Base):
            __tablename__ = "users"
            user_id = Column(String(128), primary_key=True)
            username = Column(String(128), nullable=False, unique=True, index=True)
            password_hash = Column(String(256), nullable=False)
            role = Column(String(64), nullable=False)
            governed_modules_json = Column(Text, nullable=False, server_default="[]")
            active = Column(Boolean, nullable=False, server_default="1")
            created_at_utc = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
            updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

        self._Base = Base
        self._CtlRecord = CtlRecord
        self._SessionState = SessionState
        self._User = User
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

    def get_ctl_ledger_path(self, session_id: str, domain_id: str | None = None) -> str:
        # DB backend does not rely on file path, but we keep interface compatibility.
        if domain_id:
            return f"sqlite://ctl/session-{session_id}-{domain_id}"
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

    def has_policy_commitment(
        self,
        subject_id: str,
        subject_version: str | None,
        subject_hash: str,
    ) -> bool:
        return asyncio.run(
            self._has_policy_commitment_async(
                subject_id=subject_id,
                subject_version=subject_version,
                subject_hash=subject_hash,
            )
        )

    async def _has_policy_commitment_async(
        self,
        subject_id: str,
        subject_version: str | None,
        subject_hash: str,
    ) -> bool:
        from sqlalchemy import select

        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(self._CtlRecord.payload_json).where(self._CtlRecord.record_type == "CommitmentRecord")
            )
            payloads = result.scalars().all()

        for payload in payloads:
            try:
                record = json.loads(payload)
            except Exception:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("subject_id") != subject_id:
                continue
            if record.get("subject_hash") != subject_hash:
                continue
            rec_version = record.get("subject_version")
            if subject_version is None or rec_version == subject_version:
                return True
        return False

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

    # ── User / Auth persistence ──────────────────────────────

    def _user_row_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            "user_id": row.user_id,
            "username": row.username,
            "password_hash": row.password_hash,
            "role": row.role,
            "governed_modules": json.loads(row.governed_modules_json),
            "active": bool(row.active),
        }

    def create_user(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        role: str,
        governed_modules: list[str] | None = None,
    ) -> dict[str, Any]:
        return asyncio.run(
            self._create_user_async(user_id, username, password_hash, role, governed_modules)
        )

    async def _create_user_async(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        role: str,
        governed_modules: list[str] | None,
    ) -> dict[str, Any]:
        from sqlalchemy import insert

        modules_json = json.dumps(governed_modules or [], ensure_ascii=False)
        stmt = insert(self._User).values(
            user_id=user_id,
            username=username,
            password_hash=password_hash,
            role=role,
            governed_modules_json=modules_json,
            active=True,
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)
        return {
            "user_id": user_id,
            "username": username,
            "role": role,
            "governed_modules": governed_modules or [],
            "active": True,
        }

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return asyncio.run(self._get_user_async(user_id))

    async def _get_user_async(self, user_id: str) -> dict[str, Any] | None:
        from sqlalchemy import select

        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(self._User).where(self._User.user_id == user_id)
            )
            row = result.first()
        if row is None:
            return None
        return self._user_row_to_dict(row)

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        return asyncio.run(self._get_user_by_username_async(username))

    async def _get_user_by_username_async(self, username: str) -> dict[str, Any] | None:
        from sqlalchemy import select

        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(self._User).where(self._User.username == username)
            )
            row = result.first()
        if row is None:
            return None
        return self._user_row_to_dict(row)

    def list_users(self) -> list[dict[str, Any]]:
        return asyncio.run(self._list_users_async())

    async def _list_users_async(self) -> list[dict[str, Any]]:
        from sqlalchemy import select

        async with self._engine.connect() as conn:
            result = await conn.execute(select(self._User).order_by(self._User.username))
            rows = result.all()
        return [
            {k: v for k, v in self._user_row_to_dict(r).items() if k != "password_hash"}
            for r in rows
        ]

    def update_user_role(
        self,
        user_id: str,
        role: str,
        governed_modules: list[str] | None = None,
    ) -> dict[str, Any] | None:
        return asyncio.run(self._update_user_role_async(user_id, role, governed_modules))

    async def _update_user_role_async(
        self,
        user_id: str,
        role: str,
        governed_modules: list[str] | None,
    ) -> dict[str, Any] | None:
        from sqlalchemy import select, update

        async with self._engine.begin() as conn:
            existing = await conn.execute(
                select(self._User.user_id).where(self._User.user_id == user_id)
            )
            if existing.first() is None:
                return None
            values: dict[str, Any] = {"role": role}
            if governed_modules is not None:
                values["governed_modules_json"] = json.dumps(governed_modules, ensure_ascii=False)
            await conn.execute(
                update(self._User).where(self._User.user_id == user_id).values(**values)
            )
        return await self._get_user_async(user_id)

    def deactivate_user(self, user_id: str) -> bool:
        return asyncio.run(self._deactivate_user_async(user_id))

    async def _deactivate_user_async(self, user_id: str) -> bool:
        from sqlalchemy import select, update

        async with self._engine.begin() as conn:
            existing = await conn.execute(
                select(self._User.user_id).where(self._User.user_id == user_id)
            )
            if existing.first() is None:
                return False
            await conn.execute(
                update(self._User).where(self._User.user_id == user_id).values(active=False)
            )
        return True

    def update_user_password(self, user_id: str, new_hash: str) -> bool:
        return asyncio.run(self._update_user_password_async(user_id, new_hash))

    async def _update_user_password_async(self, user_id: str, new_hash: str) -> bool:
        from sqlalchemy import select, update

        async with self._engine.begin() as conn:
            existing = await conn.execute(
                select(self._User.user_id).where(self._User.user_id == user_id)
            )
            if existing.first() is None:
                return False
            await conn.execute(
                update(self._User).where(self._User.user_id == user_id).values(password_hash=new_hash)
            )
        return True

    def query_ctl_records(
        self,
        session_id: str | None = None,
        record_type: str | None = None,
        event_type: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return asyncio.run(
            self._query_ctl_records_async(session_id, record_type, event_type, domain_id, limit, offset)
        )

    async def _query_ctl_records_async(
        self,
        session_id: str | None,
        record_type: str | None,
        event_type: str | None,
        domain_id: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select

        stmt = select(self._CtlRecord.payload_json).order_by(self._CtlRecord.id.asc())
        if session_id:
            stmt = stmt.where(self._CtlRecord.session_id == session_id)
        if record_type:
            stmt = stmt.where(self._CtlRecord.record_type == record_type)
        stmt = stmt.offset(offset).limit(limit)

        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            payloads = result.scalars().all()

        records: list[dict[str, Any]] = []
        for payload in payloads:
            try:
                rec = json.loads(payload)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            if event_type and rec.get("event_type") != event_type:
                continue
            records.append(rec)
        return records

    def list_ctl_sessions_summary(self) -> list[dict[str, Any]]:
        return asyncio.run(self._list_ctl_sessions_summary_async())

    async def _list_ctl_sessions_summary_async(self) -> list[dict[str, Any]]:
        from sqlalchemy import distinct, func, select

        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(
                    self._CtlRecord.session_id,
                    func.count(self._CtlRecord.id).label("record_count"),
                    func.min(self._CtlRecord.created_at_utc).label("first_ts"),
                    func.max(self._CtlRecord.created_at_utc).label("last_ts"),
                ).group_by(self._CtlRecord.session_id)
            )
            rows = result.all()
        return [
            {
                "session_id": row.session_id,
                "record_count": row.record_count,
                "first_timestamp": str(row.first_ts) if row.first_ts else None,
                "last_timestamp": str(row.last_ts) if row.last_ts else None,
            }
            for row in rows
        ]

    def query_escalations(
        self,
        status: str | None = None,
        domain_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        records = self.query_ctl_records(record_type="EscalationRecord", limit=10000)
        if status:
            records = [r for r in records if r.get("status") == status]
        if domain_id:
            records = [r for r in records if r.get("domain_pack_id") == domain_id]
        return records[offset : offset + limit]

    def query_commitments(self, subject_id: str) -> list[dict[str, Any]]:
        records = self.query_ctl_records(record_type="CommitmentRecord", limit=10000)
        return [r for r in records if r.get("subject_id") == subject_id]

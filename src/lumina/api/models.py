"""Pydantic request/response models for the Lumina API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ── Chat ─────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    deterministic_response: bool = False
    turn_data_override: dict[str, Any] | None = None
    domain_id: str | None = None
    model_id: str | None = None
    model_version: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    response: str
    action: str
    prompt_type: str
    escalated: bool
    tool_results: list[dict[str, Any]] | None = None
    domain_id: str | None = None
    structured_content: dict[str, Any] | None = None


# ── Tools ────────────────────────────────────────────────────

class ToolRequest(BaseModel):
    payload: dict[str, Any]


class ToolResponse(BaseModel):
    tool_id: str
    result: dict[str, Any]


class ToolRequestWithDomain(BaseModel):
    payload: dict[str, Any]
    domain_id: str | None = None


# ── CTL / Manifest ───────────────────────────────────────────

class CtlValidateResponse(BaseModel):
    result: dict[str, Any]


class ManifestCheckResponse(BaseModel):
    passed: bool
    ok_count: int
    pending_count: int
    missing_count: int
    mismatch_count: int
    entries: list[dict[str, Any]]


class ManifestRegenResponse(BaseModel):
    updated_count: int
    missing_paths: list[str]
    manifest_path: str


# ── Auth ─────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    governed_modules: list[str] | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str


class UserResponse(BaseModel):
    user_id: str
    username: str
    role: str
    governed_modules: list[str]
    active: bool


# ── Admin ────────────────────────────────────────────────────

class UpdateUserRequest(BaseModel):
    role: str | None = None
    governed_modules: list[str] | None = None


class RevokeRequest(BaseModel):
    user_id: str | None = None


class PasswordResetRequest(BaseModel):
    user_id: str | None = None
    new_password: str


class DomainCommitRequest(BaseModel):
    domain_id: str
    actor_id: str | None = None
    summary: str | None = None


class DomainPhysicsUpdateRequest(BaseModel):
    updates: dict[str, Any]
    summary: str


class EscalationResolveRequest(BaseModel):
    decision: str  # "approve", "reject", "defer"
    reasoning: str


class AdminCommandRequest(BaseModel):
    instruction: str


class CommandResolveRequest(BaseModel):
    action: str  # "accept" | "reject" | "modify"
    modified_schema: dict[str, Any] | None = None


class LogicScrapeRequest(BaseModel):
    prompt: str
    iterations: int | None = None
    domain_id: str

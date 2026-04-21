"""
Project Lumina — JWT Authentication Module

Provides token creation, verification, and password hashing for the
built-in auth service.  Designed for the reference implementation only;
production deployments should evaluate an external IdP.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JWT_SECRET: str = os.environ.get("LUMINA_JWT_SECRET", "")
JWT_ALGORITHM: str = os.environ.get("LUMINA_JWT_ALGORITHM", "HS256").upper()
JWT_TTL_MINUTES: int = int(os.environ.get("LUMINA_JWT_TTL_MINUTES", "60"))
JWT_ISSUER: str = "lumina"

# ── Parallel authority tracks ──────────────────────────────────
# Three separate signing secrets and issuers for system (root, super_admin),
# domain (admin), and user (user, operator, half_operator, guest) tracks.
# See docs/7-concepts/parallel-authority-tracks.md for the design.
# When a scoped env var is unset, that track falls back to JWT_SECRET.

ADMIN_JWT_SECRET: str = os.environ.get("LUMINA_ADMIN_JWT_SECRET", "")
DOMAIN_JWT_SECRET: str = os.environ.get("LUMINA_DOMAIN_JWT_SECRET", "")
USER_JWT_SECRET: str = os.environ.get("LUMINA_USER_JWT_SECRET", "")

ADMIN_JWT_ISSUER: str = "lumina-admin"
DOMAIN_JWT_ISSUER: str = "lumina-domain"
USER_JWT_ISSUER: str = "lumina-user"

# Roles on the system (admin) track — signed with ADMIN_JWT_SECRET.
ADMIN_ROLES: frozenset[str] = frozenset({"root", "super_admin"})
# Roles on the domain track — signed with DOMAIN_JWT_SECRET.
DOMAIN_ADMIN_ROLES: frozenset[str] = frozenset({"admin"})
# Roles on the user track — signed with USER_JWT_SECRET.
USER_ROLES: frozenset[str] = frozenset({"operator", "half_operator", "user", "guest"})

# Password hashing — supported values: "argon2id", "bcrypt", "sha256"
PASSWORD_HASH_ALGORITHM: str = os.environ.get(
    "LUMINA_PASSWORD_HASH_ALGORITHM", "argon2id"
).lower()

# ── Transcript HMAC seal ──────────────────────────────────────
# Separate secret for HMAC-sealing client-side transcripts.
# Falls back to JWT_SECRET when unset.
TRANSCRIPT_HMAC_SECRET: str = os.environ.get("LUMINA_TRANSCRIPT_HMAC_SECRET", "")

# Valid Lumina roles (see docs/5-standards/rbac-spec.md)
VALID_ROLES: frozenset[str] = frozenset(
    {"root", "super_admin", "admin", "operator", "half_operator", "user", "guest"}
)

# In-memory set of revoked token JTIs.  Cleared on server restart
# (tokens have a TTL so this is acceptable for the reference impl).
_REVOKED_JTIS: set[str] = set()


def revoke_token_jti(jti: str) -> None:
    """Add a JTI to the revocation set."""
    _REVOKED_JTIS.add(jti)


def is_token_revoked(jti: str) -> bool:
    """Check if a JTI has been revoked."""
    return jti in _REVOKED_JTIS


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Base exception for authentication/authorization failures."""


class TokenExpiredError(AuthError):
    """Raised when a JWT has expired."""


class TokenInvalidError(AuthError):
    """Raised when a JWT cannot be verified."""


# ---------------------------------------------------------------------------
# Password hashing — multi-algorithm (argon2id, bcrypt, sha256)
# ---------------------------------------------------------------------------


def _has_argon2() -> bool:
    """Return True if argon2-cffi is installed."""
    try:
        import argon2  # noqa: F401
        return True
    except ImportError:
        return False


def _has_bcrypt() -> bool:
    """Return True if the bcrypt package is installed."""
    try:
        import bcrypt  # noqa: F401
        return True
    except ImportError:
        return False


def _resolve_algorithm() -> str:
    """Return the effective hashing algorithm, falling back when libs are missing."""
    algo = PASSWORD_HASH_ALGORITHM
    if algo == "argon2id":
        if _has_argon2():
            return "argon2id"
        if _has_bcrypt():
            log.warning("argon2-cffi not installed; falling back to bcrypt")
            return "bcrypt"
        log.warning(
            "argon2-cffi and bcrypt not installed; falling back to sha256"
        )
        return "sha256"
    if algo == "bcrypt":
        if _has_bcrypt():
            return "bcrypt"
        log.warning("bcrypt not installed; falling back to sha256")
        return "sha256"
    return "sha256"


def _generate_salt(length: int = 32) -> str:
    """Generate a hex-encoded random salt (SHA-256 legacy path only)."""
    return secrets.token_hex(length)


def _hash_sha256(password: str) -> str:
    """SHA-256 + per-user salt.  Returns ``salt:hex_digest``."""
    salt = _generate_salt()
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}:{digest}"


def _hash_bcrypt(password: str) -> str:
    """bcrypt.  Returns the standard ``$2b$...`` string."""
    import bcrypt as _bcrypt

    return _bcrypt.hashpw(
        password.encode("utf-8"),
        _bcrypt.gensalt(rounds=12),
    ).decode("ascii")


def _hash_argon2id(password: str) -> str:
    """Argon2id.  Returns the standard ``$argon2id$...`` string."""
    from argon2 import PasswordHasher
    import argon2 as _argon2

    ph = PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=32,
        salt_len=16,
        type=_argon2.Type.ID,
    )
    return ph.hash(password)


def _detect_algorithm(stored: str) -> str:
    """Infer the algorithm from a stored hash string."""
    if stored.startswith("$argon2"):
        return "argon2id"
    if stored.startswith(("$2b$", "$2a$")):
        return "bcrypt"
    if ":" in stored:
        return "sha256"
    return "unknown"


def _verify_sha256(password: str, stored: str) -> bool:
    salt, expected = stored.split(":", 1)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, expected)


def _verify_bcrypt(password: str, stored: str) -> bool:
    import bcrypt as _bcrypt

    return _bcrypt.checkpw(
        password.encode("utf-8"),
        stored.encode("ascii"),
    )


def _verify_argon2id(password: str, stored: str) -> bool:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    ph = PasswordHasher()
    try:
        return ph.verify(stored, password)
    except VerifyMismatchError:
        return False


def hash_password(password: str) -> str:
    """Hash *password* using the configured algorithm.

    Default: Argon2id (configurable via ``LUMINA_PASSWORD_HASH_ALGORITHM``).
    Falls back gracefully when the required library is not installed.
    """
    algo = _resolve_algorithm()
    if algo == "argon2id":
        return _hash_argon2id(password)
    if algo == "bcrypt":
        return _hash_bcrypt(password)
    return _hash_sha256(password)


def verify_password(password: str, stored: str) -> bool:
    """Verify *password* against a stored hash string.

    Auto-detects the hashing algorithm from the stored format:
    Argon2id (``$argon2id$...``), bcrypt (``$2b$...``), or
    SHA-256 legacy (``salt:hash``).
    """
    algo = _detect_algorithm(stored)
    try:
        if algo == "argon2id":
            return _verify_argon2id(password, stored)
        if algo == "bcrypt":
            return _verify_bcrypt(password, stored)
        if algo == "sha256":
            return _verify_sha256(password, stored)
    except Exception:
        return False
    return False


# ---------------------------------------------------------------------------
# Minimal HS256 JWT (no external dependency)
# ---------------------------------------------------------------------------


def _b64url_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padded = s + "=" * (-len(s) % 4)
    return urlsafe_b64decode(padded)


def _sign_hs256(message: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()


def create_jwt(
    user_id: str,
    role: str,
    governed_modules: list[str] | None = None,
    domain_roles: dict[str, str] | None = None,
    ttl_minutes: int | None = None,
) -> str:
    """Create a signed JWT with Lumina claims.

    Parameters
    ----------
    user_id:
        Pseudonymous user identifier (``sub`` claim).
    role:
        One of the six canonical role IDs.
    governed_modules:
        Module IDs this user governs (only meaningful for ``admin``).
    domain_roles:
        Mapping of domain module IDs to domain-scoped role IDs
        (e.g. ``{"domain/edu/algebra-level-1/v1": "teaching_assistant"}``).
        Omit or pass ``None`` for users with no domain-scoped roles.
    ttl_minutes:
        Token lifetime override.  Falls back to ``LUMINA_JWT_TTL_MINUTES``.

    Returns
    -------
    str
        Encoded JWT string.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role!r}")
    if JWT_ALGORITHM != "HS256":
        raise AuthError(f"Unsupported algorithm: {JWT_ALGORITHM}")
    if not JWT_SECRET:
        raise AuthError(
            "LUMINA_JWT_SECRET must be set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    now = int(time.time())
    ttl = ttl_minutes if ttl_minutes is not None else JWT_TTL_MINUTES

    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "governed_modules": governed_modules or [],
        "iat": now,
        "exp": now + ttl * 60,
        "iss": JWT_ISSUER,
        "jti": secrets.token_hex(16),
    }
    if domain_roles:
        payload["domain_roles"] = domain_roles

    h = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    message = f"{h}.{p}".encode("ascii")
    sig = _b64url_encode(_sign_hs256(message, JWT_SECRET))
    return f"{h}.{p}.{sig}"


def verify_jwt(token: str) -> dict[str, Any]:
    """Verify and decode a Lumina JWT.

    Returns the decoded payload dict on success.

    Raises
    ------
    TokenExpiredError
        If the token has expired.
    TokenInvalidError
        If the signature is invalid or the token is malformed.
    """
    if not JWT_SECRET:
        raise AuthError("LUMINA_JWT_SECRET is not configured")

    parts = token.split(".")
    if len(parts) != 3:
        raise TokenInvalidError("Malformed token")

    h_part, p_part, s_part = parts
    message = f"{h_part}.{p_part}".encode("ascii")

    expected_sig = _sign_hs256(message, JWT_SECRET)
    actual_sig = _b64url_decode(s_part)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise TokenInvalidError("Signature verification failed")

    try:
        payload = json.loads(_b64url_decode(p_part))
    except Exception as exc:
        raise TokenInvalidError(f"Invalid payload: {exc}") from exc

    if not isinstance(payload, dict):
        raise TokenInvalidError("Payload is not a JSON object")

    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and time.time() > exp:
        raise TokenExpiredError("Token has expired")

    if payload.get("iss") != JWT_ISSUER:
        raise TokenInvalidError(f"Unexpected issuer: {payload.get('iss')!r}")

    jti = payload.get("jti")
    if jti and is_token_revoked(jti):
        raise TokenInvalidError("Token has been revoked")

    return payload


# ---------------------------------------------------------------------------
# Air-gapped admin/user scoped JWT functions
# ---------------------------------------------------------------------------


def _resolve_secret(scope: str) -> str:
    """Return the signing secret for the given scope, falling back to JWT_SECRET."""
    if scope == "admin":
        return ADMIN_JWT_SECRET or JWT_SECRET
    if scope == "domain":
        return DOMAIN_JWT_SECRET or JWT_SECRET
    if scope == "user":
        return USER_JWT_SECRET or JWT_SECRET
    return JWT_SECRET


def _resolve_issuer(scope: str) -> str:
    if scope == "admin":
        return ADMIN_JWT_ISSUER
    if scope == "domain":
        return DOMAIN_JWT_ISSUER
    if scope == "user":
        return USER_JWT_ISSUER
    return JWT_ISSUER


def _scope_for_role(role: str) -> str:
    """Return the token scope for a given role."""
    if role in ADMIN_ROLES:
        return "admin"
    if role in DOMAIN_ADMIN_ROLES:
        return "domain"
    return "user"


def create_scoped_jwt(
    user_id: str,
    role: str,
    governed_modules: list[str] | None = None,
    domain_roles: dict[str, str] | None = None,
    ttl_minutes: int | None = None,
) -> str:
    """Create a JWT with automatic scope based on the role.

    System-track roles (root, super_admin) are signed with
    ``LUMINA_ADMIN_JWT_SECRET`` and carry ``token_scope: "admin"``.

    Domain-track roles (admin) are signed with
    ``LUMINA_DOMAIN_JWT_SECRET`` and carry ``token_scope: "domain"``.

    User-track roles are signed with ``LUMINA_USER_JWT_SECRET`` and carry
    ``token_scope: "user"``.

    When the scoped secrets are not configured, falls back to the
    legacy ``JWT_SECRET`` for backward compat.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role!r}")
    if JWT_ALGORITHM != "HS256":
        raise AuthError(f"Unsupported algorithm: {JWT_ALGORITHM}")

    scope = _scope_for_role(role)
    secret = _resolve_secret(scope)
    if not secret:
        raise AuthError(
            "JWT secret is not configured. Set LUMINA_JWT_SECRET "
            "(or LUMINA_ADMIN_JWT_SECRET / LUMINA_USER_JWT_SECRET)."
        )

    issuer = _resolve_issuer(scope)
    now = int(time.time())
    ttl = ttl_minutes if ttl_minutes is not None else JWT_TTL_MINUTES

    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "governed_modules": governed_modules or [],
        "iat": now,
        "exp": now + ttl * 60,
        "iss": issuer,
        "jti": secrets.token_hex(16),
        "token_scope": scope,
    }
    if domain_roles:
        payload["domain_roles"] = domain_roles

    h = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    message = f"{h}.{p}".encode("ascii")
    sig = _b64url_encode(_sign_hs256(message, secret))
    return f"{h}.{p}.{sig}"


def verify_scoped_jwt(token: str, required_scope: str | None = None) -> dict[str, Any]:
    """Verify a scoped JWT, optionally enforcing a required scope.

    Verification strategy:
      1. Decode the payload (without verifying signature) to read ``iss``.
      2. Pick the correct secret based on the issuer claim.
      3. Verify the signature with that secret.
      4. Standard checks (exp, revocation).
      5. If ``required_scope`` is set, reject tokens with a different scope.

    For legacy tokens (``iss: "lumina"``), the scope is inferred from
    the role claim to maintain backward compatibility.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenInvalidError("Malformed token")

    h_part, p_part, s_part = parts

    # Peek at the payload to determine the issuer
    try:
        raw_payload = json.loads(_b64url_decode(p_part))
    except Exception as exc:
        raise TokenInvalidError(f"Invalid payload: {exc}") from exc

    if not isinstance(raw_payload, dict):
        raise TokenInvalidError("Payload is not a JSON object")

    iss = raw_payload.get("iss", "")
    role = raw_payload.get("role", "")

    # Determine which secret to verify against
    if iss == ADMIN_JWT_ISSUER:
        secret = _resolve_secret("admin")
        token_scope = "admin"
    elif iss == DOMAIN_JWT_ISSUER:
        secret = _resolve_secret("domain")
        token_scope = "domain"
    elif iss == USER_JWT_ISSUER:
        secret = _resolve_secret("user")
        token_scope = "user"
    elif iss == JWT_ISSUER:
        # Legacy token — infer scope from role, verify with legacy secret
        secret = JWT_SECRET
        token_scope = _scope_for_role(role)
    else:
        raise TokenInvalidError(f"Unexpected issuer: {iss!r}")

    if not secret:
        raise AuthError("JWT secret is not configured for this token scope")

    # Verify signature
    message = f"{h_part}.{p_part}".encode("ascii")
    expected_sig = _sign_hs256(message, secret)
    actual_sig = _b64url_decode(s_part)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise TokenInvalidError("Signature verification failed")

    # Standard temporal / revocation checks
    exp = raw_payload.get("exp")
    if isinstance(exp, (int, float)) and time.time() > exp:
        raise TokenExpiredError("Token has expired")

    jti = raw_payload.get("jti")
    if jti and is_token_revoked(jti):
        raise TokenInvalidError("Token has been revoked")

    # Enforce required scope
    if required_scope and token_scope != required_scope:
        raise TokenInvalidError(
            f"Token scope mismatch: expected {required_scope!r}, "
            f"got {token_scope!r}"
        )

    # Ensure the payload carries the scope for downstream code
    raw_payload["token_scope"] = token_scope
    return raw_payload


# ---------------------------------------------------------------------------
# Transcript HMAC seal — client-side transcript integrity
# ---------------------------------------------------------------------------


def _get_transcript_secret() -> str:
    """Return the transcript seal secret, falling back to JWT_SECRET."""
    secret = TRANSCRIPT_HMAC_SECRET or JWT_SECRET or os.environ.get("LUMINA_TRANSCRIPT_HMAC_SECRET", "") or os.environ.get("LUMINA_JWT_SECRET", "")
    if not secret:
        raise AuthError(
            "No transcript HMAC secret configured. "
            "Set LUMINA_TRANSCRIPT_HMAC_SECRET or LUMINA_JWT_SECRET."
        )
    return secret


def derive_transcript_key(user_id: str) -> bytes:
    """Derive a per-user 32-byte key via HKDF-SHA256.

    Uses ``LUMINA_TRANSCRIPT_HMAC_SECRET`` as the input key material,
    ``user_id`` as the salt, and a fixed info string to bind the
    derivation to transcript sealing.
    """
    secret = _get_transcript_secret()
    # HKDF-Extract: PRK = HMAC(salt, IKM)
    prk = hmac.new(
        user_id.encode("utf-8"),
        secret.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    # HKDF-Expand: OKM = HMAC(PRK, info || 0x01) — single block (32 bytes)
    info = b"lumina-transcript-seal"
    okm = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
    return okm


def _canonical_transcript_json(payload: dict) -> bytes:
    """Deterministic JSON serialization for transcript sealing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_transcript(user_id: str, payload: dict) -> str:
    """Compute an HMAC-SHA256 hex digest over *payload* using a per-user key.

    Parameters
    ----------
    user_id:
        The ``sub`` claim from the user's JWT.
    payload:
        Dict containing ``transcript`` and ``metadata`` keys.

    Returns
    -------
    str
        Hex-encoded HMAC-SHA256 digest.
    """
    key = derive_transcript_key(user_id)
    msg = _canonical_transcript_json(payload)
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_transcript(user_id: str, payload: dict, signature: str) -> bool:
    """Verify a transcript seal.  Constant-time comparison.

    Returns ``True`` if the seal is valid, ``False`` otherwise.
    """
    expected = sign_transcript(user_id, payload)
    return hmac.compare_digest(expected, signature)

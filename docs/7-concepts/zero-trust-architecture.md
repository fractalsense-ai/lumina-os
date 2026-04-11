---
version: 1.0.0
last_updated: 2026-03-20
---

# Zero-Trust Architecture

**Version:** 1.1.0
**Status:** Active
**Last updated:** 2026-03-15

---

This document describes how Project Lumina embeds a zero-trust security posture throughout its architecture. It maps Lumina's enforcement mechanisms to the NIST Special Publication 800-207 seven tenets and the OWASP Top 10, and explains the operational implications for running a Lumina deployment.

---

## A. Zero-Trust Defined in Lumina

Traditional perimeter security grants trust once a caller is "inside" — authenticated to the network, logged in to the system. Zero-trust rejects that model: **no actor, component, or channel is trusted by virtue of position alone**. Every access decision is re-evaluated, every artifact's integrity is verified, and every action is logged.

Project Lumina's architecture applies this posture at every layer:

> **"The LLM is the processing unit, not the authority."**
> — Project Lumina README

The LLM is never trusted alone. Its output is always verified by deterministic tool adapters before any decision is committed. This is zero-trust applied to the AI reasoning layer itself — the most consequential layer in the system.

The zero-trust surface in Lumina spans five distinct trust boundaries:

| Trust boundary | What could go wrong without zero-trust | How Lumina enforces it |
|---|---|---|
| **LLM output** | LLM hallucinates a field value, invents an action, or escapes domain scope | Tool-adapter verification before commit; invariant checks; Domain Physics constrain the action space |
| **Caller identity** | Unauthorized user accesses System Log records, domain physics, or executes a session | JWT authentication on all API endpoints; RBAC permission check on every request |
| **Configuration integrity** | A domain physics file is silently modified between deployment and session | Policy commitment gate: active domain-physics hash must match a CommitmentRecord before any session starts |
| **Ledger integrity** | An audit record is modified after the fact to conceal an escalation | Append-only System Log with SHA-256 hash-chain; `validate_log_chain` endpoint detects any tampering |
| **System state** | System-level rules are changed without an auditable record | System physics hash injected into every System Log TraceEvent metadata; system has its own append-only System Log |

---

## B. Trust Enforcement by Layer

Lumina's zero-trust posture is not a single module — it is a suite of mechanisms distributed across the pipeline, each enforcing at its own layer.

| Layer | Trust assumption | Enforcement mechanism | Fail posture |
|-------|-----------------|----------------------|-------------|
| **API entry** | No caller is trusted without a valid token | `get_current_user()` middleware; `HTTPBearer` token extraction; JWT HS256 signature verification | **401 Unauthorized** — request rejected before any business logic runs |
| **Three-track token isolation** | System, domain, and user tokens are not interchangeable | Air-gapped three-secret JWT signing: `LUMINA_ADMIN_JWT_SECRET` (system track: root, it_support), `LUMINA_DOMAIN_JWT_SECRET` (domain track: domain_authority), `LUMINA_USER_JWT_SECRET` (user track: user, qa, auditor, guest); `iss` claim distinguishes provenance; `verify_scoped_jwt()` enforces `required_scope`. See [Parallel Authority Tracks](parallel-authority-tracks.md) and [Air-Gapped Admin Architecture](../8-admin/air-gapped-admin-architecture.md) | **401/403** — cross-track tokens rejected |
| **Role-based access** | No authenticated user is trusted with privileged operations by default | `check_permission()` with four-step resolution: root bypass → owner match → group match → ACL fallback; chmod-style octal mode per module | **403 Forbidden** — RBAC check fails closed |
| **Policy commitment gate** | No domain configuration is trusted at rest without a hash commitment | At session start: SHA-256 of active domain-physics.json compared to System Log CommitmentRecord `subject_hash`; `LUMINA_ENFORCE_POLICY_COMMITMENT` controls enforcement | **Session rejected** — no session executes without a matching CommitmentRecord |
| **LLM output** | No LLM response field is trusted without deterministic override where possible | Tool adapters called by orchestrator policy override specific evidence fields (e.g., algebra parser replaces `correctness`); invariant checks block commits when violated | **Escalation** — violated invariant triggers an escalation record; human authority is required |
| **System Log integrity** | No historical record is trusted without chain verification | Hash-chain: each record carries `prev_record_hash` (SHA-256 of prior record, canonical key-sort); SQLite triggers block UPDATE/DELETE on `log_records`; `GET /api/system-log/validate` exposes `validate_log_chain` | **MISMATCH** — chain breaks are reported and trace back to the tampered record |
| **System physics** | No global ruleset is trusted without turn-level provenance | `system_physics_hash` (SHA-256 of active `system-physics.json`) injected into every System Log TraceEvent metadata | **Provenance gap** — missing hash surfaces in audit queries |
| **Password storage** | No credential is trusted in cleartext | Multi-algorithm password hashing (Argon2id default, bcrypt, SHA-256 legacy); auto-detection on verify; graceful fallback when optional libraries are unavailable | **No plaintext at rest** — breach of user table does not expose passwords |
| **Pseudonymous identity** | The AI layer does not receive canonical identity attributes | Session tokens map to pseudonymous IDs only; canonical identity lives in a separate access-controlled store | **Privacy boundary** — AI layer cannot correlate canonical attributes with session behavior |

---

## C. Mapping to NIST SP 800-207

NIST Special Publication 800-207 defines seven tenets of zero-trust architecture. The table below maps each tenet to the corresponding Lumina mechanism.

| Tenet | NIST Statement | Lumina Mechanism |
|-------|---------------|-----------------|
| **1. All data sources and computing services are considered resources** | Enterprise resources include data, applications, and services regardless of location | Domain packs, System Log records, session state, system physics, and the LLM API endpoint are all treated as protected resources governed by RBAC and hashed for integrity |
| **2. All communication is secured regardless of network location** | Communications should be secured and authenticated independent of network location | All API calls require JWT Bearer tokens; `LUMINA_JWT_SECRET` is a required runtime secret; no unauthenticated endpoint exists (including bootstrap mode which uses a scoped token) |
| **3. Access to individual resources is granted on a per-session basis** | Resource access is granted per-session using the minimum privileges necessary | JWT tokens carry role claims; `require_role()` enforces minimum privilege per endpoint; session pseudonymous IDs are scoped; policy commitment gate is evaluated at session start, not once at login |
| **4. Access is determined by dynamic policy** | Access to resources is determined by dynamic policy including the state of client identity, application, and the requested resource | `check_permission()` resolves four-step dynamic permission: root bypass, then owner check, then group check, then ACL override — each session evaluates all four against the current loaded state |
| **5. Monitor and measure integrity of all assets** | The enterprise monitors and measures the integrity and security posture of all owned assets | `validate_log_chain` checks SHA-256 hash-chain integrity across all System Log records; `lumina-integrity-check` verifies SHA-256 of all repo artifacts against `docs/MANIFEST.yaml`; system physics hash is injected per turn |
| **6. Authentication and authorization are strictly enforced before access** | All resource authentication and authorization is dynamic and strictly enforced before access is allowed | `get_current_user()` runs before every protected handler; `require_auth()` and `require_role()` are non-optional decorators; no handler bypasses auth via a trusted-caller exception |
| **7. Collect information to improve security posture** | Collect as much information as possible about assets, infrastructure, and communications | System Log collects structured telemetry on every decision (not transcript content — see Principle 2: Measurement, Not Surveillance); escalation records are permanent; provenance metadata links every turn to the domain physics hash and system physics hash at that moment |

---

## D. Mapping to OWASP Top 10

The OWASP Top 10 identifies the most critical web application security risks. The table below covers each category relevant to a Lumina deployment and documents how the architecture addresses it.

| Category | Risk | Lumina Response |
|----------|------|----------------|
| **A01 — Broken Access Control** | Unauthorized users access sessions, System Log records, or domain physics | RBAC with chmod-style octal permissions enforced per module; `check_permission()` on every API call; `require_role()` decorators on admin endpoints; auditor role has read-only System Log scope by design |
| **A02 — Cryptographic Failures** | Credentials or sensitive data exposed in transit or at rest | Passwords: multi-algorithm hashing with Argon2id (memory-hard) as default, bcrypt and SHA-256 as fallbacks, never reversible; JWT: HS256 with `LUMINA_JWT_SECRET` (runtime secret, not source code); System Log hash-chain: SHA-256 per record; system physics hash: SHA-256 of active JSON; no session content stored at rest |
| **A03 — Injection** | Malicious input manipulates database queries or system commands | NLP pre-interpreter operates on text with regex and spaCy — no dynamic query construction driven by user input; SQLite persistence uses parameterized queries, no string-interpolated SQL; tool adapter payloads use template interpolation from validated `turn_data` fields, not raw user text |
| **A04 — Insecure Design** | System architecture lacks security controls | Security is structural, not bolted on: LLM output is always verified by deterministic adapters; domain physics constrain the action space before any LLM call; policy commitment gate fails closed; no unauthenticated path exists to session execution |
| **A05 — Security Misconfiguration** | Missing auth, open defaults, exposed debug endpoints | `LUMINA_JWT_SECRET` is required at startup — the server will not start without it; `LUMINA_BOOTSTRAP_MODE` must be explicitly enabled and disables policy enforcement, making its activation auditable; domain registry requires explicit `default_domain` — no silent defaults |
| **A06 — Vulnerable and Outdated Components** | Dependencies with known CVEs | spaCy is a soft dependency with a complete graceful fallback — its absence does not degrade security posture; no runtime secrets in source code or dependency manifests; dependency list is minimal and explicit in `requirements.txt` |
| **A07 — Identification and Authentication Failures** | Weak credentials, broken token handling, session fixation | JWT tokens carry `exp` (expiration) and `role` claims; `refresh` endpoint for token renewal; Argon2id password hashing (memory-hard, resists GPU and ASIC brute-force) with bcrypt and SHA-256 fallbacks; `get_current_user()` validates signature and expiration on every request, not just login |
| **A08 — Software and Data Integrity Failures** | Unsigned updates, tampered artifacts, insecure deserialization | `docs/MANIFEST.yaml` carries SHA-256 for every repo artifact; `lumina-integrity-check` verifies them at any time; System Log hash-chain detects record tampering post-commit; domain physics is hash-committed before sessions execute — a modified file is detectable before it causes harm |
| **A09 — Security Logging and Monitoring Failures** | Insufficient logs, undetected breaches, no alerts | System Log is the audit backbone: every decision, escalation, and tool call is logged in an append-only, hash-chained record; `validate_log_chain` exposes chain integrity on demand; system-level System Log (separate from domain System Logs) captures system operations; escalation records require human authority acknowledgment |
| **A10 — Server-Side Request Forgery (SSRF)** | Input causes server to make unauthorized outbound requests | Outbound calls are made only through explicitly declared tool adapters registered in domain physics — no free-form URL construction from user input; core engine makes no outbound network calls; LLM API endpoint is a single configured provider URL, not user-controlled |

---

## E. Operational Implications

Zero-trust is not just an architecture property — it has concrete operational consequences for how Lumina is deployed and operated.

### Pseudonymity by default

The AI layer operates on pseudonymous session tokens. Canonical identity attributes (names, contact details, device IDs) never enter the orchestration layer directly. This means:

- A breach of the AI layer does not expose canonical identity
- Audit logs in the System Logs contain pseudonymous tokens, not personal identifiers
- Linking a session token to a canonical identity requires access to the separate identity store, which has its own access controls

### Append-only accountability

The System Logs cannot be modified. Any attempt to alter a historical record breaks the hash-chain and is detectable by `validate_log_chain`. This provides:

- Tamper-evident audit trails — breaches after the fact cannot cover their tracks
- Escalation history that cannot be backdated or suppressed
- A foundation for compliance audits — auditors read the System Logs with confidence that its content has not been altered

### Escalation as the trust-boundary enforcement action

When the system cannot resolve a situation within the authorized action space — because an invariant would be violated, a scope expansion is requested, or the LLM produced output outside policy — it escalates. It does not improvise. The escalation path terminates at a human Meta Authority.

This means the system's response to an untrusted state is:
1. Log the escalation event to System Log with a full provenance record
2. Halt the D.S.A. action that was attempted
3. Require explicit human authority before the session can proceed

Escalation is the zero-trust principle applied to action authorization: when trust cannot be established through normal channels, the decision is not made — it is deferred to a human.

### Fail-closed defaults

All Lumina security mechanisms fail closed:

- Missing JWT secret → server does not start
- No matching CommitmentRecord → session does not start (when enforcement is enabled)
- RBAC check fails → 403, not a degraded-permission response
- System Log hash-chain break → reported as MISMATCH, not silently ignored

This prevents degraded-security operation modes from becoming invisible steady states.

---

## SEE ALSO

- [`specs/principles-v1.md`](../../specs/principles-v1.md) — universal core engine principles (pseudonymity, append-only accountability, measurement not surveillance)
- [`specs/rbac-spec-v1.md`](../../specs/rbac-spec-v1.md) — RBAC role hierarchy, octal permission model, four-step resolution
- [`standards/lumina-core-v1.md`](../../standards/lumina-core-v1.md) — system log, policy commitment gate, system physics hash, dual-ledger cross-reference chain
- [`standards/system-log-v1.md`](../../standards/system-log-v1.md) — System Log hash-chain specification, record types, append-only guarantees
- [`docs/3-functions/auth.md`](../3-functions/auth.md) — JWT implementation, password hashing, token refresh
- [`docs/3-functions/permissions.md`](../3-functions/permissions.md) — `check_permission()` resolver, `Operation` flags, ACL override
- [`docs/8-admin/rbac-administration.md`](../8-admin/rbac-administration.md) — role assignment, bootstrap mode, credential rotation procedures
- [NIST SP 800-207](https://doi.org/10.6028/NIST.SP.800-207) — Zero Trust Architecture (NIST Special Publication)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/) — Open Web Application Security Project Top 10

### 🛡️ Security Philosophy

Project Lumina is designed with **Defensive AI Architecture** at its core. Our security model assumes that Large Language Models are inherently untrustworthy and will attempt to drift. Security in Lumina is not about making the AI "safe"; it is about ensuring the **D.S.A. Orchestrator** strictly bounds the AI, and the **System Logs** cryptographically records every deviation.

If a vulnerability allows the AI to bypass its prompt contract, evade the System Logs, or escalate its authority without authorization, it is treated as a critical severity issue.

---

### 🟢 Supported Versions

Currently, Project Lumina is in experimental pre-release. Only the latest commit on the `main` branch is actively supported for security updates.

| Version | Supported          |
| ---     | ---                |
| v0.x    | :white_check_mark: |
| < v0.1  | :x:                |

---

### 🚨 Out-of-Scope Vulnerabilities (By Design)

Because of our "Measurement, not surveillance" and "Pseudonymity by default" principles, the following are **not** considered vulnerabilities of the core engine, provided the engine is functioning as designed:

1. **AI Hallucinations / Drift:** LLMs hallucinating is expected. It is only a security vulnerability if the Orchestrator fails to halt the session, trigger an `EscalationRecord`, and log the hash to the System Logs.
2. **Domain Pack Logic Flaws:** If a Domain Authority writes a flawed `domain-physics.json` that permits unsafe actions, that is a domain-level policy failure, not a core engine vulnerability.
3. **Upstream LLM Provider Outages:** Failures by OpenAI or Anthropic APIs.

---

### 🎯 In-Scope Threat Model (What to Report)

We are highly interested in vulnerabilities that compromise the **Fractal Authority Structure** or the **Traceability** of the engine. Please report:

#### 1. Contract Bypasses & Prompt Injection

* Techniques that allow the LLM to ignore the `orchestrator-system-prompt-v1.md` or execute actions not explicitly mapped in the `runtime-config.yaml`.
* "Jailbreaks" that successfully force the engine to execute unauthorized tool adapters.

#### 2. System Logs Compromise

* Ways to silently drop `TraceEvent` logs without halting the system.
* Methods to manipulate, rewrite, or forge the cryptographic hash-chain of a session.
* Bypassing the append-only nature of the ledger.

#### 3. Privacy & State Leaks

* Forcing the engine to store raw chat transcripts or PII at rest (violating the "pseudonymity by default" rule).
* Cross-session state contamination (e.g., Session A accessing `user.json` data from Session B).

#### 4. Privilege Escalation

* An operator (Micro Authority) finding a way to rewrite the `domain-physics.json` or override the constraints set by the Meso/Macro Authority.

---

### 🛠️ Reporting a Vulnerability

**Do not open a public issue for a critical framework bypass.** If you discover a vulnerability that compromises the System Logs or allows unlogged contract escapes, please report it via email to the core maintainers.

1. **Email:** [fractalsense6@gmail.com]
2. **Subject Line:** `[SECURITY] Lumina Framework Vulnerability: <Brief Description>`
3. **Payload:** Please include:
* A clear description of the vulnerability.
* Steps to reproduce the bypass (preferably using the `run-preintegration-scenarios.ps1` deterministic test suite).
* A copy of the specific `trace-event-schema.json` output showing the failure, if applicable.



You should receive an acknowledgment within 48 hours. We will validate the issue, determine the root cause in the orchestrator pipeline, and issue a patch.

---

### 📜 Audit & Rollback Policies

If a severe contract bypass is discovered in production, the standard operating procedure is to trigger a **Hard Escalation** across all active sessions, halt the orchestrator, and use the System Logs to isolate the specific causal trace of the failure before rolling back to the previous stable engine state. See `governance/audit-and-rollback.md` for full operational procedures.

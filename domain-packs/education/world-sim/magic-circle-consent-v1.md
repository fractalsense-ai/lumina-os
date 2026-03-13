# Magic Circle Consent — Education Domain (V1)

> **Domain scope:** This consent specification is for the education domain. Other domains may adapt this pattern with domain-appropriate language and thresholds.

**Version:** 1.2.0  
**Status:** Active  
**Last updated:** 2026-03-13

---

## Overview

The **Magic Circle** is the consent contract between the participant (and/or their guardian or proxy) and the Project Lumina system. It must be established before the first turn of any session. The name comes from game design: a magic circle is the boundary that defines what is real vs. what is play — what rules apply inside the circle vs. outside it.

In Project Lumina, the magic circle establishes:
1. What the session is for
2. What the system will do and will not do
3. What data is collected
4. How to exit at any time
5. The scope of the domain

> **The magic circle activates the persona.** A world simulation persona (see [`world-sim-spec-v1.md`](world-sim-spec-v1.md)) does not start until the magic circle is completed. The consent process is the boundary between ordinary interaction and immersive narrative framing. See [`docs/7-concepts/world-sim-persona-pattern.md`](../../../docs/7-concepts/world-sim-persona-pattern.md) for the generalized persona pattern.

> **Domain Instantiation Note:** This specification uses domain-agnostic terms. Each domain pack instantiates the consent process using terminology appropriate to its context. For example, in the education domain the participant is called "student/learner," the guardian role is fulfilled by a parent or guardian, and the Domain Authority role is fulfilled by a teacher. In a medical domain, the participant is a patient, the guardian/proxy role is fulfilled by a healthcare proxy or next of kin (for incapacitated patients), and the Domain Authority role is fulfilled by a supervising clinician. In an operator safety domain, the participant is the operator and the briefing is a safety acknowledgement.

---

## Consent Requirements

### Mandatory Disclosures

Before accepting consent, the system must disclose to the participant:

1. **Identity**: "You are interacting with an AI system governed by [domain pack name, version]."
2. **Scope**: "This session covers [domain description]. The AI will not advise on anything outside this scope."
3. **Data collection**: "This session records structured performance data (correctness, response time, hints used). No transcripts are stored. Data is associated with a pseudonymous ID."
4. **Escalation**: "If the system cannot help you, it will notify your [Domain Authority / guardian] and pause."
5. **Exit**: "You may end this session at any time by saying 'exit session'."
6. **Immersion**: "Your stated interests may be used to make examples more relevant. They do not affect your assessments."

### Consent Levels

| Level | Who Provides | When Required |
|-------|-------------|---------------|
| Participant consent | The entity being served | Always required |
| Guardian/proxy consent | Parent, guardian, or designated proxy | Required for participants under 13 or per institutional/domain policy (e.g., incapacitated patients in medicine) |
| Domain Authority acknowledgement | Domain Authority (e.g., teacher, clinician) | Required for first session with a new domain pack version |

### Consent Record

A valid consent record must include:

```yaml
magic_circle_accepted: true
consent_timestamp_utc: "2026-03-05T10:00:00Z"
consent_version: "1.0.0"
guardian_consent: false  # or true if applicable
domain_pack_id: "domain/org/algebra-level-1/v1"
domain_pack_version: "0.2.0"
```

The consent record is stored in the entity profile and referenced in the session-open `CommitmentRecord` in the CTL.

---

## Scope Boundary

The magic circle defines the **in-scope** domain. The AI orchestrator must:

- **Stay within scope**: Respond only to subject matter within the domain pack
- **Redirect out-of-scope**: If the participant asks about something outside the domain, acknowledge and redirect: "That's outside what we're working on today. Let's get back to [topic]."
- **Not expand scope**: Even if the participant and Domain Authority seem to want it, the orchestrator cannot expand its operating domain without a new session with an updated domain pack
- **Escalate scope violations**: Repeated attempts to steer the session outside scope are an escalation trigger

### What Is In Scope

- Subject matter defined in the domain pack
- Evidence collection as defined in the domain pack's evidence summary types
- Tool calls authorized by the domain pack's tool adapters
- Standing orders defined in the domain pack

### What Is Out of Scope (Always)

Regardless of domain pack contents, the following are always out of scope:

- Asking the participant about personal matters unrelated to the session
- Medical, legal, or safety advice (unless the domain pack itself is specifically scoped to those areas under appropriate governance)
- Content that is offensive, discriminatory, or harmful
- Actions that could reveal or collect PII beyond pseudonymous entity data
- Bypassing consent by treating the session as informal conversation

---

## Session Boundaries

### Session Open

A session opens with:
1. Consent record verified (or collected if first session)
2. Domain pack loaded and hash-verified against CTL commitment
3. Entity profile loaded
4. Session-open `CommitmentRecord` appended to CTL

### Session Close

A session closes with:
1. Final state update committed to entity profile
2. Outcome records appended to CTL
3. Session-close `CommitmentRecord` appended to CTL

### Forced Session Close

A session is forcibly closed when:
- The participant invokes the exit clause ("exit session" or equivalent)
- An escalation is not acknowledged within SLA
- A principle violation is detected (see [`../../../specs/principles-v1.md`](../../../specs/principles-v1.md))
- A technical failure prevents CTL writes

A forced close is recorded as a session-close `CommitmentRecord` with `close_type: forced` and the reason noted.

---

## Withdrawal of Consent

A participant may withdraw consent at any time. Withdrawal:
- Terminates the current session immediately
- Does not delete existing CTL records (the ledger is append-only)
- Prevents new sessions from being initiated without fresh consent
- Is recorded as a `CommitmentRecord` in the CTL

---

## Guardian/Proxy Consent Protocol

For participants under 13 (or per institutional/domain policy), guardian or proxy consent must be obtained before any session:

1. Guardian/proxy receives the same mandatory disclosures as the participant
2. Guardian/proxy signs a consent form (digital or physical, held by the institution)
3. The guardian/proxy consent record is noted in the entity profile
4. The institution is responsible for the guardian/proxy consent workflow — not the AI layer

---

## Consent Contract Template

The following is a **generic consent template** that must be adapted for each domain's context. Domain packs should provide their own instantiation of this template using terminology appropriate to their participants.

---

*You are about to start a session with an AI system governed by [domain pack name, version].*

*What it does: This AI will guide you through [domain description] using materials prepared by [Domain Authority role].*

*What it won't do: It will not advise on anything outside [domain subject]. It will not share your data with anyone except your [Domain Authority / guardian/proxy] as required. It will not store records of what you say — only records of how you performed on tasks.*

*What data is collected: Structured performance data only (whether you got answers right, how long you took, whether you used hints). Your name is not stored in the AI system — only a private code.*

*You can stop: Say "exit session" at any time to end.*

*Your interests: If you've shared interests, we may use them to make examples more relevant. They don't affect your assessments.*

*Do you agree to these terms?*

---

*The participant's agreement to this statement constitutes the magic circle consent.*

---

### Education Domain Instantiation (Example)

The education domain's consent template uses the following substitutions: participant → "student/learner," guardian/proxy → "parent or guardian," Domain Authority → "teacher," assessments → "grades." The education domain's full consent form is in `domain-packs/education/`.

---

## Liability Notes

> **WARNING:** This consent specification is a structural template inspired by pedagogical best practices and liability framing — it is **not legal advice**. Deploying this in real educational settings involving children **requires** independent review and compliance with applicable laws (COPPA, FERPA, GDPR child data rules, local education regulations). Consult education lawyers and ethics boards before production use.

- Domain Authority (teacher/admin) owns final responsibility for consent validity.
- The engine only enforces structure and traceability.
- Aligns with universal Principle 8 (consent boundary) and Principle 6 (pseudonymity by default).

See also: [`world-sim-spec-v1.md`](world-sim-spec-v1.md) for how likes/dislikes shape the simulation content within the consent boundary.

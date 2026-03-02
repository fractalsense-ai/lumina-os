# Magic Circle Consent — V1

**Version:** 1.0.0  
**Status:** Active  
**Last updated:** 2026-03-02

---

## Overview

The **Magic Circle** is the consent contract between the learner (and/or their guardian) and the Project Lumina system. It must be established before the first turn of any session. The name comes from game design: a magic circle is the boundary that defines what is real vs. what is play — what rules apply inside the circle vs. outside it.

In Project Lumina, the magic circle establishes:
1. What the session is for
2. What the system will do and will not do
3. What data is collected
4. How to exit at any time
5. The scope of the domain

---

## Consent Requirements

### Mandatory Disclosures

Before accepting consent, the system must disclose to the learner:

1. **Identity**: "You are interacting with an AI system governed by [domain pack name, version]."
2. **Scope**: "This session covers [domain description]. The AI will not advise on anything outside this scope."
3. **Data collection**: "This session records structured performance data (correctness, response time, hints used). No transcripts are stored. Data is associated with a pseudonymous ID."
4. **Escalation**: "If the system cannot help you, it will notify your [teacher/guardian/Domain Authority] and pause."
5. **Exit**: "You may end this session at any time by saying 'exit session'."
6. **Immersion**: "Your stated interests may be used to make examples more relevant. They do not affect your grades or assessments."

### Consent Levels

| Level | Who Provides | When Required |
|-------|-------------|---------------|
| Student consent | Learner | Always required |
| Guardian consent | Parent/guardian | Required for learners under 13 (or per institutional policy) |
| Domain Authority acknowledgement | Teacher | Required for first session with a new domain pack version |

### Consent Record

A valid consent record must include:

```yaml
magic_circle_accepted: true
consent_timestamp_utc: "2026-03-02T10:00:00Z"
consent_version: "1.0.0"
guardian_consent: false  # or true if applicable
domain_pack_id: "domain/org/algebra-level-1/v1"
domain_pack_version: "0.2.0"
```

The consent record is stored in the student profile and referenced in the session-open `CommitmentRecord` in the CTL.

---

## Scope Boundary

The magic circle defines the **in-scope** domain. The AI orchestrator must:

- **Stay within scope**: Respond only to subject matter within the domain pack
- **Redirect out-of-scope**: If the learner asks about something outside the domain, acknowledge and redirect: "That's outside what we're working on today. Let's get back to [topic]."
- **Not expand scope**: Even if the learner and teacher seem to want it, the orchestrator cannot expand its operating domain without a new session with an updated domain pack
- **Escalate scope violations**: Repeated attempts to steer the session outside scope are an escalation trigger

### What Is In Scope

- Subject matter defined in the domain pack
- Evidence collection as defined in the domain pack's evidence summary types
- Tool calls authorized by the domain pack's tool adapters
- Standing orders defined in the domain pack

### What Is Out of Scope (Always)

Regardless of domain pack contents, the following are always out of scope:

- Asking the learner about personal matters unrelated to learning
- Medical, legal, or safety advice
- Content that is offensive, discriminatory, or harmful
- Actions that could reveal or collect PII beyond pseudonymous student data
- Bypassing consent by treating the session as informal conversation

---

## Session Boundaries

### Session Open

A session opens with:
1. Consent record verified (or collected if first session)
2. Domain pack loaded and hash-verified against CTL commitment
3. Student profile loaded
4. Session-open `CommitmentRecord` appended to CTL

### Session Close

A session closes with:
1. Final state update committed to student profile
2. Outcome records appended to CTL
3. Session-close `CommitmentRecord` appended to CTL

### Forced Session Close

A session is forcibly closed when:
- The learner invokes the exit clause ("exit session" or equivalent)
- An escalation is not acknowledged within SLA
- A principle violation is detected (see [`principles-v1.md`](principles-v1.md))
- A technical failure prevents CTL writes

A forced close is recorded as a session-close `CommitmentRecord` with `close_type: forced` and the reason noted.

---

## Withdrawal of Consent

A learner may withdraw consent at any time. Withdrawal:
- Terminates the current session immediately
- Does not delete existing CTL records (the ledger is append-only)
- Prevents new sessions from being initiated without fresh consent
- Is recorded as a `CommitmentRecord` in the CTL

---

## Guardian Consent Protocol

For learners under 13 (or per institutional policy), guardian consent must be obtained before any session:

1. Guardian receives the same mandatory disclosures as the learner
2. Guardian signs a consent form (digital or physical, held by the institution)
3. The guardian consent record is noted in the student profile
4. The institution is responsible for the guardian consent workflow — not the AI layer

---

## Consent Contract Template

The following is the canonical consent statement that must be presented to learners. Domain Authorities may adapt the bracketed fields:

---

*You are about to start a session with an AI tutoring system.*

*What it does: This AI will guide you through [domain description] using materials prepared by [Domain Authority role].*

*What it won't do: It will not advise on anything outside [domain subject]. It will not share your data with anyone except your [teacher/guardian] as required. It will not store records of what you say — only records of how you performed on tasks.*

*What data is collected: Structured performance data only (whether you got answers right, how long you took, whether you used hints). Your name is not stored in the AI system — only a private code.*

*You can stop: Say "exit session" at any time to end.*

*Your interests: If you've shared interests (like sports or space), we may use them to make examples more interesting. They don't affect your grades.*

*Do you agree to these terms?*

---

*The learner's agreement to this statement constitutes the magic circle consent.*

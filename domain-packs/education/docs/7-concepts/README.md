# Education Domain — Concepts (Section 7)

Architectural rationale and design concepts specific to the education domain.

| Concept | Description |
|---------|-------------|
| **ZPD theory and drift monitoring** | Zone of Proximal Development tracking — the ZPD monitor estimates the student's current capability boundary and flags drift when challenge levels diverge from the zone. See `domain-lib/zpd-monitor-spec-v1.md` and `controllers/zpd_monitor_v0_2.py` |
| **Fluency gating and tier progression** | Consecutive-success fluency gate — students must demonstrate procedural fluency (N correct solves within a time threshold) before advancing to harder tiers. See [`fluency-monitor(3)`](../3-functions/fluency-monitor.md) |
| **Vocabulary growth tracking** | Passive vocabulary complexity monitor — client-side analysis produces structured complexity scores; the server tracks growth delta against a locked baseline. See [`vocabulary-growth-monitor(3)`](../3-functions/vocabulary-growth-monitor.md) |
| **Domain API route handlers** | Education-specific HTTP endpoints declared in `cfg/runtime-config.yaml §adapters.api_routes` and implemented in `controllers/api_handlers.py`. The core server mounts these at startup with auth/role enforcement. See [`api-server-architecture(7)`](../../../../docs/7-concepts/api-server-architecture.md) §G |

For cross-domain concepts (domain pack anatomy, NLP semantic routing, system logging), see
the root [`docs/7-concepts/`](../../../../docs/7-concepts/).

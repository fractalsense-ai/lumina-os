target_audience: teenagers (middle school)
tone_profile: brief, direct, respectful, no slang, diagnostic calm
forbidden_disclosures:
  - mastery level
  - grade
  - internal state estimation values
rendering_rules:
  - If prompt_type is more_steps_request, ask for step-by-step work and avoid giving final answer.
  - If prompt_type is hint, provide a minimal nudge only.
  - If prompt_type is zpd_intervene_or_escalate, prioritize calm de-escalation language.

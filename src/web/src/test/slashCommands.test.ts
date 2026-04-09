import { describe, expect, it } from 'vitest'

import {
  parseSlashCommand,
  getCommandsForRole,
  generateHelpText,
} from '@/services/slashCommands'

// ── parseSlashCommand — basic dispatch ───────────────────

describe('parseSlashCommand', () => {
  it('returns null for non-slash input', () => {
    expect(parseSlashCommand('hello world')).toBeNull()
    expect(parseSlashCommand('')).toBeNull()
    expect(parseSlashCommand('  ')).toBeNull()
  })

  it('returns null for unknown commands', () => {
    expect(parseSlashCommand('/nonexistent')).toBeNull()
  })

  it('parses zero-arg commands', () => {
    const result = parseSlashCommand('/domains')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('list_domains')
    expect(result!.params).toEqual({})
  })

  it('parses single-arg commands', () => {
    const result = parseSlashCommand('/join teacher123')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('request_teacher_assignment')
    expect(result!.params).toEqual({ teacher_id: 'teacher123' })
  })

  it('merges defaultParams', () => {
    const result = parseSlashCommand('/teachers')
    expect(result).not.toBeNull()
    expect(result!.params).toEqual({ domain_role: 'teacher', domain_id: 'education' })
  })

  it('resolves aliases', () => {
    const result = parseSlashCommand('/list_commands')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('list_commands')
  })

  it('is case-insensitive for command name', () => {
    const result = parseSlashCommand('/DOMAINS')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('list_domains')
  })

  it('handles client-side /help', () => {
    const result = parseSlashCommand('/help')
    expect(result).not.toBeNull()
    expect(result!.operation).toBeNull()
  })
})

// ── New HITL-exempt operations ──────────────────────────

describe('parseSlashCommand — new exempt operations', () => {
  it('/ingestions with optional args', () => {
    const none = parseSlashCommand('/ingestions')
    expect(none!.operation).toBe('list_ingestions')
    expect(none!.params).toEqual({})

    const withDomain = parseSlashCommand('/ingestions education')
    expect(withDomain!.params).toEqual({ domain_id: 'education' })

    const withBoth = parseSlashCommand('/ingestions education pending')
    expect(withBoth!.params).toEqual({ domain_id: 'education', status: 'pending' })
  })

  it('/review_ingestion <ingestion_id>', () => {
    const result = parseSlashCommand('/review_ingestion ing-001')
    expect(result!.operation).toBe('review_ingestion')
    expect(result!.params).toEqual({ ingestion_id: 'ing-001' })
  })

  it('/proposals [domain_id]', () => {
    const result = parseSlashCommand('/proposals education')
    expect(result!.operation).toBe('review_proposals')
    expect(result!.params).toEqual({ domain_id: 'education' })
  })

  it('/module_status <domain_id> [module_id]', () => {
    const result = parseSlashCommand('/module_status education algebra-1')
    expect(result!.operation).toBe('module_status')
    expect(result!.params).toEqual({ domain_id: 'education', module_id: 'algebra-1' })
  })

  it('/daemon_status', () => {
    const result = parseSlashCommand('/daemon_status')
    expect(result!.operation).toBe('daemon_status')
    expect(result!.params).toEqual({})
  })

  it('/explain <event_id>', () => {
    const result = parseSlashCommand('/explain evt-abc')
    expect(result!.operation).toBe('explain_reasoning')
    expect(result!.params).toEqual({ event_id: 'evt-abc' })
  })

  it('/explain alias explain_reasoning', () => {
    const result = parseSlashCommand('/explain_reasoning evt-xyz')
    expect(result!.operation).toBe('explain_reasoning')
    expect(result!.params).toEqual({ event_id: 'evt-xyz' })
  })

  it('/roles <domain_id>', () => {
    const result = parseSlashCommand('/roles education')
    expect(result!.operation).toBe('list_domain_rbac_roles')
    expect(result!.params).toEqual({ domain_id: 'education' })
  })

  it('/manifest <domain_id>', () => {
    const result = parseSlashCommand('/manifest agriculture')
    expect(result!.operation).toBe('get_domain_module_manifest')
    expect(result!.params).toEqual({ domain_id: 'agriculture' })
  })

  it('/physics <domain_id> [module_id]', () => {
    const result = parseSlashCommand('/physics education algebra-1')
    expect(result!.operation).toBe('get_domain_physics')
    expect(result!.params).toEqual({ domain_id: 'education', module_id: 'algebra-1' })
  })

  it('/daemon_tasks', () => {
    const result = parseSlashCommand('/daemon_tasks')
    expect(result!.operation).toBe('list_daemon_tasks')
    expect(result!.params).toEqual({})
  })

  it('/approve <ingestion_id> <interpretation_id>', () => {
    const result = parseSlashCommand('/approve ing-001 interp-002')
    expect(result!.operation).toBe('approve_interpretation')
    expect(result!.params).toEqual({ ingestion_id: 'ing-001', interpretation_id: 'interp-002' })
  })
})

// ── New HITL-required (mutating) operations ─────────────

describe('parseSlashCommand — new HITL-required operations', () => {
  it('/commit_physics <domain_id>', () => {
    const result = parseSlashCommand('/commit_physics education')
    expect(result!.operation).toBe('commit_domain_physics')
    expect(result!.params).toEqual({ domain_id: 'education' })
  })

  it('/update_role <user_id> <new_role>', () => {
    const result = parseSlashCommand('/update_role user-123 domain_authority')
    expect(result!.operation).toBe('update_user_role')
    expect(result!.params).toEqual({ user_id: 'user-123', new_role: 'domain_authority' })
  })

  it('/deactivate <user_id>', () => {
    const result = parseSlashCommand('/deactivate user-456')
    expect(result!.operation).toBe('deactivate_user')
    expect(result!.params).toEqual({ user_id: 'user-456' })
  })

  it('/assign_role <user_id> <module_id> <domain_role>', () => {
    const result = parseSlashCommand('/assign_role user-789 algebra-1 teacher')
    expect(result!.operation).toBe('assign_domain_role')
    expect(result!.params).toEqual({ user_id: 'user-789', module_id: 'algebra-1', domain_role: 'teacher' })
  })

  it('/revoke_role <user_id> <module_id>', () => {
    const result = parseSlashCommand('/revoke_role user-789 algebra-1')
    expect(result!.operation).toBe('revoke_domain_role')
    expect(result!.params).toEqual({ user_id: 'user-789', module_id: 'algebra-1' })
  })

  it('/trigger_daemon [domain_id] [tasks]', () => {
    const result = parseSlashCommand('/trigger_daemon education ingestion_sweep')
    expect(result!.operation).toBe('trigger_daemon_task')
    expect(result!.params).toEqual({ domain_id: 'education', tasks: 'ingestion_sweep' })
  })
})

// ── joinTrailingArgs — multi-word last arg ──────────────

describe('parseSlashCommand — joinTrailingArgs', () => {
  it('/resolve joins rationale from remaining tokens', () => {
    const result = parseSlashCommand('/resolve esc-001 approved Student met all requirements this term')
    expect(result!.operation).toBe('resolve_escalation')
    expect(result!.params).toEqual({
      escalation_id: 'esc-001',
      resolution: 'approved',
      rationale: 'Student met all requirements this term',
    })
  })

  it('/reject joins reason from remaining tokens', () => {
    const result = parseSlashCommand('/reject ing-007 Insufficient evidence to support claim')
    expect(result!.operation).toBe('reject_ingestion')
    expect(result!.params).toEqual({
      ingestion_id: 'ing-007',
      reason: 'Insufficient evidence to support claim',
    })
  })

  it('/update_physics transforms key+value into updates object', () => {
    const result = parseSlashCommand('/update_physics education max_retries 5')
    expect(result!.operation).toBe('update_domain_physics')
    expect(result!.params.domain_id).toBe('education')
    // key/value should be collapsed into updates JSON
    expect(result!.params.updates).toBeDefined()
    const updates = JSON.parse(result!.params.updates)
    expect(updates).toEqual({ max_retries: 5 })
    expect(result!.params.key).toBeUndefined()
    expect(result!.params.value).toBeUndefined()
  })

  it('/update_physics with string value', () => {
    const result = parseSlashCommand('/update_physics education label My Domain Label')
    expect(result!.operation).toBe('update_domain_physics')
    const updates = JSON.parse(result!.params.updates)
    expect(updates).toEqual({ label: 'My Domain Label' })
  })
})

// ── Alias coverage ──────────────────────────────────────

describe('parseSlashCommand — alias coverage', () => {
  const aliasTests: [string, string][] = [
    ['/list_ingestions', 'list_ingestions'],
    ['/review_proposals', 'review_proposals'],
    ['/explain_reasoning evt-1', 'explain_reasoning'],
    ['/list_domain_rbac_roles education', 'list_domain_rbac_roles'],
    ['/get_domain_module_manifest education', 'get_domain_module_manifest'],
    ['/get_domain_physics education', 'get_domain_physics'],
    ['/list_daemon_tasks', 'list_daemon_tasks'],
    ['/approve_interpretation ing-1 interp-1', 'approve_interpretation'],
    ['/commit_domain_physics education', 'commit_domain_physics'],
    ['/update_user_role user-1 root', 'update_user_role'],
    ['/deactivate_user user-1', 'deactivate_user'],
    ['/assign_domain_role user-1 mod-1 teacher', 'assign_domain_role'],
    ['/revoke_domain_role user-1 mod-1', 'revoke_domain_role'],
    ['/resolve_escalation esc-1 approved ok', 'resolve_escalation'],
    ['/reject_ingestion ing-1 bad', 'reject_ingestion'],
    ['/trigger_daemon_task education sweep', 'trigger_daemon_task'],
  ]

  for (const [input, expectedOp] of aliasTests) {
    it(`${input} → ${expectedOp}`, () => {
      const result = parseSlashCommand(input)
      expect(result).not.toBeNull()
      expect(result!.operation).toBe(expectedOp)
    })
  }
})

// ── getCommandsForRole ──────────────────────────────────

describe('getCommandsForRole', () => {
  it('root sees root-only commands', () => {
    const cmds = getCommandsForRole('root')
    const names = cmds.map((c) => c.name)
    expect(names).toContain('update_role')
    expect(names).toContain('deactivate')
  })

  it('student does not see root-only commands', () => {
    const cmds = getCommandsForRole('student')
    const names = cmds.map((c) => c.name)
    expect(names).not.toContain('update_role')
    expect(names).not.toContain('deactivate')
  })

  it('domain_authority sees DA-level commands', () => {
    const cmds = getCommandsForRole('domain_authority')
    const names = cmds.map((c) => c.name)
    expect(names).toContain('assign_role')
    expect(names).toContain('revoke_role')
    expect(names).toContain('resolve')
    expect(names).toContain('reject')
    expect(names).toContain('trigger_daemon')
    expect(names).toContain('approve')
  })

  it('everyone sees commands with empty allowedRoles', () => {
    const cmds = getCommandsForRole('guest')
    const names = cmds.map((c) => c.name)
    expect(names).toContain('help')
    expect(names).toContain('profile')
    expect(names).toContain('explain')
    expect(names).toContain('module_status')
  })
})

// ── generateHelpText ────────────────────────────────────

describe('generateHelpText', () => {
  it('includes arg hints for parameterised commands', () => {
    const text = generateHelpText('domain_authority')
    expect(text).toContain('`/resolve <escalation_id> <resolution> <rationale>`')
    expect(text).toContain('`/reject <ingestion_id> <reason>`')
    expect(text).toContain('`/assign_role <user_id> <module_id> <domain_role>`')
  })

  it('shows aliases', () => {
    const text = generateHelpText('domain_authority')
    expect(text).toContain('also: /resolve_escalation')
    expect(text).toContain('also: /reject_ingestion')
  })
})

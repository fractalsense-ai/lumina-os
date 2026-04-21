import { describe, expect, it, beforeAll, afterAll } from 'vitest'

import {
  parseSlashCommand,
  getCommandsForRole,
  generateHelpText,
} from '@/services/slashCommands'
import { registerPlugin, _resetForTesting } from '@/plugins/PluginRegistry'
import type { DomainPlugin } from '@/plugins/types'

// Education plugin commands (mirroring domain-packs/education/web/plugin.ts)
const educationPlugin: DomainPlugin = {
  id: 'education-test',
  register(reg) {
    reg.addSlashCommands([
      {
        name: 'teachers',
        operation: 'list_users',
        description: 'Show available teachers',
        args: [],
        defaultParams: { domain_role: 'teacher', domain_id: 'education' },
        allowedRoles: ['student', 'guardian', 'teaching_assistant', 'teacher', 'domain_authority'],
        domainScope: 'education',
        aliases: ['list_teachers'],
        tier: 'user',
      },
      {
        name: 'join',
        operation: 'request_teacher_assignment',
        description: 'Request assignment to a teacher or teaching assistant',
        args: ['teacher_id'],
        allowedRoles: ['student'],
        domainScope: 'education',
        tier: 'user',
      },
      {
        name: 'students',
        operation: 'list_users',
        description: 'List your students',
        args: [],
        defaultParams: { domain_role: 'student', domain_id: 'education' },
        allowedRoles: ['teaching_assistant', 'teacher', 'domain_authority'],
        domainScope: 'education',
        tier: 'user',
      },
      {
        name: 'assign',
        operation: 'assign_student',
        description: 'Assign a student, TA, guardian, or module(s)',
        args: ['student_id'],
        allowedRoles: ['student', 'teaching_assistant', 'teacher', 'domain_authority'],
        domainScope: 'education',
        tier: 'user',
        subCommands: {
          module: {
            operation: 'assign_module',
            args: ['user_id', 'module_id'],
          },
          modules: {
            operation: 'assign_modules',
            args: ['target', 'module_ids'],
            joinTrailingArgs: true,
          },
          ta: {
            operation: 'assign_ta',
            args: ['ta_id', 'student_ids'],
            joinTrailingArgs: true,
          },
          guardian: {
            operation: 'assign_guardian',
            args: ['guardian_id', 'student_id'],
          },
        },
      },
      {
        name: 'escalations',
        operation: 'list_escalations',
        description: 'List pending escalations',
        args: [],
        allowedRoles: ['teacher', 'domain_authority'],
        aliases: ['list_escalations'],
        domainScope: 'education',
        tier: 'user',
      },
    ])
  },
}

// System plugin role equivalences and commands (mirroring domain-packs/system/web/plugin.ts)
const systemPlugin: DomainPlugin = {
  id: 'system-test',
  register(reg) {
    reg.addSlashCommands([
      {
        name: 'explain',
        operation: 'explain_reasoning',
        description: 'Explain reasoning for a log event',
        args: ['event_id'],
        allowedRoles: ['admin', 'operator'],
        aliases: ['explain_reasoning'],
        tier: 'user',
      },
    ])
    reg.addRoleEquivalences({
      system_admin: 'admin',
      system_operator: 'teacher',
    })
  },
}

// Register plugins for tests that depend on domain commands & role equivalences
beforeAll(() => { registerPlugin(educationPlugin); registerPlugin(systemPlugin) })
afterAll(() => { _resetForTesting() })

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
    const result = parseSlashCommand('/update_role user-123 admin')
    expect(result!.operation).toBe('update_user_role')
    expect(result!.params).toEqual({ user_id: 'user-123', new_role: 'admin' })
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
    // New operation-name aliases
    ['/list_domains', 'list_domains'],
    ['/list_escalations', 'list_escalations'],
    ['/list_users', 'list_users'],
    ['/invite_user alice teacher', 'invite_user'],
    ['/list_modules', 'list_modules'],
    ['/update_domain_physics education label Test', 'update_domain_physics'],
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

  it('admin sees DA-level commands', () => {
    const cmds = getCommandsForRole('admin')
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
    expect(names).toContain('module_status')
    expect(names).toContain('modules')
    // /explain has restricted allowedRoles, so guest should NOT see it
    expect(names).not.toContain('explain')
  })

  it('platformRole root sees ALL commands regardless of effectiveRole', () => {
    const cmds = getCommandsForRole('system_admin', 'root')
    const names = cmds.map((c) => c.name)
    expect(names).toContain('update_role')
    expect(names).toContain('deactivate')
    expect(names).toContain('assign_role')
    expect(names).toContain('domains')
    expect(names).toContain('teachers')
    expect(names).toContain('help')
  })

  it('system_admin maps to admin via plugin role equivalences', () => {
    const cmds = getCommandsForRole('system_admin')
    const names = cmds.map((c) => c.name)
    expect(names).toContain('domains')
    expect(names).toContain('assign_role')
    expect(names).toContain('ingestions')
    // system_admin should NOT see root-only commands without platformRole
    expect(names).not.toContain('update_role')
    // Without a domainKey, education-scoped commands are excluded
    expect(names).not.toContain('teachers')
    expect(names).not.toContain('students')
    expect(names).not.toContain('join')
    expect(names).not.toContain('escalations')
    // /modules is system-wide (no domainScope), visible to all
    expect(names).toContain('modules')
  })

  it('system_operator maps to teacher via plugin role equivalences', () => {
    const cmds = getCommandsForRole('system_operator')
    const names = cmds.map((c) => c.name)
    // Without a domainKey, education-scoped commands (including escalations) are excluded
    expect(names).not.toContain('escalations')
    expect(names).not.toContain('domains')
    expect(names).not.toContain('teachers')
    // /switch is system-wide (no domainScope), visible to all
    expect(names).toContain('switch')
  })
})

// ── getCommandsForRole — domain scoping ─────────────────

describe('getCommandsForRole — domain scoping', () => {
  it('domain_authority on education sees education-scoped commands', () => {
    const cmds = getCommandsForRole('domain_authority', undefined, 'education')
    const names = cmds.map((c) => c.name)
    expect(names).toContain('teachers')
    expect(names).toContain('students')
    expect(names).toContain('modules')
    expect(names).toContain('assign')
    expect(names).toContain('escalations')
    expect(names).toContain('switch')
    // /join is student-only, so domain_authority still doesn't see it
    expect(names).not.toContain('join')
  })

  it('system_admin on system domain does NOT see education-scoped commands', () => {
    const cmds = getCommandsForRole('system_admin', undefined, 'system')
    const names = cmds.map((c) => c.name)
    expect(names).not.toContain('teachers')
    expect(names).not.toContain('students')
    expect(names).not.toContain('assign')
    expect(names).not.toContain('join')
    // /modules and /switch are system-wide (no domainScope), visible in all domains
    expect(names).toContain('modules')
    expect(names).toContain('switch')
    // But still sees non-scoped DA commands
    expect(names).toContain('domains')
    expect(names).toContain('assign_role')
    expect(names).toContain('ingestions')
  })

  it('system_operator on system domain does NOT see education-scoped commands', () => {
    const cmds = getCommandsForRole('system_operator', undefined, 'system')
    const names = cmds.map((c) => c.name)
    expect(names).not.toContain('teachers')
    expect(names).not.toContain('escalations')
    // /switch is system-wide, visible in all domains
    expect(names).toContain('switch')
  })

  it('student on education sees education-scoped student commands', () => {
    const cmds = getCommandsForRole('student', undefined, 'education')
    const names = cmds.map((c) => c.name)
    expect(names).toContain('teachers')
    expect(names).toContain('join')
    expect(names).toContain('modules')
    expect(names).toContain('switch')
  })

  it('platformRole root always sees ALL commands regardless of domainKey', () => {
    const cmds = getCommandsForRole('system_admin', 'root', 'system')
    const names = cmds.map((c) => c.name)
    expect(names).toContain('teachers')
    expect(names).toContain('students')
    expect(names).toContain('modules')
    expect(names).toContain('update_role')
    expect(names).toContain('domains')
  })

  it('commands without domainScope are visible on any domain', () => {
    const eduCmds = getCommandsForRole('admin', undefined, 'education')
    const sysCmds = getCommandsForRole('system_admin', undefined, 'system')
    const eduNames = eduCmds.map((c) => c.name)
    const sysNames = sysCmds.map((c) => c.name)
    // Non-scoped commands appear in both
    expect(eduNames).toContain('domains')
    expect(sysNames).toContain('domains')
    expect(eduNames).toContain('help')
    expect(sysNames).toContain('help')
  })
})

// ── generateHelpText ────────────────────────────────────

describe('generateHelpText', () => {
  it('includes arg hints for parameterised commands', () => {
    const text = generateHelpText('admin', undefined, 'education')
    expect(text).toContain('`/resolve <escalation_id> <resolution> <rationale>`')
    expect(text).toContain('`/reject <ingestion_id> <reason>`')
    expect(text).toContain('`/assign_role <user_id> <module_id> <domain_role>`')
  })

  it('shows aliases', () => {
    const text = generateHelpText('admin', undefined, 'education')
    expect(text).toContain('also: /resolve_escalation')
    expect(text).toContain('also: /reject_ingestion')
  })

  it('shows all commands for platformRole root', () => {
    const text = generateHelpText('system_admin', 'root')
    expect(text).toContain('/update_role')
    expect(text).toContain('/domains')
    expect(text).toContain('/assign_role')
  })

  it('excludes education-scoped commands on system domain for non-root', () => {
    const text = generateHelpText('system_admin', undefined, 'system')
    expect(text).not.toContain('/teachers')
    expect(text).not.toContain('/students')
    // /modules is system-wide, visible in all domains
    expect(text).toContain('/modules')
    expect(text).toContain('/domains')
  })
})

// ── Sub-command routing ─────────────────────────────────

describe('parseSlashCommand — sub-command routing', () => {
  it('/assign without sub-command falls back to assign_student', () => {
    const result = parseSlashCommand('/assign student123')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('assign_student')
    expect(result!.params).toEqual({ student_id: 'student123' })
  })

  it('/assign ta routes to assign_ta', () => {
    const result = parseSlashCommand('/assign ta ta-user stu1,stu2')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('assign_ta')
    expect(result!.params).toEqual({ ta_id: 'ta-user', student_ids: 'stu1,stu2' })
  })

  it('/assign ta with joinTrailingArgs joins remaining tokens', () => {
    const result = parseSlashCommand('/assign ta ta-user stu1 stu2 stu3')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('assign_ta')
    expect(result!.params).toEqual({ ta_id: 'ta-user', student_ids: 'stu1 stu2 stu3' })
  })

  it('/assign guardian routes to assign_guardian', () => {
    const result = parseSlashCommand('/assign guardian parent-jane student-alice')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('assign_guardian')
    expect(result!.params).toEqual({ guardian_id: 'parent-jane', student_id: 'student-alice' })
  })

  it('/assign guardian with only guardian_id (student self-assign)', () => {
    const result = parseSlashCommand('/assign guardian parent-jane')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('assign_guardian')
    expect(result!.params).toEqual({ guardian_id: 'parent-jane' })
  })

  it('/assign module routes to assign_module', () => {
    const result = parseSlashCommand('/assign module user-1 algebra-1')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('assign_module')
    expect(result!.params).toEqual({ user_id: 'user-1', module_id: 'algebra-1' })
  })

  it('/assign modules routes to assign_modules with joinTrailingArgs', () => {
    const result = parseSlashCommand('/assign modules user-1 algebra-1 pre-algebra geometry')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('assign_modules')
    expect(result!.params).toEqual({ target: 'user-1', module_ids: 'algebra-1 pre-algebra geometry' })
  })

  it('/assign with unknown sub-command treats it as student_id', () => {
    const result = parseSlashCommand('/assign unknownstudent')
    expect(result).not.toBeNull()
    expect(result!.operation).toBe('assign_student')
    expect(result!.params).toEqual({ student_id: 'unknownstudent' })
  })
})

/**
 * Slash command parser and registry for the Lumina chat UI.
 *
 * Maps IRC-style "/command" input to structured admin operations
 * that bypass the SLM via direct dispatch.
 */

export interface SlashCommandDef {
  /** The slash command name (without the leading "/"). */
  name: string
  /** Operation name sent to /api/admin/command. Null = client-side only. */
  operation: string | null
  /** Human-readable description shown in help / palette. */
  description: string
  /** Named argument templates — first positional arg maps to the first key. */
  args: string[]
  /** Static params merged into every invocation. */
  defaultParams?: Record<string, string>
  /** Domain roles that may see/execute this command. Empty = all roles. */
  allowedRoles: string[]
  /** Restrict this command to a specific domain key (e.g. 'education'). */
  domainScope?: string
  /** Aliases that also trigger this command. */
  aliases?: string[]
  /** If true, the last arg captures all remaining tokens joined with spaces. */
  joinTrailingArgs?: boolean
}

export interface ParsedSlashCommand {
  /** The matched command definition. */
  def: SlashCommandDef
  /** The operation to dispatch (null for client-only commands like /help). */
  operation: string | null
  /** Merged params ready to POST. */
  params: Record<string, string>
}

// ── Command registry ──────────────────────────────────────

const COMMANDS: SlashCommandDef[] = [
  // ── Student-accessible ─────────────────────────────────
  {
    name: 'teachers',
    operation: 'list_users',
    description: 'Show available teachers',
    args: [],
    defaultParams: { domain_role: 'teacher', domain_id: 'education' },
    allowedRoles: ['student', 'guardian', 'teaching_assistant', 'teacher', 'domain_authority'],
    domainScope: 'education',
    aliases: ['list_teachers'],
  },
  {
    name: 'join',
    operation: 'request_teacher_assignment',
    description: 'Request assignment to a teacher',
    args: ['teacher_id'],
    allowedRoles: ['student'],
    domainScope: 'education',
  },
  {
    name: 'switch',
    operation: 'switch_active_module',
    description: 'Switch your active education module',
    args: ['module_id'],
    allowedRoles: ['student', 'teaching_assistant', 'teacher', 'domain_authority'],
    domainScope: 'education',
  },
  {
    name: 'profile',
    operation: 'view_my_profile',
    description: 'View your own profile',
    args: [],
    allowedRoles: [],
  },
  {
    name: 'modules',
    operation: 'list_modules',
    description: 'List available modules',
    args: [],
    defaultParams: { domain_id: 'education' },
    allowedRoles: ['student', 'teaching_assistant', 'teacher', 'domain_authority'],
    domainScope: 'education',
    aliases: ['list_modules'],
  },
  {
    name: 'preferences',
    operation: 'update_user_preferences',
    description: 'Update a preference (key value)',
    args: ['key', 'value'],
    allowedRoles: [],
  },
  {
    name: 'help',
    operation: null,
    description: 'Show available slash commands',
    args: [],
    allowedRoles: [],
  },
  {
    name: 'commands',
    operation: 'list_commands',
    description: 'List all admin commands from the server',
    args: [],
    allowedRoles: [],
    aliases: ['list_commands'],
  },

  // ── Teacher-accessible ─────────────────────────────────
  {
    name: 'students',
    operation: 'list_users',
    description: 'List your students',
    args: [],
    defaultParams: { domain_role: 'student', domain_id: 'education' },
    allowedRoles: ['teaching_assistant', 'teacher', 'domain_authority'],
    domainScope: 'education',
  },
  {
    name: 'assign',
    operation: 'assign_student',
    description: 'Assign a student to your roster',
    args: ['student_id'],
    allowedRoles: ['teacher', 'domain_authority'],
    domainScope: 'education',
  },

  // ── Governance (DA / root) ─────────────────────────────
  {
    name: 'users',
    operation: 'list_users',
    description: 'List all users',
    args: [],
    allowedRoles: ['domain_authority'],
    aliases: ['list_users'],
  },
  {
    name: 'invite',
    operation: 'invite_user',
    description: 'Invite a new user (username role)',
    args: ['username', 'role'],
    allowedRoles: ['domain_authority'],
    aliases: ['invite_user'],
  },
  {
    name: 'domains',
    operation: 'list_domains',
    description: 'List all domains',
    args: [],
    allowedRoles: ['domain_authority'],
    aliases: ['list_domains'],
  },
  {
    name: 'escalations',
    operation: 'list_escalations',
    description: 'List pending escalations',
    args: [],
    allowedRoles: ['teacher', 'domain_authority'],
    aliases: ['list_escalations'],
  },

  // ── Read-only / HITL-exempt operations ─────────────────
  {
    name: 'ingestions',
    operation: 'list_ingestions',
    description: 'List ingestion records',
    args: ['domain_id', 'status'],
    allowedRoles: ['domain_authority'],
    aliases: ['list_ingestions'],
  },
  {
    name: 'review_ingestion',
    operation: 'review_ingestion',
    description: 'Review an ingestion record',
    args: ['ingestion_id'],
    allowedRoles: ['domain_authority'],
  },
  {
    name: 'proposals',
    operation: 'review_proposals',
    description: 'List pending night-cycle proposals',
    args: ['domain_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['review_proposals'],
  },
  {
    name: 'module_status',
    operation: 'module_status',
    description: 'Check module runtime status',
    args: ['domain_id', 'module_id'],
    allowedRoles: [],
  },
  {
    name: 'daemon_status',
    operation: 'daemon_status',
    description: 'Show daemon scheduler status',
    args: [],
    allowedRoles: ['domain_authority'],
  },
  {
    name: 'explain',
    operation: 'explain_reasoning',
    description: 'Explain reasoning for a log event',
    args: ['event_id'],
    allowedRoles: [],
    aliases: ['explain_reasoning'],
  },
  {
    name: 'roles',
    operation: 'list_domain_rbac_roles',
    description: 'List domain RBAC roles',
    args: ['domain_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['list_domain_rbac_roles'],
  },
  {
    name: 'manifest',
    operation: 'get_domain_module_manifest',
    description: 'Show domain module manifest',
    args: ['domain_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['get_domain_module_manifest'],
  },
  {
    name: 'physics',
    operation: 'get_domain_physics',
    description: 'View domain physics configuration',
    args: ['domain_id', 'module_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['get_domain_physics'],
  },
  {
    name: 'daemon_tasks',
    operation: 'list_daemon_tasks',
    description: 'List available daemon tasks',
    args: [],
    allowedRoles: ['domain_authority'],
    aliases: ['list_daemon_tasks'],
  },
  {
    name: 'approve',
    operation: 'approve_interpretation',
    description: 'Approve an interpretation for an ingestion',
    args: ['ingestion_id', 'interpretation_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['approve_interpretation'],
  },

  // ── Mutating / HITL-required operations ────────────────
  {
    name: 'update_physics',
    operation: 'update_domain_physics',
    description: 'Update domain physics (domain key value)',
    args: ['domain_id', 'key', 'value'],
    allowedRoles: ['domain_authority'],
    joinTrailingArgs: true,
    aliases: ['update_domain_physics'],
  },
  {
    name: 'commit_physics',
    operation: 'commit_domain_physics',
    description: 'Commit pending domain physics changes',
    args: ['domain_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['commit_domain_physics'],
  },
  {
    name: 'update_role',
    operation: 'update_user_role',
    description: 'Change a user platform role (root only)',
    args: ['user_id', 'new_role'],
    allowedRoles: ['root'],
    aliases: ['update_user_role'],
  },
  {
    name: 'deactivate',
    operation: 'deactivate_user',
    description: 'Deactivate a user account (root only)',
    args: ['user_id'],
    allowedRoles: ['root'],
    aliases: ['deactivate_user'],
  },
  {
    name: 'assign_role',
    operation: 'assign_domain_role',
    description: 'Assign domain role to user',
    args: ['user_id', 'module_id', 'domain_role'],
    allowedRoles: ['domain_authority'],
    aliases: ['assign_domain_role'],
  },
  {
    name: 'revoke_role',
    operation: 'revoke_domain_role',
    description: 'Revoke domain role from user',
    args: ['user_id', 'module_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['revoke_domain_role'],
  },
  {
    name: 'resolve',
    operation: 'resolve_escalation',
    description: 'Resolve an escalation (id resolution rationale)',
    args: ['escalation_id', 'resolution', 'rationale'],
    allowedRoles: ['domain_authority'],
    joinTrailingArgs: true,
    aliases: ['resolve_escalation'],
  },
  {
    name: 'reject',
    operation: 'reject_ingestion',
    description: 'Reject an ingestion record with reason',
    args: ['ingestion_id', 'reason'],
    allowedRoles: ['domain_authority'],
    joinTrailingArgs: true,
    aliases: ['reject_ingestion'],
  },
  {
    name: 'trigger_daemon',
    operation: 'trigger_daemon_task',
    description: 'Trigger daemon task run',
    args: ['domain_id', 'tasks'],
    allowedRoles: ['domain_authority'],
    aliases: ['trigger_daemon_task'],
  },
]

// Build a lookup map including aliases
const COMMAND_MAP = new Map<string, SlashCommandDef>()
for (const cmd of COMMANDS) {
  COMMAND_MAP.set(cmd.name, cmd)
  for (const alias of cmd.aliases ?? []) {
    COMMAND_MAP.set(alias, cmd)
  }
}

/**
 * Map non-education domain roles to their equivalent slash-command role.
 * This lets system-domain roles (system_admin, system_operator) see the
 * correct governance or operational commands.
 */
const ROLE_EQUIVALENCE: Record<string, string> = {
  system_admin: 'domain_authority',
  system_operator: 'teacher',
}

/**
 * Get commands visible to a given effective domain role.
 * Empty allowedRoles means visible to everyone.
 *
 * @param effectiveRole  The domain-specific role (e.g. 'student', 'system_admin')
 * @param platformRole   Optional platform-level role from auth (e.g. 'root')
 * @param domainKey      Optional current domain key (e.g. 'education', 'system')
 */
export function getCommandsForRole(effectiveRole: string, platformRole?: string, domainKey?: string): SlashCommandDef[] {
  // Platform root sees every command
  if (platformRole === 'root') return COMMANDS

  const normalizedRole = ROLE_EQUIVALENCE[effectiveRole] ?? effectiveRole
  return COMMANDS.filter(
    (cmd) =>
      (cmd.allowedRoles.length === 0 || cmd.allowedRoles.includes(normalizedRole)) &&
      (!cmd.domainScope || cmd.domainScope === domainKey),
  )
}

/**
 * Parse a slash command string into a structured command, or null if
 * the input doesn't start with "/" or the command is unrecognised.
 */
export function parseSlashCommand(input: string): ParsedSlashCommand | null {
  const trimmed = input.trim()
  if (!trimmed.startsWith('/')) return null

  const parts = trimmed.slice(1).split(/\s+/)
  const commandName = (parts[0] ?? '').toLowerCase()
  if (!commandName) return null

  const def = COMMAND_MAP.get(commandName)
  if (!def) return null

  // Map positional args to named params
  const params: Record<string, string> = { ...(def.defaultParams ?? {}) }
  for (let i = 0; i < def.args.length; i++) {
    if (def.joinTrailingArgs && i === def.args.length - 1) {
      // Last arg captures all remaining tokens
      const rest = parts.slice(i + 1).join(' ')
      if (rest) params[def.args[i]] = rest
    } else {
      const value = parts[i + 1]
      if (value) params[def.args[i]] = value
    }
  }

  // Special: preferences transforms key+value into JSON updates object
  if (def.name === 'preferences' && parts.length > 2) {
    const key = parts[1] ?? ''
    const value = parts.slice(2).join(' ')
    params['updates'] = JSON.stringify({ [key]: value })
    delete params['key']
    delete params['value']
  }

  // Special: update_physics transforms key+value into updates object
  if (def.name === 'update_physics' && params['key'] && params['value']) {
    const key = params['key']
    const value = params['value']
    // Try JSON parse for structured values, fall back to string
    let parsed: unknown = value
    try { parsed = JSON.parse(value) } catch { /* use string */ }
    params['updates'] = JSON.stringify({ [key]: parsed })
    delete params['key']
    delete params['value']
  }

  return { def, operation: def.operation, params }
}

/**
 * Generate the /help response text for a given role.
 */
export function generateHelpText(effectiveRole: string, platformRole?: string, domainKey?: string): string {
  const available = getCommandsForRole(effectiveRole, platformRole, domainKey)
  const lines = ['**Available Commands**', '']
  for (const cmd of available) {
    const argHint = cmd.args.length > 0 ? ' ' + cmd.args.map((a) => `<${a}>`).join(' ') : ''
    const aliases = cmd.aliases?.length ? ` (also: ${cmd.aliases.map((a) => '/' + a).join(', ')})` : ''
    lines.push(`\`/${cmd.name}${argHint}\` — ${cmd.description}${aliases}`)
  }
  return lines.join('\n')
}

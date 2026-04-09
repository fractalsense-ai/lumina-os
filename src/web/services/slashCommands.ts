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
  /** Aliases that also trigger this command. */
  aliases?: string[]
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
    aliases: ['list_teachers'],
  },
  {
    name: 'join',
    operation: 'request_teacher_assignment',
    description: 'Request assignment to a teacher',
    args: ['teacher_id'],
    allowedRoles: ['student'],
  },
  {
    name: 'switch',
    operation: 'switch_active_module',
    description: 'Switch your active education module',
    args: ['module_id'],
    allowedRoles: ['student', 'teaching_assistant', 'teacher', 'domain_authority'],
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
    description: 'List available education modules',
    args: [],
    defaultParams: { domain_id: 'education' },
    allowedRoles: ['student', 'teaching_assistant', 'teacher', 'domain_authority'],
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
  },
  {
    name: 'assign',
    operation: 'assign_student',
    description: 'Assign a student to your roster',
    args: ['student_id'],
    allowedRoles: ['teacher', 'domain_authority'],
  },

  // ── Governance (DA / root) ─────────────────────────────
  {
    name: 'users',
    operation: 'list_users',
    description: 'List all users',
    args: [],
    allowedRoles: ['domain_authority'],
  },
  {
    name: 'invite',
    operation: 'invite_user',
    description: 'Invite a new user (username role)',
    args: ['username', 'role'],
    allowedRoles: ['domain_authority'],
  },
  {
    name: 'domains',
    operation: 'list_domains',
    description: 'List all domains',
    args: [],
    allowedRoles: ['domain_authority'],
  },
  {
    name: 'escalations',
    operation: 'list_escalations',
    description: 'List pending escalations',
    args: [],
    allowedRoles: ['teacher', 'domain_authority'],
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
 * Get commands visible to a given effective domain role.
 * Empty allowedRoles means visible to everyone.
 */
export function getCommandsForRole(effectiveRole: string): SlashCommandDef[] {
  return COMMANDS.filter(
    (cmd) => cmd.allowedRoles.length === 0 || cmd.allowedRoles.includes(effectiveRole),
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
    const value = parts[i + 1]
    if (value) {
      params[def.args[i]] = value
    }
  }

  // For preferences, join remaining args as the value
  if (def.name === 'preferences' && parts.length > 2) {
    const key = parts[1] ?? ''
    const value = parts.slice(2).join(' ')
    params['updates'] = JSON.stringify({ [key]: value })
    delete params['key']
    delete params['value']
  }

  return { def, operation: def.operation, params }
}

/**
 * Generate the /help response text for a given role.
 */
export function generateHelpText(effectiveRole: string): string {
  const available = getCommandsForRole(effectiveRole)
  const lines = ['**Available Commands**', '']
  for (const cmd of available) {
    const argHint = cmd.args.length > 0 ? ' ' + cmd.args.map((a) => `<${a}>`).join(' ') : ''
    const aliases = cmd.aliases?.length ? ` (also: ${cmd.aliases.map((a) => '/' + a).join(', ')})` : ''
    lines.push(`\`/${cmd.name}${argHint}\` — ${cmd.description}${aliases}`)
  }
  return lines.join('\n')
}

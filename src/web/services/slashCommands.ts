/**
 * Slash command parser and registry for the Lumina chat UI.
 *
 * Maps IRC-style "/command" input to structured operations
 * that bypass the SLM via direct dispatch.
 *
 * Commands are routed to one of three tiered endpoints:
 *   /api/command        — user tier  (any authenticated user)
 *   /api/domain/command — domain tier (domain authority+)
 *   /api/admin/command  — admin tier  (root / IT support)
 */

import { getPluginCommands, getPluginRoleEquivalences } from '@/plugins/PluginRegistry'

export type CommandTier = 'user' | 'domain' | 'admin'

export interface SlashCommandDef {
  /** The slash command name (without the leading "/"). */
  name: string
  /** Operation name sent to the command endpoint. Null = client-side only. */
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
  /** Command tier — determines which API endpoint to use. */
  tier: CommandTier
}

export interface ParsedSlashCommand {
  /** The matched command definition. */
  def: SlashCommandDef
  /** The operation to dispatch (null for client-only commands like /help). */
  operation: string | null
  /** Merged params ready to POST. */
  params: Record<string, string>
  /** The API endpoint path for this command's tier. */
  endpoint: string
}

/** Map a command tier to its API endpoint path. */
export function tierEndpoint(tier: CommandTier): string {
  switch (tier) {
    case 'user':   return '/api/command'
    case 'domain': return '/api/domain/command'
    case 'admin':  return '/api/admin/command'
  }
}

// ── Command registry ──────────────────────────────────────

const COMMANDS: SlashCommandDef[] = [
  // ── User tier — any authenticated user ─────────────────
  {
    name: 'switch',
    operation: 'switch_active_module',
    description: 'Switch your active module',
    args: ['module_id'],
    allowedRoles: [],
    tier: 'user',
  },
  {
    name: 'profile',
    operation: 'view_my_profile',
    description: 'View your own profile',
    args: [],
    allowedRoles: [],
    tier: 'user',
  },
  {
    name: 'modules',
    operation: 'list_modules',
    description: 'List modules in the active domain (or specify a domain)',
    args: ['domain_id'],
    allowedRoles: [],
    aliases: ['list_modules'],
    tier: 'user',
  },
  {
    name: 'preferences',
    operation: 'update_user_preferences',
    description: 'Update a preference (key value)',
    args: ['key', 'value'],
    allowedRoles: [],
    tier: 'user',
  },
  {
    name: 'help',
    operation: null,
    description: 'Show available slash commands',
    args: [],
    allowedRoles: [],
    tier: 'user',
  },
  {
    name: 'commands',
    operation: 'list_commands',
    description: 'List all commands from the server',
    args: [],
    allowedRoles: [],
    aliases: ['list_commands'],
    tier: 'user',
  },

  {
    name: 'module_status',
    operation: 'module_status',
    description: 'Check module runtime status',
    args: ['domain_id', 'module_id'],
    allowedRoles: [],
    tier: 'user',
  },

  // ── Domain tier — domain authority + root ──────────────
  {
    name: 'users',
    operation: 'list_users',
    description: 'List all users',
    args: [],
    allowedRoles: ['domain_authority'],
    aliases: ['list_users'],
    tier: 'domain',
  },
  {
    name: 'invite',
    operation: 'invite_user',
    description: 'Invite a new user (username role)',
    args: ['username', 'role'],
    allowedRoles: ['domain_authority'],
    aliases: ['invite_user'],
    tier: 'domain',
  },
  {
    name: 'domains',
    operation: 'list_domains',
    description: 'List all domains',
    args: [],
    allowedRoles: ['domain_authority'],
    aliases: ['list_domains'],
    tier: 'domain',
  },
  {
    name: 'ingestions',
    operation: 'list_ingestions',
    description: 'List ingestion records',
    args: ['domain_id', 'status'],
    allowedRoles: ['domain_authority'],
    aliases: ['list_ingestions'],
    tier: 'domain',
  },
  {
    name: 'review_ingestion',
    operation: 'review_ingestion',
    description: 'Review an ingestion record',
    args: ['ingestion_id'],
    allowedRoles: ['domain_authority'],
    tier: 'domain',
  },
  {
    name: 'proposals',
    operation: 'review_proposals',
    description: 'List pending daemon proposals',
    args: ['domain_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['review_proposals'],
    tier: 'domain',
  },
  {
    name: 'daemon_status',
    operation: 'daemon_status',
    description: 'Show daemon scheduler status',
    args: [],
    allowedRoles: ['domain_authority'],
    tier: 'domain',
  },
  {
    name: 'roles',
    operation: 'list_domain_rbac_roles',
    description: 'List domain RBAC roles',
    args: ['domain_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['list_domain_rbac_roles'],
    tier: 'domain',
  },
  {
    name: 'manifest',
    operation: 'get_domain_module_manifest',
    description: 'Show domain module manifest',
    args: ['domain_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['get_domain_module_manifest'],
    tier: 'domain',
  },
  {
    name: 'physics',
    operation: 'get_domain_physics',
    description: 'View domain physics configuration',
    args: ['domain_id', 'module_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['get_domain_physics'],
    tier: 'domain',
  },
  {
    name: 'daemon_tasks',
    operation: 'list_daemon_tasks',
    description: 'List available daemon tasks',
    args: [],
    allowedRoles: ['domain_authority'],
    aliases: ['list_daemon_tasks'],
    tier: 'domain',
  },
  {
    name: 'approve',
    operation: 'approve_interpretation',
    description: 'Approve an interpretation for an ingestion',
    args: ['ingestion_id', 'interpretation_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['approve_interpretation'],
    tier: 'domain',
  },
  {
    name: 'update_physics',
    operation: 'update_domain_physics',
    description: 'Update domain physics (domain key value)',
    args: ['domain_id', 'key', 'value'],
    allowedRoles: ['domain_authority'],
    joinTrailingArgs: true,
    aliases: ['update_domain_physics'],
    tier: 'domain',
  },
  {
    name: 'commit_physics',
    operation: 'commit_domain_physics',
    description: 'Commit pending domain physics changes',
    args: ['domain_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['commit_domain_physics'],
    tier: 'domain',
  },
  {
    name: 'assign_role',
    operation: 'assign_domain_role',
    description: 'Assign domain role to user',
    args: ['user_id', 'module_id', 'domain_role'],
    allowedRoles: ['domain_authority'],
    aliases: ['assign_domain_role'],
    tier: 'domain',
  },
  {
    name: 'revoke_role',
    operation: 'revoke_domain_role',
    description: 'Revoke domain role from user',
    args: ['user_id', 'module_id'],
    allowedRoles: ['domain_authority'],
    aliases: ['revoke_domain_role'],
    tier: 'domain',
  },
  {
    name: 'resolve',
    operation: 'resolve_escalation',
    description: 'Resolve an escalation (id resolution rationale)',
    args: ['escalation_id', 'resolution', 'rationale'],
    allowedRoles: ['domain_authority'],
    joinTrailingArgs: true,
    aliases: ['resolve_escalation'],
    tier: 'domain',
  },
  {
    name: 'reject',
    operation: 'reject_ingestion',
    description: 'Reject an ingestion record with reason',
    args: ['ingestion_id', 'reason'],
    allowedRoles: ['domain_authority'],
    joinTrailingArgs: true,
    aliases: ['reject_ingestion'],
    tier: 'domain',
  },
  {
    name: 'trigger_daemon',
    operation: 'trigger_daemon_task',
    description: 'Trigger daemon task run',
    args: ['domain_id', 'tasks'],
    allowedRoles: ['domain_authority'],
    aliases: ['trigger_daemon_task'],
    tier: 'domain',
  },

  // ── Admin tier — root / IT support only ────────────────
  {
    name: 'update_role',
    operation: 'update_user_role',
    description: 'Change a user platform role (root only)',
    args: ['user_id', 'new_role'],
    allowedRoles: ['root'],
    aliases: ['update_user_role'],
    tier: 'admin',
  },
  {
    name: 'deactivate',
    operation: 'deactivate_user',
    description: 'Deactivate a user account (root only)',
    args: ['user_id'],
    allowedRoles: ['root'],
    aliases: ['deactivate_user'],
    tier: 'admin',
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
 * Merge the static framework commands with any plugin-contributed commands.
 * Rebuilt on each call so newly-registered plugins are picked up.
 */
export function getAllCommands(): SlashCommandDef[] {
  const pluginCmds = getPluginCommands()
  return pluginCmds.length > 0 ? [...COMMANDS, ...pluginCmds] : COMMANDS
}

function buildMergedMap(): Map<string, SlashCommandDef> {
  const pluginCmds = getPluginCommands()
  if (pluginCmds.length === 0) return COMMAND_MAP
  const merged = new Map(COMMAND_MAP)
  for (const cmd of pluginCmds) {
    merged.set(cmd.name, cmd)
    for (const alias of cmd.aliases ?? []) {
      merged.set(alias, cmd)
    }
  }
  return merged
}

/**
 * Get commands visible to a given effective domain role.
 * Empty allowedRoles means visible to everyone.
 *
 * Role equivalences are contributed by domain-pack plugins via
 * addRoleEquivalences(), keeping domain-specific role knowledge
 * out of the framework.
 *
 * @param effectiveRole  The domain-specific role (e.g. 'student', 'system_admin')
 * @param platformRole   Optional platform-level role from auth (e.g. 'root')
 * @param domainKey      Optional current domain key (e.g. 'education', 'system')
 */
export function getCommandsForRole(effectiveRole: string, platformRole?: string, domainKey?: string): SlashCommandDef[] {
  const all = getAllCommands()
  // Platform root sees every command
  if (platformRole === 'root') return all

  const roleEquivalences = getPluginRoleEquivalences()
  const normalizedRole = roleEquivalences[effectiveRole] ?? effectiveRole
  return all.filter(
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

  const def = buildMergedMap().get(commandName)
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

  return { def, operation: def.operation, params, endpoint: tierEndpoint(def.tier) }
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

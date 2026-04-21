/**
 * Assistant domain-pack UI plugin.
 *
 * Registers:
 *  - Assistant-scoped slash commands (/tasks, /cleartasks, /escalations)
 *  - Dashboard tab: Intent Distribution (DA / root)
 *  - No custom sidebar panels in v1 (uses built-in DataPanel)
 */

import type {
  DomainPlugin,
  PluginRegistration,
  SlashCommandDef,
  DashboardTabDef,
} from '@lumina/plugins'

// ── Assistant slash commands ───────────────────────────────

const ASSISTANT_COMMANDS: SlashCommandDef[] = [
  {
    name: 'tasks',
    operation: 'list_tasks',
    description: 'List your tracked tasks',
    args: [],
    defaultParams: {},
    allowedRoles: ['user', 'domain_authority'],
    domainScope: 'assistant',
    aliases: ['list_tasks'],
    tier: 'user',
  },
  {
    name: 'cleartasks',
    operation: 'clear_task_history',
    description: 'Clear completed and abandoned tasks',
    args: [],
    defaultParams: { confirm: true },
    allowedRoles: ['user', 'domain_authority'],
    domainScope: 'assistant',
    tier: 'user',
  },
  {
    name: 'escalations',
    operation: 'list_escalations',
    description: 'List pending escalations',
    args: [],
    allowedRoles: ['domain_authority'],
    aliases: ['list_escalations'],
    domainScope: 'assistant',
    tier: 'user',
  },
]

// ── Assistant dashboard tabs ────────────────────────────

const ASSISTANT_DASHBOARD_TABS: DashboardTabDef[] = [
  {
    id: 'intent-distribution',
    label: 'Intents',
    roles: ['root', 'admin'],
    // Placeholder component — renders a simple summary until a
    // dedicated React component is built in a future iteration.
    component: () => null,
    order: 110,
  },
]

// ── Plugin definition ──────────────────────────────────────

const assistantPlugin: DomainPlugin = {
  id: 'assistant',

  register(api: PluginRegistration) {
    api.addSlashCommands(ASSISTANT_COMMANDS)
    api.addDashboardTabs(ASSISTANT_DASHBOARD_TABS)
    api.addRoleEquivalences({})
  },
}

export default assistantPlugin

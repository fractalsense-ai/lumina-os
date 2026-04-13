/**
 * PluginRegistry — central registry for domain-pack UI contributions.
 *
 * Domain plugins call `registerPlugin()` once at load time.  Framework
 * components query the registry via the read-only getters below.
 */

import type {
  SlashCommandDef,
  DashboardTabDef,
  SidebarPanelDef,
  ChatHookDef,
  ChatHookContext,
  DomainPlugin,
  PluginRegistration,
  PanelComponentProps,
} from './types'
import type { ComponentType } from 'react'

// ── Internal state ─────────────────────────────────────────

const _commands: SlashCommandDef[] = []
const _dashboardTabs: DashboardTabDef[] = []
const _sidebarPanels = new Map<string, ComponentType<PanelComponentProps>>()
const _chatHooks: ChatHookDef[] = []
const _roleEquivalences: Record<string, string> = {}
const _loadedPlugins = new Set<string>()

// ── Registration API (handed to each plugin) ───────────────

function createRegistrationApi(): PluginRegistration {
  return {
    addSlashCommands(commands) {
      _commands.push(...commands)
    },
    addDashboardTabs(tabs) {
      _dashboardTabs.push(...tabs)
    },
    addSidebarPanels(panels) {
      for (const p of panels) {
        _sidebarPanels.set(p.name, p.component)
      }
    },
    addChatHooks(hooks) {
      _chatHooks.push(...hooks)
    },
    addRoleEquivalences(equivalences) {
      Object.assign(_roleEquivalences, equivalences)
    },
  }
}

// ── Public API ─────────────────────────────────────────────

/** Register a domain plugin.  Idempotent — duplicate IDs are ignored. */
export function registerPlugin(plugin: DomainPlugin): void {
  if (_loadedPlugins.has(plugin.id)) return
  _loadedPlugins.add(plugin.id)
  plugin.register(createRegistrationApi())
}

/** All plugin-contributed slash commands. */
export function getPluginCommands(): SlashCommandDef[] {
  return _commands
}

/** All plugin-contributed dashboard tabs, sorted by order. */
export function getPluginDashboardTabs(): DashboardTabDef[] {
  return [..._dashboardTabs].sort((a, b) => (a.order ?? 100) - (b.order ?? 100))
}

/** Resolve a sidebar panel component by name.  undefined = not registered. */
export function resolvePluginPanel(
  name: string,
): ComponentType<PanelComponentProps> | undefined {
  return _sidebarPanels.get(name)
}

/** All registered chat hooks. */
export function getChatHooks(): ChatHookDef[] {
  return _chatHooks
}

/** All plugin-contributed role equivalences. */
export function getPluginRoleEquivalences(): Readonly<Record<string, string>> {
  return _roleEquivalences
}

/** Fire all onMessagesChanged hooks.  Individual errors are silently caught. */
export async function fireChatHooks(ctx: ChatHookContext): Promise<void> {
  for (const hook of _chatHooks) {
    try {
      await hook.onMessagesChanged?.(ctx)
    } catch {
      // Domain hook errors must not break the framework shell
    }
  }
}

/** Reset all registrations (test-only). */
export function _resetForTesting(): void {
  _commands.length = 0
  _dashboardTabs.length = 0
  _sidebarPanels.clear()
  _chatHooks.length = 0
  for (const key of Object.keys(_roleEquivalences)) delete _roleEquivalences[key]
  _loadedPlugins.clear()
}

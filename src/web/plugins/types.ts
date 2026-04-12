/**
 * Plugin system type definitions.
 *
 * Domain packs register components, hooks, slash commands, and dashboard
 * tabs through the PluginRegistration API.  The framework shell consumes
 * them via the read-only query functions in PluginRegistry.ts.
 */

import type { ComponentType } from 'react'

// ── Shared types ───────────────────────────────────────────

export interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

export interface PanelComponentProps {
  auth: AuthState
  panelId: string
  endpoint?: string
  domainId?: string
  domainKey?: string
}

export type CommandTier = 'user' | 'domain' | 'admin'

// ── Plugin contribution types ──────────────────────────────

export interface SlashCommandDef {
  name: string
  operation: string | null
  description: string
  args: string[]
  defaultParams?: Record<string, string>
  allowedRoles: string[]
  domainScope?: string
  aliases?: string[]
  joinTrailingArgs?: boolean
  tier: CommandTier
}

export interface DashboardTabDef {
  id: string
  label: string
  roles: string[]
  component: ComponentType<{ auth: AuthState }>
  /** Lower number = further left.  Framework tabs use 0–99; plugins use 100+. */
  order?: number
}

export interface SidebarPanelDef {
  name: string
  component: ComponentType<PanelComponentProps>
}

export interface ChatHookDef {
  id: string
  onMessagesChanged?: (ctx: ChatHookContext) => void | Promise<void>
}

export interface ChatHookContext {
  messages: ReadonlyArray<{ role: 'user' | 'assistant'; content: string }>
  auth: AuthState
  apiBase: string
}

// ── Registration API ───────────────────────────────────────

export interface PluginRegistration {
  addSlashCommands(commands: SlashCommandDef[]): void
  addDashboardTabs(tabs: DashboardTabDef[]): void
  addSidebarPanels(panels: SidebarPanelDef[]): void
  addChatHooks(hooks: ChatHookDef[]): void
}

export interface DomainPlugin {
  id: string
  register(api: PluginRegistration): void
}

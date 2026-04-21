/**
 * System domain-pack UI plugin.
 *
 * Registers system-scoped dashboard tabs:
 *  - Escalation Queue
 *  - Staged Commands
 *  - Ingestion Review
 *  - System Log
 *  - Daemon Control
 *  - Daemon Monitor
 */

import type { DomainPlugin, DashboardTabDef, SidebarPanelDef, SlashCommandDef, PanelComponentProps } from '@lumina/plugins'
import { EscalationQueue } from './components/EscalationQueue'
import { StagedCommandsPanel } from './components/StagedCommandsPanel'
import { IngestionReview } from './components/IngestionReview'
import { SystemLogPanel } from './components/SystemLogPanel'
import { DaemonPanel } from './components/DaemonPanel'
import { DaemonMonitorPanel } from './components/DaemonMonitorPanel'
import type { ComponentType } from 'react'
import { createElement } from 'react'

// ── Sidebar panel wrapper ───────────────────────────────

type LegacyProps = { auth: { token: string; userId: string; username: string; role: string }; domainId?: string; domainKey?: string }

function wrapLegacy(
  Comp: ComponentType<LegacyProps>,
): ComponentType<PanelComponentProps> {
  return function LegacyWrapper({ auth, domainId, domainKey }: PanelComponentProps) {
    return createElement(Comp, { auth, domainId, domainKey })
  }
}

// ── System slash commands ────────────────────────────────

const SYSTEM_COMMANDS: SlashCommandDef[] = [
  {
    name: 'explain',
    operation: 'explain_reasoning',
    description: 'Explain reasoning for a log event',
    args: ['event_id'],
    allowedRoles: ['admin', 'operator'],
    aliases: ['explain_reasoning'],
    tier: 'user',
  },
]

// ── Sidebar panels ──────────────────────────────────────

const SYSTEM_SIDEBAR_PANELS: SidebarPanelDef[] = [
  { name: 'EscalationQueue', component: wrapLegacy(EscalationQueue) },
  { name: 'SystemLogPanel', component: wrapLegacy(SystemLogPanel) },
]

// ── System dashboard tabs ───────────────────────────────

const SYSTEM_DASHBOARD_TABS: DashboardTabDef[] = [
  {
    id: 'escalations',
    label: 'Escalations',
    roles: ['root', 'admin', 'super_admin', 'operator', 'half_operator'],
    component: EscalationQueue,
  },
  {
    id: 'commands',
    label: 'Commands',
    roles: ['root', 'admin', 'super_admin'],
    component: StagedCommandsPanel,
  },
  {
    id: 'ingestions',
    label: 'Ingestions',
    roles: ['root', 'admin'],
    component: IngestionReview,
  },
  {
    id: 'logs',
    label: 'System Log',
    roles: ['root', 'admin', 'operator', 'half_operator'],
    component: SystemLogPanel,
  },
  {
    id: 'daemon',
    label: 'Daemon',
    roles: ['root', 'half_operator'],
    component: DaemonPanel,
  },
  {
    id: 'daemon-monitor',
    label: 'Monitor',
    roles: ['root', 'super_admin', 'half_operator'],
    component: DaemonMonitorPanel,
  },
]

// ── Plugin registration ─────────────────────────────────

export const systemPlugin: DomainPlugin = {
  id: 'system',
  register(reg) {
    reg.addSlashCommands(SYSTEM_COMMANDS)
    reg.addDashboardTabs(SYSTEM_DASHBOARD_TABS)
    reg.addSidebarPanels(SYSTEM_SIDEBAR_PANELS)
    reg.addRoleEquivalences({
      system_admin: 'admin',
      system_operator: 'teacher',
    })
  },
}

export default systemPlugin

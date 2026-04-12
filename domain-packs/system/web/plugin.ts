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

import type { DomainPlugin, DashboardTabDef, SidebarPanelDef, PanelComponentProps } from '@lumina/plugins'
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
    roles: ['root', 'domain_authority', 'it_support', 'qa', 'auditor'],
    component: EscalationQueue,
  },
  {
    id: 'commands',
    label: 'Commands',
    roles: ['root', 'domain_authority', 'it_support'],
    component: StagedCommandsPanel,
  },
  {
    id: 'ingestions',
    label: 'Ingestions',
    roles: ['root', 'domain_authority'],
    component: IngestionReview,
  },
  {
    id: 'logs',
    label: 'System Log',
    roles: ['root', 'domain_authority', 'qa', 'auditor'],
    component: SystemLogPanel,
  },
  {
    id: 'daemon',
    label: 'Daemon',
    roles: ['root', 'auditor'],
    component: DaemonPanel,
  },
  {
    id: 'daemon-monitor',
    label: 'Monitor',
    roles: ['root', 'it_support', 'auditor'],
    component: DaemonMonitorPanel,
  },
]

// ── Plugin registration ─────────────────────────────────

export const systemPlugin: DomainPlugin = {
  id: 'system',
  register(reg) {
    reg.addDashboardTabs(SYSTEM_DASHBOARD_TABS)
    reg.addSidebarPanels(SYSTEM_SIDEBAR_PANELS)
  },
}

export default systemPlugin

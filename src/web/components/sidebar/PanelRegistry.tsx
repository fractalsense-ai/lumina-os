/**
 * Panel Registry — maps component name strings declared in domain-pack
 * role_layouts to generic React components.  The framework owns this
 * registry; domain packs choose from the generic palette by setting
 * `component` in their sidebar_panel declarations.
 *
 * If a domain pack references a component name that is not registered
 * here, the fallback is DataPanel (a generic endpoint-driven renderer).
 */

import type { ComponentType } from 'react'
import { EscalationQueue } from '@/components/dashboard/EscalationQueue'
import { SystemLogPanel } from '@/components/dashboard/SystemLogPanel'
import { DataPanel } from '@/components/sidebar/DataPanel'

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

/** Props that every registered panel component must accept. */
export interface PanelComponentProps {
  auth: AuthState
  panelId: string
  endpoint?: string
}

/**
 * Wrapper that adapts existing dashboard components (which accept only
 * `{ auth }`) to the PanelComponentProps interface.
 */
function wrapLegacy(
  Comp: ComponentType<{ auth: AuthState }>,
): ComponentType<PanelComponentProps> {
  return function LegacyWrapper({ auth }: PanelComponentProps) {
    return <Comp auth={auth} />
  }
}

/** Map of component name → React component.  Names are case-sensitive
 *  and must match the `component` strings used in domain-pack role_layouts. */
const REGISTRY: Record<string, ComponentType<PanelComponentProps>> = {
  EscalationQueue: wrapLegacy(EscalationQueue),
  SystemLogPanel: wrapLegacy(SystemLogPanel),
  DataPanel: DataPanel,
}

/** Resolve a component name to a React component.  Unknown names
 *  fall back to DataPanel so domain packs can still render endpoint
 *  data without a dedicated component. */
export function resolvePanel(name: string): ComponentType<PanelComponentProps> {
  return REGISTRY[name] ?? DataPanel
}

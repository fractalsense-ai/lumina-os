/**
 * Panel Registry — maps component name strings declared in domain-pack
 * role_layouts to generic React components.  The framework owns this
 * registry; domain packs register their own panel components at load
 * time via the PluginRegistry.
 *
 * Resolution order: PluginRegistry → static REGISTRY → DataPanel fallback.
 */

import type { ComponentType } from 'react'
import { DataPanel } from '@/components/sidebar/DataPanel'
import { resolvePluginPanel } from '@/plugins/PluginRegistry'

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
  domainId?: string
  domainKey?: string
}

/** Map of component name → React component.  Names are case-sensitive
 *  and must match the `component` strings used in domain-pack role_layouts. */
const REGISTRY: Record<string, ComponentType<PanelComponentProps>> = {
  DataPanel: DataPanel,
}

/** Resolve a component name to a React component.
 *  Checks the plugin registry first, then the static registry,
 *  then falls back to DataPanel. */
export function resolvePanel(name: string): ComponentType<PanelComponentProps> {
  return resolvePluginPanel(name) ?? REGISTRY[name] ?? DataPanel
}

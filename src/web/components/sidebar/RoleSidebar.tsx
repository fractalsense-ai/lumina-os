import { useState } from 'react'
import { CaretRight, CaretDown, X } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { resolvePanel, type PanelComponentProps } from '@/components/sidebar/PanelRegistry'

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

interface SidebarPanel {
  id: string
  label: string
  component: string
  endpoint?: string
}

interface RoleLayout {
  sidebar_panels: SidebarPanel[]
  capabilities: string[]
  effective_role: string
}

/**
 * RoleSidebar — domain-agnostic sidebar rendered alongside the chat
 * interface.  The panel list comes from the resolved role_layout
 * returned by /api/domain-info; the component names are resolved via
 * the PanelRegistry.  If the layout has no panels, this component
 * renders nothing.
 */
export function RoleSidebar({
  roleLayout,
  auth,
  onClose,
}: {
  roleLayout: RoleLayout
  auth: AuthState
  onClose: () => void
}) {
  const [expandedPanels, setExpandedPanels] = useState<Set<string>>(
    () => new Set(roleLayout.sidebar_panels.map((p) => p.id)),
  )

  if (roleLayout.sidebar_panels.length === 0) return null

  const toggle = (id: string) => {
    setExpandedPanels((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <aside className="w-80 border-l border-border bg-card flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="text-sm font-semibold text-foreground">
          {roleLayout.effective_role
            ? roleLayout.effective_role.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
            : 'Panels'}
        </span>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="h-7 w-7 text-muted-foreground hover:text-foreground"
        >
          <X size={16} />
        </Button>
      </div>

      {/* Panel sections */}
      <div className="flex-1 overflow-y-auto">
        {roleLayout.sidebar_panels.map((panel) => {
          const expanded = expandedPanels.has(panel.id)
          const PanelComponent = resolvePanel(panel.component)

          return (
            <div key={panel.id} className="border-b border-border/50">
              <button
                onClick={() => toggle(panel.id)}
                className="w-full flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-foreground hover:bg-muted/50 transition-colors"
              >
                {expanded
                  ? <CaretDown size={14} weight="bold" />
                  : <CaretRight size={14} weight="bold" />}
                {panel.label}
              </button>
              {expanded && (
                <div className="px-4 pb-3">
                  <PanelComponent
                    auth={auth}
                    panelId={panel.id}
                    endpoint={panel.endpoint}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </aside>
  )
}

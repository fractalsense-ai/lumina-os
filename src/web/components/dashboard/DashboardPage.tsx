import { useState, useEffect, useCallback } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { getPluginDashboardTabs } from '@/plugins/PluginRegistry'
import type { AuthState, DashboardTabDef } from '@/plugins/types'

interface DomainSummary {
  domain_id: string
  name: string
  version: string
  pending_escalations: number
  pending_ingestions: number
  review_ingestions: number
}

interface TelemetrySummary {
  total_log_records: number
  record_type_counts: Record<string, number>
  escalation_summary: {
    total: number
    pending: number
    resolved: number
  }
  domain_filter: string | null
}

// ── Dynamic tab manifest ─────────────────────────────────────

interface TabDef {
  id: string
  label: string
  roles: string[]
}

interface PanelDef {
  id: string
  label: string
  endpoint: string
  roles: string[]
  type: 'chart' | 'table' | 'metric'
}

interface UiManifest {
  title: string
  subtitle: string
  domain_label: string
  panels?: PanelDef[]
  [key: string]: unknown
}

const TAB_MANIFEST: TabDef[] = [
  { id: 'overview',   label: 'Overview',     roles: ['root', 'admin'] },
]

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

export function DashboardPage({ auth, manifest }: { auth: AuthState; manifest?: UiManifest }) {
  // Merge static governance tabs + plugin tabs + domain-specific panels
  const pluginTabs: TabDef[] = getPluginDashboardTabs()
    .filter((t) => t.roles.includes(auth.role))
    .map((t) => ({ id: `plugin:${t.id}`, label: t.label, roles: t.roles }))
  const domainPanels: TabDef[] = (manifest?.panels ?? [])
    .filter((p) => p.roles.includes(auth.role))
    .map((p) => ({ id: `panel:${p.id}`, label: p.label, roles: p.roles }))
  const allTabs = [
    ...TAB_MANIFEST.filter((t) => t.roles.includes(auth.role)),
    ...pluginTabs,
    ...domainPanels,
  ]
  const visibleTabs = allTabs
  const [domains, setDomains] = useState<DomainSummary[]>([])
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const [tab, setTab] = useState(visibleTabs[0]?.id ?? 'overview')
  const [error, setError] = useState<string | null>(null)

  const headers = { Authorization: `Bearer ${auth.token}` }

  const refreshDashboard = useCallback(async () => {
    setError(null)
    try {
      const [domRes, telRes] = await Promise.all([
        fetch(`${getApiBase()}/api/dashboard/domains`, { headers }),
        fetch(`${getApiBase()}/api/dashboard/telemetry`, { headers }),
      ])
      if (domRes.ok) setDomains(await domRes.json())
      if (telRes.ok) setTelemetry(await telRes.json())
    } catch {
      setError('Failed to load dashboard data.')
    }
  }, [auth.token])

  useEffect(() => { refreshDashboard() }, [refreshDashboard])

  return (
    <div className="p-6 max-w-6xl mx-auto flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-foreground">Governance Dashboard</h2>
        <Button variant="outline" size="sm" onClick={refreshDashboard}>
          Refresh
        </Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {/* Dynamic tab navigation */}
      <div className="flex gap-2 border-b border-border pb-2 overflow-x-auto">
        {visibleTabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-sm font-medium rounded-t transition-colors whitespace-nowrap ${
              tab === t.id
                ? 'bg-card border border-b-0 border-border text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <OverviewTab domains={domains} telemetry={telemetry} />
      )}

      {/* Plugin-contributed tabs */}
      {tab.startsWith('plugin:') && (() => {
        const pluginTab = getPluginDashboardTabs().find((t) => `plugin:${t.id}` === tab)
        if (!pluginTab) return null
        const Comp = pluginTab.component
        return <Comp auth={auth} />
      })()}

      {/* Domain-specific panels from ui_manifest */}
      {tab.startsWith('panel:') && (
        <DomainPanel
          panelId={tab.replace('panel:', '')}
          panel={manifest?.panels?.find((p) => `panel:${p.id}` === tab)}
          auth={auth}
        />
      )}
    </div>
  )
}

function DomainPanel({
  panelId,
  panel,
  auth,
}: {
  panelId: string
  panel?: PanelDef
  auth: AuthState
}) {
  const [data, setData] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!panel) return
    setLoading(true)
    setError(null)
    fetch(`${getApiBase()}${panel.endpoint}`, {
      headers: { Authorization: `Bearer ${auth.token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status}`)
        return res.json()
      })
      .then(setData)
      .catch(() => setError('Panel endpoint not yet implemented.'))
      .finally(() => setLoading(false))
  }, [panel?.endpoint, auth.token])

  if (!panel) return <p className="text-sm text-muted-foreground">Unknown panel.</p>

  return (
    <Card className="p-6">
      <h3 className="text-lg font-semibold text-foreground mb-2">{panel.label}</h3>
      <span className="text-xs font-medium text-muted-foreground bg-muted px-2 py-0.5 rounded mb-4 inline-block">
        {panel.type}
      </span>
      {loading && <p className="text-sm text-muted-foreground mt-3">Loading…</p>}
      {error && <p className="text-sm text-muted-foreground mt-3">{error}</p>}
      {!loading && !error && data && (
        <pre className="mt-3 text-xs bg-muted p-3 rounded overflow-auto max-h-64">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </Card>
  )
}

function OverviewTab({
  domains,
  telemetry,
}: {
  domains: DomainSummary[]
  telemetry: TelemetrySummary | null
}) {
  return (
    <div className="flex flex-col gap-6">
      {/* Telemetry summary cards */}
      {telemetry && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <StatCard label="System Log Records" value={telemetry.total_log_records} />
          <StatCard label="Pending Escalations" value={telemetry.escalation_summary.pending} />
          <StatCard label="Resolved Escalations" value={telemetry.escalation_summary.resolved} />
        </div>
      )}

      {/* Domain list */}
      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Domains
        </h3>
        {domains.length === 0 && (
          <p className="text-sm text-muted-foreground">No domains found.</p>
        )}
        {domains.map((d) => (
          <Card key={d.domain_id} className="p-4 flex items-center justify-between">
            <div>
              <p className="font-medium text-foreground">{d.name}</p>
              <p className="text-xs text-muted-foreground">
                {d.domain_id} &middot; v{d.version}
              </p>
            </div>
            <div className="flex items-center gap-4 text-sm">
              {d.pending_escalations > 0 && (
                <span className="px-2 py-0.5 rounded bg-destructive/10 text-destructive text-xs font-medium">
                  {d.pending_escalations} escalation{d.pending_escalations !== 1 ? 's' : ''}
                </span>
              )}
              {d.review_ingestions > 0 && (
                <span className="px-2 py-0.5 rounded bg-yellow-500/10 text-yellow-600 text-xs font-medium">
                  {d.review_ingestions} review{d.review_ingestions !== 1 ? 's' : ''}
                </span>
              )}
              {d.pending_ingestions > 0 && (
                <span className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-600 text-xs font-medium">
                  {d.pending_ingestions} pending
                </span>
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Card className="p-4 flex flex-col items-center gap-1">
      <span className="text-2xl font-bold text-foreground">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </Card>
  )
}

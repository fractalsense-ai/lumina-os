import { useState, useEffect, useCallback } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { EscalationQueue } from './EscalationQueue'
import { IngestionReview } from './IngestionReview'
import { NightCyclePanel } from './NightCyclePanel'

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

interface DomainSummary {
  domain_id: string
  name: string
  version: string
  pending_escalations: number
  pending_ingestions: number
  review_ingestions: number
}

interface TelemetrySummary {
  total_ctl_records: number
  record_type_counts: Record<string, number>
  escalation_summary: {
    total: number
    pending: number
    resolved: number
  }
  domain_filter: string | null
}

type DashboardTab = 'overview' | 'escalations' | 'ingestions' | 'nightcycle'

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

export function DashboardPage({ auth }: { auth: AuthState }) {
  const [domains, setDomains] = useState<DomainSummary[]>([])
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const [tab, setTab] = useState<DashboardTab>('overview')
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

      {/* Tab navigation */}
      <div className="flex gap-2 border-b border-border pb-2">
        {(['overview', 'escalations', 'ingestions', 'nightcycle'] as DashboardTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 text-sm font-medium rounded-t transition-colors ${
              tab === t
                ? 'bg-card border border-b-0 border-border text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {t === 'overview' ? 'Overview' : t === 'escalations' ? 'Escalations' : t === 'ingestions' ? 'Ingestions' : 'Night Cycle'}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <OverviewTab domains={domains} telemetry={telemetry} />
      )}
      {tab === 'escalations' && (
        <EscalationQueue auth={auth} />
      )}
      {tab === 'ingestions' && (
        <IngestionReview auth={auth} onRefresh={refreshDashboard} />
      )}
      {tab === 'nightcycle' && (
        <NightCyclePanel auth={auth} />
      )}
    </div>
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
          <StatCard label="CTL Records" value={telemetry.total_ctl_records} />
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

import { useState, useEffect, useCallback } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

interface LogRecord {
  record_id: string
  record_type: string
  event_type?: string
  timestamp_utc: string
  session_id?: string
  domain_pack_id?: string
  [key: string]: unknown
}

type LogFilter = 'all' | 'warnings' | 'alerts'

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

const TYPE_COLORS: Record<string, string> = {
  EscalationRecord: 'bg-yellow-500/10 text-yellow-600',
  WarningEvent: 'bg-orange-500/10 text-orange-600',
  ErrorEvent: 'bg-red-500/10 text-red-600',
  CriticalEvent: 'bg-red-500/10 text-red-600',
  TurnRecord: 'bg-blue-500/10 text-blue-600',
  AdminCommandLog: 'bg-purple-500/10 text-purple-600',
  CommitmentRecord: 'bg-indigo-500/10 text-indigo-600',
  TraceEvent: 'bg-cyan-500/10 text-cyan-600',
}

function getRecordSummary(rec: LogRecord): string {
  if (rec.summary && typeof rec.summary === 'string') return rec.summary
  if (rec.trigger && typeof rec.trigger === 'string') return rec.trigger
  if (rec.decision && typeof rec.decision === 'string') return rec.decision
  if (rec.operation && typeof rec.operation === 'string') return `Operation: ${rec.operation}`
  if (rec.message && typeof rec.message === 'string') return rec.message
  if (rec.description && typeof rec.description === 'string') return rec.description
  if (rec.actor_id && typeof rec.actor_id === 'string') return `Actor: ${rec.actor_id}`
  return ''
}

export function SystemLogPanel({ auth, domainId, domainKey }: { auth: AuthState; domainId?: string; domainKey?: string }) {
  const [records, setRecords] = useState<LogRecord[]>([])
  const [filter, setFilter] = useState<LogFilter>('all')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const headers = { Authorization: `Bearer ${auth.token}` }

  const load = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      let url: string
      const scopeId = domainKey || domainId
      const domainParam = scopeId ? `&domain_id=${encodeURIComponent(scopeId)}` : ''
      if (filter === 'warnings') {
        url = `${getApiBase()}/api/system-log/warnings?limit=50${domainParam}`
      } else if (filter === 'alerts') {
        url = `${getApiBase()}/api/system-log/alerts?limit=50${domainParam}`
      } else {
        url = `${getApiBase()}/api/system-log/records?limit=50${domainParam}`
      }
      const res = await fetch(url, { headers })
      if (res.ok) setRecords(await res.json())
      else setError('Failed to load log records.')
    } catch {
      setError('Could not reach API.')
    } finally {
      setLoading(false)
    }
  }, [auth.token, filter, domainId, domainKey])

  useEffect(() => { load() }, [load])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          System Log{domainKey ? ` — ${domainKey}` : domainId ? ` — ${domainId}` : ''}
        </h3>
        <div className="flex items-center gap-2">
          {(['all', 'warnings', 'alerts'] as LogFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2 py-1 text-xs font-medium rounded transition-colors ${
                filter === f
                  ? 'bg-foreground text-background'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {f === 'all' ? 'All' : f === 'warnings' ? 'Warnings' : 'Alerts'}
            </button>
          ))}
          <Button variant="outline" size="sm" onClick={load}>Refresh</Button>
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {loading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {!loading && records.length === 0 && (
        <p className="text-sm text-muted-foreground">No records.</p>
      )}

      <div className="flex flex-col gap-2">
        {records.map((rec) => (
          <Card key={rec.record_id} className="p-3 flex items-start justify-between gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                  TYPE_COLORS[rec.record_type] ?? 'bg-muted text-muted-foreground'
                }`}>
                  {rec.record_type}
                </span>
                {rec.event_type && (
                  <span className="text-xs text-muted-foreground">{rec.event_type}</span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-1 truncate">
                {getRecordSummary(rec) || (
                  <>
                    {rec.session_id && `Session: ${rec.session_id}`}
                    {rec.domain_pack_id && ` · Domain: ${rec.domain_pack_id}`}
                  </>
                )}
              </p>
            </div>
            <span className="text-[10px] text-muted-foreground whitespace-nowrap flex-shrink-0">
              {rec.timestamp_utc}
            </span>
          </Card>
        ))}
      </div>
    </div>
  )
}

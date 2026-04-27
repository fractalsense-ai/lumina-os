import { useState, useEffect, useCallback } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

interface Escalation {
  record_id: string
  trigger: string
  model_pack_id?: string
  domain_pack_id?: string
  session_id: string
  status: string
  timestamp_utc: string
  reason?: string
  student_username?: string
  active_module?: string
  evidence?: {
    frustration?: boolean
    drift_pct?: number
    tier?: string
  }
  domain_lib_decision?: {
    domain_alert_flag?: boolean
    domain_metric_pct?: number
    tier?: string
  }
  sla_minutes?: number
  [key: string]: unknown
}

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

function severityColor(esc: Escalation): string {
  const d = esc.domain_lib_decision ?? esc.evidence
  if (!d) return 'border-l-gray-400'
  if (d.domain_alert_flag || d.frustration) return 'border-l-red-500'
  const drift = d.domain_metric_pct ?? d.drift_pct ?? 0
  if (drift > 0.5) return 'border-l-orange-500'
  if (drift > 0.25) return 'border-l-yellow-400'
  return 'border-l-green-500'
}

function getModelPackId(esc: Escalation): string {
  return esc.model_pack_id ?? esc.domain_pack_id ?? ''
}

export function EscalationQueue({ auth, domainId }: { auth: AuthState; domainId?: string; domainKey?: string }) {
  const [escalations, setEscalations] = useState<Escalation[]>([])
  const [error, setError] = useState<string | null>(null)
  const [resolving, setResolving] = useState<string | null>(null)

  const headers = {
    Authorization: `Bearer ${auth.token}`,
    'Content-Type': 'application/json',
  }

  const load = useCallback(async () => {
    setError(null)
    try {
      const domainParam = domainId ? `&domain_id=${encodeURIComponent(domainId)}` : ''
      const res = await fetch(`${getApiBase()}/api/escalations?status=pending${domainParam}`, {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (res.ok) setEscalations(await res.json())
      else setError('Failed to load escalations.')
    } catch {
      setError('Could not reach API.')
    }
  }, [auth.token, domainId])

  useEffect(() => { load() }, [load])

  const resolve = async (id: string, decision: 'approve' | 'reject' | 'defer') => {
    setResolving(id)
    try {
      const res = await fetch(`${getApiBase()}/api/escalations/${encodeURIComponent(id)}/resolve`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ decision, reasoning: `Resolved via dashboard by ${auth.username}` }),
      })
      if (res.ok) await load()
      else setError('Failed to resolve escalation.')
    } catch {
      setError('Could not reach API.')
    } finally {
      setResolving(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Escalation Queue
        </h3>
        <Button variant="outline" size="sm" onClick={load}>Refresh</Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {escalations.length === 0 && (
        <p className="text-sm text-muted-foreground">No escalations.</p>
      )}

      {escalations.map((esc) => (
        <Card key={esc.record_id} className={`p-4 flex flex-col gap-3 border-l-4 ${severityColor(esc)}`}>
          <div className="flex items-start justify-between">
            <div>
              <p className="font-medium text-foreground text-sm">
                {esc.reason ?? esc.trigger}
              </p>
              {esc.student_username && (
                <p className="text-xs text-foreground font-medium">
                  Student: {esc.student_username}
                  {esc.active_module && (
                    <span className="ml-2 px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      {esc.active_module.split('/').pop()}
                    </span>
                  )}
                </p>
              )}
              {esc.evidence && (
                <p className="text-xs text-muted-foreground">
                  {esc.evidence.frustration && <span className="text-red-500 mr-2">frustrated</span>}
                  {esc.evidence.drift_pct != null && <span className="mr-2">drift {Math.round(esc.evidence.drift_pct * 100)}%</span>}
                  {esc.evidence.tier && <span>tier {esc.evidence.tier}</span>}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                Model-pack: {getModelPackId(esc)} &middot; Session: {esc.session_id}
              </p>
              <p className="text-xs text-muted-foreground">
                {esc.timestamp_utc}
              </p>
            </div>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              esc.status === 'pending'
                ? 'bg-yellow-500/10 text-yellow-600'
                : 'bg-green-500/10 text-green-600'
            }`}>
              {esc.status}
            </span>
          </div>

          {esc.status === 'pending' && (
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => resolve(esc.record_id, 'approve')}
                disabled={resolving === esc.record_id}
                className="bg-green-600 hover:bg-green-700 text-white"
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => resolve(esc.record_id, 'reject')}
                disabled={resolving === esc.record_id}
              >
                Reject
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => resolve(esc.record_id, 'defer')}
                disabled={resolving === esc.record_id}
              >
                Defer
              </Button>
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}

import { useState, useEffect, useCallback } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

interface DaemonStatus {
  enabled: boolean
  schedule: string
  is_running: boolean
  current_run_id: string | null
  last_run: {
    run_id: string
    started_at: string
    finished_at: string | null
    triggered_by: string
    status: string
    total_proposals: number
  } | null
  run_count: number
}

interface DaemonProposal {
  proposal_id: string
  task: string
  domain_id: string
  proposal_type: string
  summary: string
  detail: Record<string, unknown>
  status: string
}

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

async function adminCommand(
  base: string,
  headers: Record<string, string>,
  operation: string,
  parameters?: Record<string, unknown>,
): Promise<Response> {
  return fetch(`${base}/api/domain/command`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ operation, parameters: parameters ?? {} }),
  })
}

export function DaemonPanel({ auth }: { auth: AuthState }) {
  const [status, setStatus] = useState<DaemonStatus | null>(null)
  const [proposals, setProposals] = useState<DaemonProposal[]>([])
  const [triggering, setTriggering] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const headers = { Authorization: `Bearer ${auth.token}` }
  const base = getApiBase()

  const refresh = useCallback(async () => {
    setError(null)
    try {
      const [statusRes, propRes] = await Promise.all([
        adminCommand(base, headers, 'daemon_status'),
        adminCommand(base, headers, 'review_proposals'),
      ])
      if (statusRes.ok) setStatus(await statusRes.json())
      if (propRes.ok) setProposals(await propRes.json())
    } catch {
      setError('Failed to load daemon data.')
    }
  }, [auth.token])

  useEffect(() => { refresh() }, [refresh])

  const triggerRun = async () => {
    setTriggering(true)
    try {
      const res = await adminCommand(base, headers, 'trigger_daemon_task')
      if (!res.ok) throw new Error('Trigger failed')
      await refresh()
    } catch {
      setError('Failed to trigger daemon task.')
    } finally {
      setTriggering(false)
    }
  }

  const resolveProposal = async (proposalId: string, action: 'approved' | 'rejected') => {
    try {
      const res = await adminCommand(base, headers, 'resolve_proposal', {
        proposal_id: proposalId,
        action,
      })
      if (res.ok) await refresh()
    } catch {
      setError('Failed to resolve proposal.')
    }
  }

  const statusColor = (s: string) => {
    switch (s) {
      case 'completed': return 'text-green-400'
      case 'running': return 'text-blue-400'
      case 'failed': return 'text-red-400'
      default: return 'text-muted-foreground'
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <p className="text-sm text-destructive">{error}</p>}

      {/* Status card */}
      <Card className="p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">Daemon Status</h3>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={refresh}>Refresh</Button>
            <Button size="sm" onClick={triggerRun} disabled={triggering || (status?.is_running ?? false)}>
              {triggering ? 'Triggering...' : status?.is_running ? 'Running...' : 'Trigger Now'}
            </Button>
          </div>
        </div>

        {status && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground">Enabled:</span>{' '}
              <span className={status.enabled ? 'text-green-400' : 'text-red-400'}>
                {status.enabled ? 'Yes' : 'No'}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Schedule:</span>{' '}
              <span className="font-mono text-xs">{status.schedule}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Total Runs:</span>{' '}
              <span>{status.run_count}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Running:</span>{' '}
              <span className={status.is_running ? 'text-blue-400' : 'text-muted-foreground'}>
                {status.is_running ? 'Yes' : 'No'}
              </span>
            </div>
          </div>
        )}

        {status?.last_run && (
          <div className="border-t border-border pt-3 text-sm">
            <p className="font-medium mb-1">Last Run</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
              <div>
                <span className="text-muted-foreground">Status:</span>{' '}
                <span className={statusColor(status.last_run.status)}>{status.last_run.status}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Triggered by:</span>{' '}
                <span>{status.last_run.triggered_by}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Proposals:</span>{' '}
                <span>{status.last_run.total_proposals}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Started:</span>{' '}
                <span>{new Date(status.last_run.started_at).toLocaleString()}</span>
              </div>
            </div>
          </div>
        )}
      </Card>

      {/* Proposals */}
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          Pending Proposals ({proposals.length})
        </h3>

        {proposals.length === 0 ? (
          <p className="text-sm text-muted-foreground">No pending proposals.</p>
        ) : (
          proposals.map((p) => (
            <Card key={p.proposal_id} className="p-3 flex flex-col gap-2">
              <div className="flex items-start justify-between gap-2">
                <div className="flex flex-col gap-1 min-w-0">
                  <span className="text-sm font-medium text-foreground truncate">{p.summary}</span>
                  <div className="flex gap-2 text-xs text-muted-foreground">
                    <span className="font-mono">{p.task}</span>
                    <span>•</span>
                    <span>{p.domain_id}</span>
                    <span>•</span>
                    <span className="bg-muted px-1.5 py-0.5 rounded">{p.proposal_type}</span>
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <Button size="sm" onClick={() => resolveProposal(p.proposal_id, 'approved')}>
                    Approve
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => resolveProposal(p.proposal_id, 'rejected')}
                  >
                    Reject
                  </Button>
                </div>
              </div>
            </Card>
          ))
        )}
      </div>
    </div>
  )
}

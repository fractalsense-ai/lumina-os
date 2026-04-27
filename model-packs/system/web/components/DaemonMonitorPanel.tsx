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
  state: string
  enabled: boolean
  load_score: number
  is_idle: boolean
  current_task: string | null
  idle_since: number | null
  poll_interval_seconds: number
}

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

const STATE_COLORS: Record<string, string> = {
  monitoring: 'bg-green-500/10 text-green-600',
  idle: 'bg-blue-500/10 text-blue-600',
  dispatching: 'bg-yellow-500/10 text-yellow-600',
  preempting: 'bg-orange-500/10 text-orange-600',
  stopped: 'bg-red-500/10 text-red-600',
}

export function DaemonMonitorPanel({ auth }: { auth: AuthState }) {
  const [status, setStatus] = useState<DaemonStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch(`${getApiBase()}/api/health/load`, {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (res.ok) {
        setStatus(await res.json())
      } else if (res.status === 403) {
        // Fallback: try public health endpoint
        const pub = await fetch(`${getApiBase()}/api/health`)
        if (pub.ok) {
          const data = await pub.json()
          if (data.daemon) setStatus(data.daemon)
        }
      } else {
        setError('Failed to load daemon status.')
      }
    } catch {
      setError('Could not reach API.')
    }
  }, [auth.token])

  useEffect(() => { refresh() }, [refresh])

  // Auto-refresh every 15s
  useEffect(() => {
    const timer = setInterval(refresh, 15_000)
    return () => clearInterval(timer)
  }, [refresh])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Resource Monitor Daemon
        </h3>
        <Button variant="outline" size="sm" onClick={refresh}>Refresh</Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {!status && !error && (
        <p className="text-sm text-muted-foreground">Loading…</p>
      )}

      {status && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <Card className="p-4 flex flex-col gap-2">
            <span className="text-xs text-muted-foreground uppercase tracking-wide">State</span>
            <div className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATE_COLORS[status.state] ?? 'bg-muted text-muted-foreground'}`}>
                {status.state}
              </span>
              {!status.enabled && (
                <span className="px-2 py-0.5 rounded text-xs font-medium bg-red-500/10 text-red-600">
                  disabled
                </span>
              )}
            </div>
          </Card>

          <Card className="p-4 flex flex-col gap-2">
            <span className="text-xs text-muted-foreground uppercase tracking-wide">Load Score</span>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    status.load_score > 0.8 ? 'bg-red-500' :
                    status.load_score > 0.5 ? 'bg-yellow-500' : 'bg-green-500'
                  }`}
                  style={{ width: `${Math.min(status.load_score * 100, 100)}%` }}
                />
              </div>
              <span className="text-sm font-medium text-foreground">
                {(status.load_score * 100).toFixed(0)}%
              </span>
            </div>
          </Card>

          <Card className="p-4 flex flex-col gap-2">
            <span className="text-xs text-muted-foreground uppercase tracking-wide">Current Task</span>
            <span className="text-sm font-medium text-foreground">
              {status.current_task ?? 'None'}
            </span>
          </Card>

          <Card className="p-4 flex flex-col gap-2">
            <span className="text-xs text-muted-foreground uppercase tracking-wide">Poll Interval</span>
            <span className="text-sm font-medium text-foreground">
              {status.poll_interval_seconds}s
            </span>
          </Card>

          {status.is_idle && status.idle_since && (
            <Card className="p-4 flex flex-col gap-2">
              <span className="text-xs text-muted-foreground uppercase tracking-wide">Idle Since</span>
              <span className="text-sm font-medium text-foreground">
                {new Date(status.idle_since * 1000).toLocaleTimeString()}
              </span>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}

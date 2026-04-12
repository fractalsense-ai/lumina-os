import { useState, useEffect, useCallback } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { InviteLinkDisplay } from '@/components/InviteLinkDisplay'

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

interface StagedCommand {
  staged_id: string
  operation: string
  original_instruction: string
  actor_id: string
  staged_at: string
  expires_at: string
  resolved: boolean
}

interface StagedListResponse {
  total: number
  limit: number
  offset: number
  staged_commands: StagedCommand[]
}

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

export function StagedCommandsPanel({ auth }: { auth: AuthState }) {
  const [commands, setCommands] = useState<StagedCommand[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [resolving, setResolving] = useState<string | null>(null)
  const [resolveResults, setResolveResults] = useState<Record<string, Record<string, unknown>>>({})

  const headers = {
    Authorization: `Bearer ${auth.token}`,
    'Content-Type': 'application/json',
  }

  const load = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch(`${getApiBase()}/api/admin/command/staged?limit=50`, {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (res.ok) {
        const data: StagedListResponse = await res.json()
        setCommands(data.staged_commands)
        setTotal(data.total)
      } else {
        setError('Failed to load staged commands.')
      }
    } catch {
      setError('Could not reach API.')
    }
  }, [auth.token])

  useEffect(() => { load() }, [load])

  const resolve = async (id: string, action: 'accept' | 'reject') => {
    setResolving(id)
    try {
      const res = await fetch(`${getApiBase()}/api/admin/command/${encodeURIComponent(id)}/resolve`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ action }),
      })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        setResolveResults((prev) => ({ ...prev, [id]: data }))
        await load()
      } else {
        setError('Failed to resolve command.')
      }
    } catch {
      setError('Could not reach API.')
    } finally {
      setResolving(null)
    }
  }

  const pending = commands.filter((c) => !c.resolved)
  const resolved = commands.filter((c) => c.resolved)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Staged Commands ({total})
        </h3>
        <Button variant="outline" size="sm" onClick={load}>Refresh</Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {pending.length === 0 && resolved.length === 0 && (
        <p className="text-sm text-muted-foreground">No staged commands.</p>
      )}

      {pending.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground font-medium">Pending</p>
          {pending.map((cmd) => (
            <Card key={cmd.staged_id} className="p-4 flex flex-col gap-3 border-l-4 border-l-yellow-500">
              <div>
                <p className="font-medium text-foreground text-sm">{cmd.operation}</p>
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                  {cmd.original_instruction}
                </p>
                <p className="text-[10px] text-muted-foreground mt-1">
                  by {cmd.actor_id} · expires {cmd.expires_at}
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() => resolve(cmd.staged_id, 'accept')}
                  disabled={resolving === cmd.staged_id}
                  className="bg-green-600 hover:bg-green-700 text-white"
                >
                  Accept
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => resolve(cmd.staged_id, 'reject')}
                  disabled={resolving === cmd.staged_id}
                >
                  Reject
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {resolved.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground font-medium">Resolved</p>
          {resolved.map((cmd) => {
            const rr = resolveResults[cmd.staged_id]
            const result = rr?.result as Record<string, unknown> | undefined
            const setupUrl = result?.setup_url as string | undefined
            const username = result?.username as string | undefined
            const emailSent = result?.email_sent as boolean | undefined
            return (
              <Card key={cmd.staged_id} className="p-3 opacity-60">
                <p className="font-medium text-foreground text-sm">{cmd.operation}</p>
                <p className="text-xs text-muted-foreground">
                  by {cmd.actor_id} · {cmd.staged_at}
                </p>
                {setupUrl && username && (
                  <InviteLinkDisplay
                    setupUrl={setupUrl}
                    username={username}
                    emailSent={emailSent ?? false}
                  />
                )}
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

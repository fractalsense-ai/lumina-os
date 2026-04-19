/**
 * TeacherOverview — DA dashboard tab showing colour-coded teacher status.
 *
 * Fetches the DA view of roster-status and renders each teacher with
 * load, pending escalation count, SLA breach flag, and a status colour.
 */

import { useState, useEffect, useCallback } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

interface TeacherStatus {
  teacher_id: string
  username: string
  modules: string[]
  student_count: number
  pending_escalations: number
  has_sla_breach: boolean
  color: 'green' | 'yellow' | 'orange' | 'red'
}

interface DAViewResponse {
  view: string
  teachers: TeacherStatus[]
}

const COLOR_CLASSES: Record<string, string> = {
  green:  'bg-green-500',
  yellow: 'bg-yellow-400',
  orange: 'bg-orange-500',
  red:    'bg-red-500',
}

const COLOR_BORDER: Record<string, string> = {
  green:  'border-l-green-500',
  yellow: 'border-l-yellow-400',
  orange: 'border-l-orange-500',
  red:    'border-l-red-500',
}

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

export function TeacherOverview({ auth }: { auth: AuthState }) {
  const [data, setData] = useState<DAViewResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const res = await fetch(`${getApiBase()}/api/dashboard/education/roster-status`, {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (res.ok) {
        setData(await res.json())
      } else {
        setError('Failed to load teacher overview.')
      }
    } catch {
      setError('Could not reach API.')
    } finally {
      setLoading(false)
    }
  }, [auth.token])

  useEffect(() => { load() }, [load])

  if (loading) {
    return <p className="text-sm text-muted-foreground p-4">Loading teacher overview…</p>
  }

  const teachers = data?.teachers ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Teacher Status
        </h3>
        <Button variant="outline" size="sm" onClick={load}>Refresh</Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {teachers.length === 0 && !error && (
        <p className="text-sm text-muted-foreground">No teachers found.</p>
      )}

      {teachers.map((t) => (
        <Card
          key={t.teacher_id}
          className={`p-4 border-l-4 ${COLOR_BORDER[t.color] ?? 'border-l-gray-400'}`}
        >
          <div className="flex items-center gap-2 mb-2">
            <span className={`inline-block w-2.5 h-2.5 rounded-full ${COLOR_CLASSES[t.color] ?? 'bg-gray-400'}`} />
            <span className="font-medium text-sm text-foreground">{t.username}</span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-lg font-semibold text-foreground">{t.student_count}</p>
              <p className="text-xs text-muted-foreground">Students</p>
            </div>
            <div>
              <p className={`text-lg font-semibold ${t.pending_escalations > 0 ? 'text-amber-500' : 'text-foreground'}`}>
                {t.pending_escalations}
              </p>
              <p className="text-xs text-muted-foreground">Pending</p>
            </div>
            <div>
              {t.has_sla_breach ? (
                <p className="text-lg font-semibold text-red-500">SLA</p>
              ) : (
                <p className="text-lg font-semibold text-green-500">OK</p>
              )}
              <p className="text-xs text-muted-foreground">Status</p>
            </div>
          </div>

          {t.modules.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {t.modules.map((m) => (
                <span key={m} className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                  {m.split('/').pop()?.replace(/\/v\d+$/, '') ?? m}
                </span>
              ))}
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}

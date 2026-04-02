import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

/**
 * Generic data panel — fetches JSON from a configurable endpoint and
 * renders the result as a compact table.  Domain packs declare the
 * endpoint in their role_layouts sidebar_panel config; this component
 * is entirely domain-agnostic.
 */
export function DataPanel({
  auth,
  panelId,
  endpoint,
}: {
  auth: AuthState
  panelId: string
  endpoint?: string
}) {
  const [data, setData] = useState<unknown>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const url = endpoint
    ? `${getApiBase()}${endpoint}`
    : `${getApiBase()}/api/panels/${encodeURIComponent(panelId)}`

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (!res.ok) {
        setError(`Error ${res.status}`)
        return
      }
      setData(await res.json())
    } catch {
      setError('Could not reach API.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [url])

  if (loading) {
    return <p className="text-xs text-muted-foreground animate-pulse">Loading…</p>
  }

  if (error) {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-xs text-destructive">{error}</p>
        <Button variant="outline" size="sm" onClick={load}>Retry</Button>
      </div>
    )
  }

  if (data === null) return null

  // Render array data as a compact table
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'object') {
    const keys = Object.keys(data[0] as Record<string, unknown>)
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border">
              {keys.map((k) => (
                <th key={k} className="text-left py-1 px-2 text-muted-foreground font-medium">
                  {k}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr key={i} className="border-b border-border/50">
                {keys.map((k) => (
                  <td key={k} className="py-1 px-2 text-foreground">
                    {String((row as Record<string, unknown>)[k] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  // Render object data as key-value pairs
  if (typeof data === 'object' && data !== null && !Array.isArray(data)) {
    const entries = Object.entries(data as Record<string, unknown>)
    return (
      <dl className="text-xs space-y-1">
        {entries.map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <dt className="text-muted-foreground font-medium min-w-[80px]">{k}:</dt>
            <dd className="text-foreground">{typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')}</dd>
          </div>
        ))}
      </dl>
    )
  }

  // Fallback: raw JSON
  return (
    <pre className="text-xs text-foreground whitespace-pre-wrap break-words">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

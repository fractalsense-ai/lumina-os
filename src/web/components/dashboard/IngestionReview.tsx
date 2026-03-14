import { useState, useEffect } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

interface Interpretation {
  id: string
  label: string
  yaml_content: string
  confidence: number
  ambiguity_notes: string
}

interface IngestionRecord {
  document_id: string
  original_filename: string
  content_type: string
  domain_id: string
  status: string
  timestamp_utc: string
  interpretations: Interpretation[]
  selected_interpretation_id: string | null
  review_notes: string | null
}

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

export function IngestionReview({
  auth,
  onRefresh,
}: {
  auth: AuthState
  onRefresh?: () => void
}) {
  const [records, setRecords] = useState<IngestionRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const headers = {
    Authorization: `Bearer ${auth.token}`,
    'Content-Type': 'application/json',
  }

  const load = async () => {
    setError(null)
    try {
      const res = await fetch(`${getApiBase()}/api/ingest`, {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (res.ok) setRecords(await res.json())
      else setError('Failed to load ingestion records.')
    } catch {
      setError('Could not reach API.')
    }
  }

  useEffect(() => { load() }, [])

  const triggerExtract = async (docId: string) => {
    setBusy(docId)
    try {
      const res = await fetch(`${getApiBase()}/api/ingest/${encodeURIComponent(docId)}/extract`, {
        method: 'POST',
        headers,
      })
      if (res.ok) await load()
      else setError('Extraction failed.')
    } catch {
      setError('Could not reach API.')
    } finally {
      setBusy(null)
    }
  }

  const reviewIngestion = async (docId: string, decision: string, interpId?: string) => {
    setBusy(docId)
    try {
      const body: Record<string, string> = { decision }
      if (interpId) body.selected_interpretation_id = interpId
      const res = await fetch(
        `${getApiBase()}/api/ingest/${encodeURIComponent(docId)}/review`,
        { method: 'POST', headers, body: JSON.stringify(body) },
      )
      if (res.ok) {
        await load()
        onRefresh?.()
      } else setError('Review failed.')
    } catch {
      setError('Could not reach API.')
    } finally {
      setBusy(null)
    }
  }

  const commitIngestion = async (docId: string) => {
    setBusy(docId)
    try {
      const res = await fetch(
        `${getApiBase()}/api/ingest/${encodeURIComponent(docId)}/commit`,
        { method: 'POST', headers },
      )
      if (res.ok) {
        await load()
        onRefresh?.()
      } else setError('Commit failed.')
    } catch {
      setError('Could not reach API.')
    } finally {
      setBusy(null)
    }
  }

  const statusColor = (status: string) => {
    switch (status) {
      case 'pending_extraction': return 'bg-blue-500/10 text-blue-600'
      case 'extracting': return 'bg-blue-500/10 text-blue-600'
      case 'extraction_complete': return 'bg-yellow-500/10 text-yellow-600'
      case 'approved': return 'bg-green-500/10 text-green-600'
      case 'committed': return 'bg-green-500/10 text-green-600'
      case 'rejected': return 'bg-destructive/10 text-destructive'
      default: return 'bg-muted text-muted-foreground'
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Ingestion Review
        </h3>
        <Button variant="outline" size="sm" onClick={load}>Refresh</Button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {records.length === 0 && (
        <p className="text-sm text-muted-foreground">No ingestion records.</p>
      )}

      {records.map((rec) => (
        <Card key={rec.document_id} className="p-4 flex flex-col gap-3">
          <div className="flex items-start justify-between">
            <div>
              <p className="font-medium text-foreground text-sm">{rec.original_filename}</p>
              <p className="text-xs text-muted-foreground">
                {rec.content_type} &middot; {rec.domain_id} &middot; {rec.timestamp_utc}
              </p>
            </div>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor(rec.status)}`}>
              {rec.status.replace(/_/g, ' ')}
            </span>
          </div>

          {/* Action buttons based on status */}
          <div className="flex gap-2 flex-wrap">
            {rec.status === 'pending_extraction' && (
              <Button
                size="sm"
                onClick={() => triggerExtract(rec.document_id)}
                disabled={busy === rec.document_id}
              >
                Extract
              </Button>
            )}

            {rec.status === 'extraction_complete' && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setExpandedId(expandedId === rec.document_id ? null : rec.document_id)}
              >
                {expandedId === rec.document_id ? 'Hide' : 'Review'} Interpretations
              </Button>
            )}

            {rec.status === 'approved' && (
              <Button
                size="sm"
                onClick={() => commitIngestion(rec.document_id)}
                disabled={busy === rec.document_id}
                className="bg-green-600 hover:bg-green-700 text-white"
              >
                Commit
              </Button>
            )}
          </div>

          {/* Expanded interpretations */}
          {expandedId === rec.document_id && rec.interpretations.length > 0 && (
            <div className="flex flex-col gap-3 mt-2 border-t border-border pt-3">
              {rec.interpretations.map((interp) => (
                <div key={interp.id} className="flex flex-col gap-2 p-3 bg-muted rounded-lg">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm text-foreground">{interp.label}</span>
                      <span className="text-xs text-muted-foreground">
                        ({(interp.confidence * 100).toFixed(0)}% confidence)
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        onClick={() => reviewIngestion(rec.document_id, 'approve', interp.id)}
                        disabled={busy === rec.document_id}
                        className="bg-green-600 hover:bg-green-700 text-white"
                      >
                        Approve
                      </Button>
                    </div>
                  </div>
                  {interp.ambiguity_notes && (
                    <p className="text-xs text-muted-foreground">{interp.ambiguity_notes}</p>
                  )}
                  <pre className="text-xs bg-card border border-border rounded p-2 overflow-x-auto whitespace-pre-wrap">
                    {interp.yaml_content}
                  </pre>
                </div>
              ))}
              <Button
                size="sm"
                variant="outline"
                onClick={() => reviewIngestion(rec.document_id, 'reject')}
                disabled={busy === rec.document_id}
                className="self-start"
              >
                Reject All
              </Button>
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}

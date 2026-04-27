import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash, ChatCircle, Lock } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { SessionSummary, TranscriptStore } from '@/services/transcriptStore'

export interface SessionPanelProps {
  store: TranscriptStore
  activeSessionId: string | null
  onSelect: (sessionId: string) => void
  onNew: () => void
  onDelete: (sessionId: string) => void
  /** Bump this counter to trigger a refresh of the session list */
  refreshKey?: number
}

function timeAgo(ts: number): string {
  const seconds = Math.floor((Date.now() - ts) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(ts).toLocaleDateString()
}

export function SessionPanel({
  store,
  activeSessionId,
  onSelect,
  onNew,
  onDelete,
  refreshKey,
}: SessionPanelProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])

  const refresh = useCallback(async () => {
    try {
      const list = await store.listSessions()
      list.sort((a, b) => b.updatedAt - a.updatedAt)
      setSessions(list)
    } catch {
      // Store unavailable — show empty list
    }
  }, [store])

  useEffect(() => {
    refresh()
  }, [refresh, refreshKey])

  return (
    <aside className="w-60 border-r border-border bg-card flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-border">
        <span className="text-sm font-semibold text-foreground">Conversations</span>
        <Button
          variant="ghost"
          size="icon"
          onClick={onNew}
          title="New conversation"
          className="h-7 w-7 text-muted-foreground hover:text-foreground"
        >
          <Plus size={16} weight="bold" />
        </Button>
      </div>

      {/* Session list */}
      <ScrollArea className="flex-1">
        <div className="flex flex-col py-1">
          {sessions.length === 0 && (
            <p className="text-xs text-muted-foreground px-3 py-4 text-center">
              No conversations yet.
            </p>
          )}
          {sessions.map((s) => {
            const active = s.sessionId === activeSessionId
            return (
              <div
                key={s.sessionId}
                role="button"
                tabIndex={0}
                onClick={() => onSelect(s.sessionId)}
                onKeyDown={(e) => { if (e.key === 'Enter') onSelect(s.sessionId) }}
                className={`group flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors ${
                  active
                    ? 'bg-muted text-foreground'
                    : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                }`}
              >
                <ChatCircle size={16} weight={active ? 'fill' : 'regular'} className="flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm truncate">
                    {s.label || `Session ${s.sessionId.slice(-6)}`}
                  </p>
                  <p className="text-[11px] text-muted-foreground">
                    {s.turnCount} turn{s.turnCount !== 1 ? 's' : ''} · {timeAgo(s.updatedAt)}
                  </p>
                </div>
                {s.moduleId && s.moduleId !== 'domain/edu/general-education/v1' ? (
                  <Lock
                    size={14}
                    className="flex-shrink-0 text-muted-foreground"
                  />
                ) : (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive flex-shrink-0"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete(s.sessionId)
                    }}
                    title="Delete conversation"
                  >
                    <Trash size={14} />
                  </Button>
                )}
              </div>
            )
          })}
        </div>
      </ScrollArea>
    </aside>
  )
}

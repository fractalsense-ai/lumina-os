import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { motion } from 'framer-motion'
import {
  Warning,
  CheckCircle,
  XCircle,
  Clock,
  PencilSimple,
  ShieldCheck,
} from '@phosphor-icons/react'

export interface ActionCardAction {
  id: string
  label: string
  style: 'primary' | 'destructive' | 'ghost' | 'outline'
}

export interface ActionCardData {
  type: 'action_card'
  card_type: 'escalation' | 'command_proposal'
  id: string
  title: string
  body: string
  context: Record<string, unknown>
  actions: ActionCardAction[]
  resolve_endpoint: string
  metadata?: Record<string, unknown>
}

interface ActionCardProps {
  card: ActionCardData
  token: string
  onResolved?: (cardId: string, actionId: string) => void
}

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

const STYLE_MAP: Record<ActionCardAction['style'], string> = {
  primary: 'default',
  destructive: 'destructive',
  ghost: 'ghost',
  outline: 'outline',
}

const ACTION_ICONS: Record<string, React.ReactNode> = {
  approve: <CheckCircle size={16} weight="bold" />,
  accept: <CheckCircle size={16} weight="bold" />,
  reject: <XCircle size={16} weight="bold" />,
  defer: <Clock size={16} weight="bold" />,
  modify: <PencilSimple size={16} weight="bold" />,
}

export function ActionCard({ card, token, onResolved }: ActionCardProps) {
  const [resolving, setResolving] = useState<string | null>(null)
  const [resolved, setResolved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleAction = async (action: ActionCardAction) => {
    setResolving(action.id)
    setError(null)
    try {
      const res = await fetch(`${getApiBase()}${card.resolve_endpoint}`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(
          card.card_type === 'command_proposal'
            ? { action: action.id }
            : { decision: action.id, reasoning: 'Resolved via chat action card' },
        ),
      })
      if (res.ok) {
        setResolved(true)
        onResolved?.(card.id, action.id)
      } else {
        const body = await res.json().catch(() => ({}))
        setError(body?.detail ?? 'Failed to resolve.')
      }
    } catch {
      setError('Could not reach API.')
    } finally {
      setResolving(null)
    }
  }

  const icon = card.card_type === 'escalation'
    ? <Warning size={20} weight="duotone" className="text-yellow-500" />
    : <ShieldCheck size={20} weight="duotone" className="text-blue-500" />

  const borderColor = card.card_type === 'escalation'
    ? 'border-l-yellow-500'
    : 'border-l-blue-500'

  if (resolved) {
    return (
      <motion.div
        initial={{ opacity: 1 }}
        animate={{ opacity: 0.6 }}
        transition={{ duration: 0.3 }}
      >
        <Card className={`p-4 border-l-4 ${borderColor} bg-muted/30`}>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <CheckCircle size={16} weight="bold" className="text-green-500" />
            <span>Resolved</span>
          </div>
        </Card>
      </motion.div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
    >
      <Card className={`p-4 border-l-4 ${borderColor} flex flex-col gap-3`}>
        <div className="flex items-start gap-2">
          {icon}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-foreground">{card.title}</p>
            <p className="text-sm text-muted-foreground whitespace-pre-wrap mt-1">{card.body}</p>
          </div>
        </div>

        {card.context.sla_minutes && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock size={12} />
            <span>SLA: {String(card.context.sla_minutes)} min</span>
            {card.context.target_role && (
              <span className="ml-2">Target: {String(card.context.target_role)}</span>
            )}
          </div>
        )}

        {error && <p className="text-xs text-destructive">{error}</p>}

        <div className="flex gap-2 flex-wrap">
          {card.actions.map((action) => (
            <Button
              key={action.id}
              size="sm"
              variant={STYLE_MAP[action.style] as any}
              onClick={() => handleAction(action)}
              disabled={resolving !== null}
              className="gap-1"
            >
              {ACTION_ICONS[action.id]}
              {action.label}
            </Button>
          ))}
        </div>
      </Card>
    </motion.div>
  )
}

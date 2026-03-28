import { Card } from '@/components/ui/card'
import { motion } from 'framer-motion'
import { WarningCircle, Lightbulb } from '@phosphor-icons/react'

export interface ClarificationData {
  type: 'clarification'
  operation: string
  error: string
  hints: string[]
  original_params?: Record<string, unknown>
}

interface ClarificationCardProps {
  data: ClarificationData
}

function formatOperationLabel(operation: string): string {
  return operation.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function ClarificationCard({ data }: ClarificationCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
    >
      <Card className="p-4 border-l-4 border-l-amber-500 flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <WarningCircle size={20} weight="duotone" className="text-amber-500" />
          <span className="text-sm font-semibold text-foreground">
            {formatOperationLabel(data.operation)} — Clarification Needed
          </span>
        </div>

        <p className="text-sm text-muted-foreground">{data.error}</p>

        {data.hints.length > 0 && (
          <div className="space-y-1.5">
            {data.hints.map((hint, i) => (
              <div key={i} className="flex items-start gap-2 text-sm">
                <Lightbulb size={14} weight="duotone" className="text-amber-500 mt-0.5 shrink-0" />
                <span className="text-muted-foreground">{hint}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </motion.div>
  )
}

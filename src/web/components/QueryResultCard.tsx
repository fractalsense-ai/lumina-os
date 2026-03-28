import { Card } from '@/components/ui/card'
import { motion } from 'framer-motion'
import { ListBullets, Table as TableIcon } from '@phosphor-icons/react'

export interface QueryResultData {
  type: 'query_result'
  operation: string
  result: Record<string, unknown>
}

interface QueryResultCardProps {
  data: QueryResultData
}

function formatOperationLabel(operation: string): string {
  return operation.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function CommandListView({ commands }: { commands: Array<Record<string, unknown>> }) {
  return (
    <div className="space-y-1.5">
      {commands.map((cmd) => (
        <div
          key={String(cmd.name)}
          className="flex items-start gap-2 text-sm"
        >
          <code className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded shrink-0">
            {String(cmd.name)}
          </code>
          {cmd.description && (
            <span className="text-muted-foreground text-xs leading-relaxed">
              {String(cmd.description)}
            </span>
          )}
          {cmd.hitl_exempt && (
            <span className="text-[10px] bg-green-500/10 text-green-600 px-1 rounded ml-auto shrink-0">
              instant
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

function GenericResultView({ result }: { result: Record<string, unknown> }) {
  const entries = Object.entries(result).filter(
    ([key]) => key !== 'operation',
  )
  return (
    <div className="space-y-1.5 text-sm">
      {entries.map(([key, value]) => (
        <div key={key} className="flex gap-2">
          <span className="text-muted-foreground shrink-0">{key}:</span>
          <span className="break-all">
            {typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}
          </span>
        </div>
      ))}
    </div>
  )
}

export function QueryResultCard({ data }: QueryResultCardProps) {
  const result = data.result ?? {}
  const commands = Array.isArray(result.commands) ? result.commands as Array<Record<string, unknown>> : null
  const count = typeof result.count === 'number' ? result.count : null

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
    >
      <Card className="p-4 border-l-4 border-l-emerald-500 flex flex-col gap-3">
        <div className="flex items-center gap-2">
          {commands ? (
            <ListBullets size={20} weight="duotone" className="text-emerald-500" />
          ) : (
            <TableIcon size={20} weight="duotone" className="text-emerald-500" />
          )}
          <span className="text-sm font-semibold text-foreground">
            {formatOperationLabel(data.operation)}
          </span>
          {count !== null && (
            <span className="text-xs text-muted-foreground ml-auto">
              {count} result{count !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        <div className="max-h-64 overflow-y-auto">
          {commands ? (
            <CommandListView commands={commands} />
          ) : (
            <GenericResultView result={result} />
          )}
        </div>
      </Card>
    </motion.div>
  )
}

import { Card } from '@/components/ui/card'
import { motion } from 'framer-motion'
import {
  ListBullets,
  Table as TableIcon,
  Users as UsersIcon,
  UserCircle,
  CheckCircle,
  Shield,
  Folders,
  Warning,
} from '@phosphor-icons/react'

export interface QueryResultData {
  type: 'query_result'
  operation: string
  result: Record<string, unknown>
}

interface QueryResultCardProps {
  data: QueryResultData
}

/* ── Helpers ─────────────────────────────────────────────── */

function formatOperationLabel(operation: string): string {
  return operation.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatRole(role: string): string {
  return role.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function roleBadgeClass(role: string): string {
  switch (role) {
    case 'root':
      return 'bg-red-500/10 text-red-600'
    case 'admin':
      return 'bg-purple-500/10 text-purple-600'
    case 'super_admin':
      return 'bg-blue-500/10 text-blue-600'
    case 'operator':
    case 'half_operator':
      return 'bg-amber-500/10 text-amber-600'
    case 'guest':
      return 'bg-gray-500/10 text-gray-500'
    default:
      return 'bg-sky-500/10 text-sky-600'
  }
}

function statusBadge(active: unknown) {
  if (active === true)
    return <span className="text-[10px] bg-green-500/10 text-green-600 px-1.5 py-0.5 rounded">Active</span>
  if (active === false)
    return <span className="text-[10px] bg-orange-500/10 text-orange-600 px-1.5 py-0.5 rounded">Pending</span>
  return null
}

function domainRoleBadges(domainRoles: Record<string, string> | undefined) {
  if (!domainRoles || Object.keys(domainRoles).length === 0) return null
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {Object.entries(domainRoles).map(([mod, role]) => {
        const shortMod = mod.split('/').pop() ?? mod
        return (
          <span
            key={mod}
            className="text-[10px] bg-indigo-500/10 text-indigo-600 px-1.5 py-0.5 rounded"
            title={mod}
          >
            {shortMod}: {role}
          </span>
        )
      })}
    </div>
  )
}

/* ── list_users ──────────────────────────────────────────── */

function UserListView({ users }: { users: Array<Record<string, unknown>> }) {
  return (
    <div className="space-y-2">
      {users.map((u) => {
        const uid = String(u.user_id ?? '')
        const username = String(u.username ?? 'unknown')
        const role = String(u.role ?? 'user')
        const active = u.active
        const domainRoles = (u.domain_roles ?? undefined) as Record<string, string> | undefined
        const modules = Array.isArray(u.governed_modules) ? u.governed_modules as string[] : []

        return (
          <div key={uid} className="flex items-start gap-2.5 py-1.5 border-b border-border/50 last:border-0">
            <UserCircle size={22} weight="duotone" className="text-muted-foreground shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium truncate">{username}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${roleBadgeClass(role)}`}>
                  {formatRole(role)}
                </span>
                {statusBadge(active)}
              </div>
              {modules.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {modules.map((m) => {
                    const shortMod = String(m).split('/').pop() ?? String(m)
                    return (
                      <span key={String(m)} className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded" title={String(m)}>
                        {shortMod}
                      </span>
                    )
                  })}
                </div>
              )}
              {domainRoleBadges(domainRoles)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ── list_commands ───────────────────────────────────────── */

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

/* ── list_escalations ────────────────────────────────────── */

function EscalationListView({ escalations }: { escalations: Array<Record<string, unknown>> }) {
  return (
    <div className="space-y-2">
      {escalations.map((esc, i) => {
        const id = String(esc.escalation_id ?? esc.record_id ?? i)
        const reason = String(esc.reason ?? esc.summary ?? esc.decision ?? '-')
        const status = String(esc.status ?? 'pending')
        const domain = String(esc.model_pack_id ?? esc.domain_pack_id ?? esc.domain_id ?? '')
        const shortDomain = domain.split('/').pop() ?? domain
        return (
          <div key={id} className="flex items-start gap-2 py-1.5 border-b border-border/50 last:border-0">
            <Warning size={18} weight="duotone" className="text-amber-500 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-mono text-muted-foreground">{id.slice(0, 8)}…</span>
                <span className="text-[10px] bg-amber-500/10 text-amber-600 px-1.5 py-0.5 rounded">{status}</span>
                {shortDomain && <span className="text-[10px] text-muted-foreground">{shortDomain}</span>}
              </div>
              <p className="text-xs text-foreground mt-0.5 line-clamp-2">{reason}</p>
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ── list_domains / list_modules ─────────────────────────── */

function DomainListView({ items, labelKey }: { items: Array<Record<string, unknown>>; labelKey: string }) {
  return (
    <div className="space-y-1.5">
      {items.map((item, i) => {
        const label = String(item[labelKey] ?? item.domain_id ?? item.module_id ?? i)
        const version = item.version ? String(item.version) : null
        return (
          <div key={label} className="flex items-center gap-2 text-sm py-1 border-b border-border/50 last:border-0">
            <Folders size={16} weight="duotone" className="text-emerald-500 shrink-0" />
            <span className="font-mono text-xs">{label}</span>
            {version && <span className="text-[10px] text-muted-foreground ml-auto">v{version}</span>}
          </div>
        )
      })}
    </div>
  )
}

/* ── Confirmation results (invite_user, assign_domain_role, etc.) ── */

function ConfirmationView({ result }: { result: Record<string, unknown> }) {
  const entries = Object.entries(result).filter(
    ([key]) => !['operation', 'setup_url', 'invite_token'].includes(key),
  )
  return (
    <div className="space-y-1.5 text-sm">
      {entries.map(([key, value]) => {
        const label = key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
        let display: string
        if (typeof value === 'boolean') display = value ? 'Yes' : 'No'
        else if (value === null || value === undefined) display = '-'
        else if (Array.isArray(value)) {
          display = value.length > 0 ? value.map(String).join(', ') : 'None'
        } else display = String(value)
        return (
          <div key={key} className="flex gap-2">
            <span className="text-muted-foreground shrink-0 text-xs">{label}:</span>
            <span className="text-xs break-all">{display}</span>
          </div>
        )
      })}
    </div>
  )
}

/* ── Generic fallback (improved) ─────────────────────────── */

function GenericResultView({ result }: { result: Record<string, unknown> }) {
  const entries = Object.entries(result).filter(
    ([key]) => key !== 'operation',
  )
  return (
    <div className="space-y-1.5 text-sm">
      {entries.map(([key, value]) => {
        const label = key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
        let display: React.ReactNode

        if (value === null || value === undefined) {
          display = <span className="text-muted-foreground italic">-</span>
        } else if (typeof value === 'boolean') {
          display = value ? 'Yes' : 'No'
        } else if (Array.isArray(value) && value.length === 0) {
          display = <span className="text-muted-foreground italic">None</span>
        } else if (Array.isArray(value) && value.every((v) => typeof v === 'string')) {
          display = value.join(', ')
        } else if (typeof value === 'object') {
          display = (
            <pre className="text-xs bg-muted rounded p-2 overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(value, null, 2)}
            </pre>
          )
        } else {
          display = String(value)
        }

        return (
          <div key={key} className="flex flex-col gap-0.5">
            <span className="text-muted-foreground text-xs">{label}</span>
            <span className="break-all">{display}</span>
          </div>
        )
      })}
    </div>
  )
}

/* ── Detect which view to render ─────────────────────────── */

function pickIcon(operation: string, result: Record<string, unknown>) {
  if (Array.isArray(result.commands)) return <ListBullets size={20} weight="duotone" className="text-emerald-500" />
  if (Array.isArray(result.users)) return <UsersIcon size={20} weight="duotone" className="text-emerald-500" />
  if (Array.isArray(result.escalations)) return <Warning size={20} weight="duotone" className="text-amber-500" />
  if (Array.isArray(result.domains) || Array.isArray(result.modules))
    return <Folders size={20} weight="duotone" className="text-emerald-500" />
  if (operation === 'invite_user') return <CheckCircle size={20} weight="duotone" className="text-emerald-500" />
  if (result.domain_roles) return <Shield size={20} weight="duotone" className="text-emerald-500" />
  return <TableIcon size={20} weight="duotone" className="text-emerald-500" />
}

function ResultBody({ operation, result }: { operation: string; result: Record<string, unknown> }) {
  // list_commands
  if (Array.isArray(result.commands))
    return <CommandListView commands={result.commands as Array<Record<string, unknown>>} />

  // list_users
  if (Array.isArray(result.users))
    return <UserListView users={result.users as Array<Record<string, unknown>>} />

  // list_escalations
  if (Array.isArray(result.escalations))
    return <EscalationListView escalations={result.escalations as Array<Record<string, unknown>>} />

  // list_domains
  if (Array.isArray(result.domains))
    return <DomainListView items={result.domains as Array<Record<string, unknown>>} labelKey="domain_id" />

  // list_modules
  if (Array.isArray(result.modules) && result.modules.every((m) => typeof m === 'object'))
    return <DomainListView items={result.modules as Array<Record<string, unknown>>} labelKey="module_id" />

  // Mutation confirmations (invite_user, assign_domain_role, update_user_role, etc.)
  const mutationOps = [
    'invite_user', 'update_user_role', 'deactivate_user',
    'assign_domain_role', 'revoke_domain_role',
    'assign_student', 'remove_student', 'assign_module', 'remove_module',
    'approve_interpretation', 'reject_ingestion', 'resolve_escalation',
  ]
  if (mutationOps.includes(operation))
    return <ConfirmationView result={result} />

  return <GenericResultView result={result} />
}

/* ── Card ─────────────────────────────────────────────────── */

export function QueryResultCard({ data }: QueryResultCardProps) {
  const result = data.result ?? {}
  const count = typeof result.count === 'number' ? result.count : null

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
    >
      <Card className="p-4 border-l-4 border-l-emerald-500 flex flex-col gap-3">
        <div className="flex items-center gap-2">
          {pickIcon(data.operation, result)}
          <span className="text-sm font-semibold text-foreground">
            {formatOperationLabel(data.operation)}
          </span>
          {count !== null && (
            <span className="text-xs text-muted-foreground ml-auto">
              {count} result{count !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        <div className="max-h-72 overflow-y-auto">
          <ResultBody operation={data.operation} result={result} />
        </div>
      </Card>
    </motion.div>
  )
}

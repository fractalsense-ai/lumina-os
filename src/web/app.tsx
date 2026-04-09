import { useState, useEffect, useRef, Component, type ReactNode } from 'react'
import { Shield, PaperPlaneRight, User, Robot, SignOut, Gauge, Bell, SidebarSimple, Warning, ChatCircle } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { motion, AnimatePresence } from 'framer-motion'
import { DashboardPage } from '@/components/dashboard/DashboardPage'
import { ActionCard, type ActionCardData } from '@/components/ActionCard'
import { QueryResultCard, type QueryResultData } from '@/components/QueryResultCard'
import { ClarificationCard, type ClarificationData } from '@/components/ClarificationCard'
import { useEventStream } from '@/hooks/useEventStream'
import { SetupPasswordPage } from '@/components/SetupPasswordPage'
import { RoleSidebar } from '@/components/sidebar/RoleSidebar'
import { SessionPanel } from '@/components/sidebar/SessionPanel'
import { SlashCommandPalette } from '@/components/SlashCommandPalette'
import {
  createTranscriptStore,
  type TranscriptStore,
  type TranscriptTurn,
  type TranscriptMetadata,
  type StoredSession,
  type SessionSummary,
} from '@/services/transcriptStore'
import { parseSlashCommand, generateHelpText } from '@/services/slashCommands'

interface Message {
  role: 'user' | 'assistant'
  content: string
  id: string
  meta?: {
    action?: string
    promptType?: string
    escalated?: boolean
  }
  structured_content?: ActionCardData | QueryResultData | ClarificationData
}

type ApiChatResponse = {
  session_id: string
  response: string
  action: string
  prompt_type: string
  escalated: boolean
  structured_content?: ActionCardData | QueryResultData | ClarificationData
  transcript_seal?: string
  transcript_seal_metadata?: TranscriptMetadata
  transcript_snapshot?: TranscriptTurn[]
}

interface UiManifest {
  title: string
  subtitle: string
  domain_label: string
  consent_heading: string
  consent_text: string
  consent_button_label: string
  placeholder_text: string
  input_placeholder?: string
  theme?: {
    primary?: string
    accent?: string
    background?: string
  }
}

interface SidebarPanel {
  id: string
  label: string
  component: string
  endpoint?: string
}

interface RoleLayout {
  sidebar_panels: SidebarPanel[]
  capabilities: string[]
  effective_role: string
}

interface DomainInfo {
  domain_id: string
  domain_key?: string
  domain_version: string
  ui_manifest: UiManifest
  role_layout?: RoleLayout
}

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

const DEFAULT_MANIFEST: UiManifest = {
  title: 'Project Lumina',
  subtitle: '',
  domain_label: '',
  consent_heading: 'Project Lumina',
  consent_text:
    'This system uses structured telemetry only. No raw transcripts are stored. If we get stuck, we escalate to a human authority.',
  consent_button_label: 'I Agree',
  placeholder_text: 'Type your message...',
}

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

async function fetchDomainInfo(token?: string): Promise<DomainInfo | null> {
  try {
    const headers: Record<string, string> = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    const res = await fetch(`${getApiBase()}/api/domain-info`, { headers })
    if (!res.ok) return null
    return (await res.json()) as DomainInfo
  } catch {
    return null
  }
}

async function orchestratorApiCall(
  userText: string,
  sessionId: string | null,
  auth: AuthState | null,
): Promise<ApiChatResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (auth) {
    headers['Authorization'] = `Bearer ${auth.token}`
  }
  const res = await fetch(`${getApiBase()}/api/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      session_id: sessionId,
      message: userText,
    }),
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(errorText || `API request failed with status ${res.status}`)
  }

  return (await res.json()) as ApiChatResponse
}

type AdminCommandResponse = {
  staged_id: string | null
  staged_command: Record<string, unknown>
  original_instruction: string
  result?: Record<string, unknown>
  hitl_exempt?: boolean
  structured_content?: ActionCardData | QueryResultData | ClarificationData
  expires_at?: number
}

async function adminCommandCall(
  operation: string,
  params: Record<string, string>,
  auth: AuthState | null,
  domainId?: string,
): Promise<AdminCommandResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (auth) {
    headers['Authorization'] = `Bearer ${auth.token}`
  }
  const body: Record<string, unknown> = { operation, params }
  if (domainId) {
    body.domain_id = domainId
  }
  const res = await fetch(`${getApiBase()}/api/admin/command`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(errorText || `Command failed with status ${res.status}`)
  }

  return (await res.json()) as AdminCommandResponse
}

function applyThemeOverrides(theme: UiManifest['theme']) {
  if (!theme) return
  const root = document.documentElement
  if (theme.primary) root.style.setProperty('--primary', theme.primary)
  if (theme.accent) root.style.setProperty('--accent', theme.accent)
  if (theme.background) root.style.setProperty('--background', theme.background)
}

function LoginScreen({
  manifest,
  onAuth,
}: {
  manifest: UiManifest
  onAuth: (auth: AuthState) => void
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async () => {
    const u = username.trim()
    const p = password.trim()
    if (!u || !p) {
      setError('Username and password are required.')
      return
    }
    setError(null)
    setIsLoading(true)
    try {
      const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register'
      const res = await fetch(`${getApiBase()}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body?.detail ?? `${mode === 'login' ? 'Login' : 'Registration'} failed.`)
        return
      }
      const data = await res.json()
      const auth: AuthState = {
        token: data.access_token,
        userId: data.user_id,
        username: u,
        role: data.role,
      }
      localStorage.setItem('lumina.auth', JSON.stringify(auth))
      onAuth(auth)
    } catch {
      setError('Could not reach the Lumina API. Is the server running?')
    } finally {
      setIsLoading(false)
    }
  }

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSubmit()
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <Card className="max-w-sm w-full p-8 shadow-lg">
          <div className="flex flex-col gap-5">
            <div className="flex flex-col items-center gap-2 text-center">
              <Shield className="text-primary" size={40} weight="duotone" />
              <h1 className="font-bold text-2xl tracking-tight text-foreground">
                {manifest.title}
              </h1>
              <p className="text-sm text-muted-foreground">
                {mode === 'login' ? 'Sign in to continue' : 'Create your account'}
              </p>
            </div>

            <div className="flex flex-col gap-3">
              <Input
                placeholder="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onKeyDown={handleKey}
                disabled={isLoading}
                autoFocus
              />
              <Input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={handleKey}
                disabled={isLoading}
              />
            </div>

            {error && (
              <p className="text-sm text-destructive text-center">{error}</p>
            )}

            <Button
              onClick={handleSubmit}
              disabled={isLoading}
              className="w-full bg-accent hover:bg-accent/90 text-accent-foreground font-medium"
            >
              {isLoading
                ? 'Please wait…'
                : mode === 'login'
                ? 'Sign In'
                : 'Create Account'}
            </Button>

            <button
              className="text-xs text-muted-foreground hover:text-foreground transition-colors text-center"
              onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null) }}
            >
              {mode === 'login'
                ? "Don't have an account? Register"
                : 'Already have an account? Sign in'}
            </button>
          </div>
        </Card>
      </motion.div>
    </div>
  )
}

function ConsentScreen({
  manifest,
  onConsent,
}: {
  manifest: UiManifest
  onConsent: () => void
}) {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <Card className="max-w-lg w-full p-8 shadow-lg">
          <div className="flex flex-col gap-6 items-center text-center">
            <Shield className="text-primary" size={48} weight="duotone" />
            <h1 className="font-bold text-3xl md:text-4xl tracking-tight text-foreground">
              {manifest.consent_heading}
            </h1>
            <div className="bg-muted p-6 rounded-lg">
              <p className="text-base leading-relaxed text-foreground">
                {manifest.consent_text}
              </p>
            </div>
            <Button
              onClick={onConsent}
              size="lg"
              className="w-full bg-accent hover:bg-accent/90 text-accent-foreground font-medium tracking-wide transition-all hover:shadow-lg hover:-translate-y-0.5"
            >
              {manifest.consent_button_label}
            </Button>
          </div>
        </Card>
      </motion.div>
    </div>
  )
}

class MessageErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="ml-11 text-sm text-destructive">
          Something went wrong rendering this message.
        </div>
      )
    }
    return this.props.children
  }
}

function ChatMessage({ message, token, userRole }: { message: Message; token?: string; userRole?: string }) {
  const isUser = message.role === 'user'
  
  return (
    <div className="flex flex-col gap-2">
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
        className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}
      >
        <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
          isUser ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
        }`}>
          {isUser ? <User size={18} weight="bold" /> : <Robot size={18} weight="bold" />}
        </div>
        <div className={`max-w-[75%] md:max-w-[65%] rounded-2xl px-4 py-3 ${
          isUser 
            ? 'bg-primary text-primary-foreground rounded-tr-sm' 
            : 'bg-card border border-border text-card-foreground rounded-tl-sm'
        }`}>
          <p className="text-base leading-relaxed whitespace-pre-wrap break-words">
            {message.content}
          </p>
        </div>
      </motion.div>
      {message.structured_content?.type === 'action_card' && token && (
        <div className="ml-11 max-w-[75%] md:max-w-[65%]">
          <ActionCard card={message.structured_content as ActionCardData} token={token} userRole={userRole} />
        </div>
      )}
      {message.structured_content?.type === 'query_result' && (
        <div className="ml-11 max-w-[75%] md:max-w-[65%]">
          <QueryResultCard data={message.structured_content as QueryResultData} />
        </div>
      )}
      {message.structured_content?.type === 'clarification' && (
        <div className="ml-11 max-w-[75%] md:max-w-[65%]">
          <ClarificationCard data={message.structured_content as ClarificationData} />
        </div>
      )}
    </div>
  )
}

function LoadingIndicator() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="flex gap-3"
    >
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-muted text-muted-foreground flex items-center justify-center">
        <Robot size={18} weight="bold" />
      </div>
      <div className="bg-card border border-border rounded-2xl rounded-tl-sm px-4 py-3">
        <div className="flex gap-1">
          {[0, 1, 2].map((i) => (
            <motion.div
              key={i}
              className="w-2 h-2 bg-muted-foreground rounded-full"
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{
                duration: 1.2,
                repeat: Infinity,
                delay: i * 0.2,
              }}
            />
          ))}
        </div>
      </div>
    </motion.div>
  )
}

function AppHeader({
  manifest,
  auth,
  onLogout,
  showDashboard,
  view,
  onViewChange,
  unreadCount,
  onClearUnread,
  hasSidebar,
  sidebarOpen,
  onToggleSidebar,
  sessionPanelOpen,
  onToggleSessionPanel,
}: {
  manifest: UiManifest
  auth: AuthState
  onLogout: () => void
  showDashboard: boolean
  view: 'chat' | 'dashboard'
  onViewChange: (v: 'chat' | 'dashboard') => void
  unreadCount?: number
  onClearUnread?: () => void
  hasSidebar?: boolean
  sidebarOpen?: boolean
  onToggleSidebar?: () => void
  sessionPanelOpen?: boolean
  onToggleSessionPanel?: () => void
}) {
  return (
    <header className="border-b border-border bg-card px-6 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {onToggleSessionPanel && (
            <Button
              variant="ghost"
              size="icon"
              onClick={onToggleSessionPanel}
              title={sessionPanelOpen ? 'Hide conversations' : 'Show conversations'}
              className="h-8 w-8 text-muted-foreground hover:text-foreground"
            >
              <ChatCircle size={18} weight={sessionPanelOpen ? 'fill' : 'regular'} />
            </Button>
          )}
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-bold text-2xl md:text-3xl tracking-tight text-foreground">
                {manifest.title}
              </h1>
              {manifest.domain_label && (
                <span className="text-xs font-medium text-muted-foreground bg-muted px-2 py-0.5 rounded">
                  {manifest.domain_label}
                </span>
              )}
            </div>
            <p className="text-sm md:text-base text-muted-foreground mt-1">
              {manifest.subtitle}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {hasSidebar && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggleSidebar}
              title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
              className="text-muted-foreground hover:text-foreground"
            >
              <SidebarSimple size={18} />
            </Button>
          )}
          {showDashboard && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                const next = view === 'chat' ? 'dashboard' : 'chat'
                if (next === 'dashboard') onClearUnread?.()
                onViewChange(next)
              }}
              title={view === 'chat' ? 'Dashboard' : 'Back to Chat'}
              className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 relative"
            >
              <Gauge size={18} />
              <span className="hidden sm:inline text-sm">
                {view === 'chat' ? 'Dashboard' : 'Chat'}
              </span>
              {(unreadCount ?? 0) > 0 && view === 'chat' && (
                <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-destructive text-destructive-foreground text-[10px] font-bold px-1">
                  {unreadCount! > 99 ? '99+' : unreadCount}
                </span>
              )}
            </Button>
          )}
          <span className="text-sm text-muted-foreground hidden sm:block">
            {auth.username}
          </span>
          <Button
            variant="ghost"
            size="icon"
            onClick={onLogout}
            title="Sign out"
            className="text-muted-foreground hover:text-foreground"
          >
            <SignOut size={20} />
          </Button>
        </div>
      </div>
    </header>
  )
}

function ChatInterface({
  manifest,
  auth,
  onLogout,
  showDashboard,
  view,
  onViewChange,
  unreadCount,
  onClearUnread,
  roleLayout,
  domainId,
  domainKey,
}: {
  manifest: UiManifest
  auth: AuthState
  onLogout: () => void
  showDashboard: boolean
  view: 'chat' | 'dashboard'
  onViewChange: (v: 'chat' | 'dashboard') => void
  unreadCount?: number
  onClearUnread?: () => void
  roleLayout?: RoleLayout
  domainId?: string
  domainKey?: string
}) {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sessionFrozen, setSessionFrozen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  // Multi-session state
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionPanelOpen, setSessionPanelOpen] = useState(true)
  const [sessionRefreshKey, setSessionRefreshKey] = useState(0)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // ── Client-side transcript persistence ───────────────────
  const transcriptStoreRef = useRef<TranscriptStore>(createTranscriptStore())
  const sealRef = useRef<string>('')
  const sealMetadataRef = useRef<TranscriptMetadata | null>(null)
  const transcriptRef = useRef<TranscriptTurn[]>([])
  const turnCounterRef = useRef<number>(0)
  const sessionLabelRef = useRef<string>('')

  // ── Session management helpers ───────────────────────────
  const resetChatState = () => {
    setMessages([])
    setInputValue('')
    setSessionFrozen(false)
    sealRef.current = ''
    sealMetadataRef.current = null
    transcriptRef.current = []
    turnCounterRef.current = 0
    sessionLabelRef.current = ''
  }

  const saveCurrentSession = async () => {
    const meta = sealMetadataRef.current
    if (sessionId && sealRef.current && transcriptRef.current.length > 0 && meta) {
      await transcriptStoreRef.current.saveSession({
        sessionId,
        messages: transcriptRef.current,
        seal: sealRef.current,
        metadata: meta,
        updatedAt: Date.now(),
        label: sessionLabelRef.current || undefined,
      }).catch(() => {})
    }
  }

  const createNewSession = async () => {
    await saveCurrentSession()
    resetChatState()
    const newId = `${auth.userId}_${Date.now()}`
    setSessionId(newId)
    // Prune oldest sessions beyond cap
    const MAX_SESSIONS = 50
    const all = await transcriptStoreRef.current.listSessions()
    if (all.length >= MAX_SESSIONS) {
      all.sort((a, b) => a.updatedAt - b.updatedAt)
      const toDelete = all.slice(0, all.length - MAX_SESSIONS + 1)
      for (const s of toDelete) {
        await transcriptStoreRef.current.deleteSession(s.sessionId)
      }
    }
    setSessionRefreshKey((k) => k + 1)
  }

  const switchSession = async (targetId: string) => {
    if (targetId === sessionId) return
    await saveCurrentSession()
    resetChatState()
    setSessionId(targetId)
  }

  const deleteSession = async (targetId: string) => {
    await transcriptStoreRef.current.deleteSession(targetId)
    if (targetId === sessionId) {
      resetChatState()
      // Pick next session or create new
      const remaining = await transcriptStoreRef.current.listSessions()
      if (remaining.length > 0) {
        remaining.sort((a, b) => b.updatedAt - a.updatedAt)
        setSessionId(remaining[0].sessionId)
      } else {
        const newId = `${auth.userId}_${Date.now()}`
        setSessionId(newId)
      }
    }
    setSessionRefreshKey((k) => k + 1)
  }

  // On mount: pick most recent session or create a new one.
  // Also handles migration from old single-session format.
  useEffect(() => {
    if (!auth.token) return
    const store = transcriptStoreRef.current
    ;(async () => {
      const sessions = await store.listSessions()
      if (sessions.length > 0) {
        sessions.sort((a, b) => b.updatedAt - a.updatedAt)
        setSessionId(sessions[0].sessionId)
      } else {
        // Migrate old single-session key if present
        const oldSession = await store.loadSession(`user_${auth.userId}`)
        if (oldSession && oldSession.messages.length > 0) {
          const migratedId = `${auth.userId}_migrated`
          await store.saveSession({ ...oldSession, sessionId: migratedId })
          await store.deleteSession(`user_${auth.userId}`)
          setSessionId(migratedId)
        } else {
          setSessionId(`${auth.userId}_${Date.now()}`)
        }
      }
      setSessionRefreshKey((k) => k + 1)
    })()
  }, [auth.token, auth.userId])

  // Attempt to resume a locally-stored session when sessionId changes
  useEffect(() => {
    if (!sessionId || !auth.token) return
    const store = transcriptStoreRef.current
    ;(async () => {
      try {
        const stored = await store.loadSession(sessionId)
        if (!stored || !stored.seal || stored.messages.length === 0) return

        const res = await fetch(`${getApiBase()}/api/session/${sessionId}/resume`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${auth.token}`,
          },
          body: JSON.stringify({
            transcript: stored.messages,
            metadata: stored.metadata,
            seal: stored.seal,
          }),
        })

        if (res.ok) {
          // Restore messages to UI state
          const restored: Message[] = stored.messages.flatMap((t) => [
            { role: 'user' as const, content: t.user, id: `user-r-${t.turn}` },
            { role: 'assistant' as const, content: t.assistant, id: `assistant-r-${t.turn}` },
          ])
          setMessages(restored)
          sealRef.current = stored.seal
          sealMetadataRef.current = stored.metadata
          transcriptRef.current = stored.messages
          turnCounterRef.current = stored.messages.length
          sessionLabelRef.current = stored.label ?? ''
        } else {
          // Server rejected the seal — wipe stale local data
          await store.deleteSession(sessionId)
          setSessionRefreshKey((k) => k + 1)
        }
      } catch {
        // Network error or store error — start fresh
      }
    })()
  }, [sessionId, auth.token]) // re-run when session/auth changes

  // Best-effort save on tab close / navigation
  useEffect(() => {
    const handler = () => {
      const meta = sealMetadataRef.current
      if (sessionId && sealRef.current && transcriptRef.current.length > 0 && meta) {
        transcriptStoreRef.current.saveSession({
          sessionId,
          messages: transcriptRef.current,
          seal: sealRef.current,
          metadata: meta,
          updatedAt: Date.now(),
          label: sessionLabelRef.current || undefined,
        }).catch(() => {})
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [sessionId])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, isLoading])

  const handleSend = async () => {
    const trimmedInput = inputValue.trim()
    if (!trimmedInput || isLoading) return

    const userMessage: Message = {
      role: 'user',
      content: trimmedInput,
      id: `user-${Date.now()}`,
    }

    setMessages((prev) => [...prev, userMessage])
    setInputValue('')
    setIsLoading(true)

    try {
      // ── Slash command detection ──────────────────────────
      const slashCmd = parseSlashCommand(trimmedInput)
      if (slashCmd) {
        // /help is client-side only
        if (slashCmd.operation === null) {
          const effectiveRole = roleLayout?.effective_role ?? 'student'
          const helpText = generateHelpText(effectiveRole)
          const helpMessage: Message = {
            role: 'assistant',
            content: helpText,
            id: `assistant-${Date.now()}`,
            meta: { action: 'slash_command', promptType: 'help' },
          }
          setMessages((prev) => [...prev, helpMessage])
          setIsLoading(false)
          return
        }

        // Direct dispatch to /api/admin/command
        const cmdResponse = await adminCommandCall(slashCmd.operation, slashCmd.params, auth, domainId)
        const resultData = cmdResponse.result ?? {}
        const content = cmdResponse.hitl_exempt
          ? (resultData as Record<string, unknown>).message as string ?? `Command executed: ${slashCmd.operation}`
          : `Command staged for approval (ID: ${cmdResponse.staged_id})`

        const cmdMessage: Message = {
          role: 'assistant',
          content,
          id: `assistant-${Date.now()}`,
          meta: { action: 'slash_command', promptType: slashCmd.operation },
          structured_content: cmdResponse.structured_content ?? (
            cmdResponse.hitl_exempt && resultData
              ? { type: 'query_result', operation: slashCmd.operation, result: resultData } as QueryResultData
              : undefined
          ),
        }
        setMessages((prev) => [...prev, cmdMessage])
        setIsLoading(false)
        return
      }

      // ── Normal chat flow ────────────────────────────────
      const apiResponse = await orchestratorApiCall(trimmedInput, sessionId, auth)

      const assistantMessage: Message = {
        role: 'assistant',
        content: apiResponse.response,
        id: `assistant-${Date.now()}`,
        meta: {
          action: apiResponse.action,
          promptType: apiResponse.prompt_type,
          escalated: apiResponse.escalated,
        },
        structured_content: apiResponse.structured_content as ActionCardData | undefined,
      }
      setMessages((prev) => [...prev, assistantMessage])

      // ── Session freeze / unlock tracking ───────────────
      if (apiResponse.escalated || apiResponse.action === 'session_frozen' || apiResponse.action === 'user_frozen') {
        setSessionFrozen(true)
      } else if (apiResponse.action === 'session_unlocked') {
        setSessionFrozen(false)
      }

      // ── Persist transcript locally with rolling seal ───
      if (apiResponse.transcript_seal && apiResponse.transcript_seal_metadata) {
        sealRef.current = apiResponse.transcript_seal
        sealMetadataRef.current = apiResponse.transcript_seal_metadata
        turnCounterRef.current += 1
        // Auto-extract label from first user message
        if (!sessionLabelRef.current && trimmedInput) {
          sessionLabelRef.current = trimmedInput.length > 40
            ? trimmedInput.slice(0, 40) + '…'
            : trimmedInput
        }
        // Use the server-authoritative transcript snapshot when available
        // to eliminate timestamp drift between client and server that
        // causes HMAC seal verification to fail on session resume.
        // See: docs/7-concepts/zero-trust-architecture.md
        if (apiResponse.transcript_snapshot && Array.isArray(apiResponse.transcript_snapshot)) {
          transcriptRef.current = apiResponse.transcript_snapshot as TranscriptTurn[]
        } else {
          const turn: TranscriptTurn = {
            turn: turnCounterRef.current,
            user: trimmedInput,
            assistant: apiResponse.response,
            ts: Date.now() / 1000,
            domain_id: apiResponse.transcript_seal_metadata?.domain_id ?? '',
          }
          transcriptRef.current = [...transcriptRef.current, turn]
        }
        if (sessionId) {
          transcriptStoreRef.current.saveSession({
            sessionId,
            messages: transcriptRef.current,
            seal: sealRef.current,
            metadata: apiResponse.transcript_seal_metadata!,
            updatedAt: Date.now(),
            label: sessionLabelRef.current || undefined,
          }).then(() => {
            setSessionRefreshKey((k) => k + 1)
          }).catch(() => {})
        }
      } else {
        console.warn('[lumina] transcript_seal missing from API response — transcript not persisted this turn')
      }
    } catch (error) {
      const errorMessage: Message = {
        role: 'assistant',
        content: 'Sorry, the API request failed. Check that the Lumina API server is running on port 8000.',
        id: `error-${Date.now()}`,
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const showSlashPalette = !sessionFrozen && inputValue.startsWith('/') && !inputValue.includes(' ')

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (showSlashPalette && (e.key === 'Tab' || e.key === 'Escape')) {
      // Let the palette handle Tab (autocomplete) and Escape (dismiss)
      // Palette selection is handled via onSelect callback
      if (e.key === 'Tab') {
        e.preventDefault()
        // The palette's onSelect will fire via the component
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setInputValue('')
      }
      return
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Save transcript to IndexedDB before calling the parent logout handler.
  // The beforeunload handler does NOT fire on React state-driven logouts,
  // so we must explicitly save here to survive the re-login cycle.
  const handleLogoutWithSave = async () => {
    const meta = sealMetadataRef.current
    if (sessionId && sealRef.current && transcriptRef.current.length > 0 && meta) {
      try {
        await transcriptStoreRef.current.saveSession({
          sessionId,
          messages: transcriptRef.current,
          seal: sealRef.current,
          metadata: meta,
          updatedAt: Date.now(),
          label: sessionLabelRef.current || undefined,
        })
      } catch { /* best-effort — proceed to logout */ }
    }
    onLogout()
  }

  return (
    <div className="min-h-screen flex flex-col">
      <AppHeader
        manifest={manifest}
        auth={auth}
        onLogout={handleLogoutWithSave}
        showDashboard={showDashboard}
        view={view}
        onViewChange={onViewChange}
        unreadCount={unreadCount}
        onClearUnread={onClearUnread}
        hasSidebar={(roleLayout?.sidebar_panels?.length ?? 0) > 0}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
        sessionPanelOpen={sessionPanelOpen}
        onToggleSessionPanel={() => setSessionPanelOpen((v) => !v)}
      />

      <div className="flex-1 flex overflow-hidden">
        {/* Session history panel */}
        {sessionPanelOpen && (
          <SessionPanel
            store={transcriptStoreRef.current}
            activeSessionId={sessionId}
            onSelect={switchSession}
            onNew={createNewSession}
            onDelete={deleteSession}
            refreshKey={sessionRefreshKey}
          />
        )}

        {/* Chat column */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <ScrollArea className="flex-1 px-6">
            <div className="max-w-3xl mx-auto py-6 flex flex-col gap-4">
              {messages.map((message) => (
                <div key={message.id} className="flex flex-col gap-1">
                  <MessageErrorBoundary>
                    <ChatMessage message={message} token={auth.token} userRole={auth.role} />
                  </MessageErrorBoundary>
                  {message.role === 'assistant' && message.meta && (
                    <div className="text-xs text-muted-foreground px-11">
                      action: {message.meta.action ?? 'n/a'} | prompt: {message.meta.promptType ?? 'n/a'}
                      {message.meta.escalated ? ' | escalated: yes' : ''}
                    </div>
                  )}
                </div>
              ))}
              <AnimatePresence>
                {isLoading && <LoadingIndicator />}
              </AnimatePresence>
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>

          <div className="border-t border-border bg-card px-6 py-4">
            {sessionFrozen && (
              <div className="max-w-3xl mx-auto mb-3 rounded-lg bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-300 dark:border-yellow-700 px-4 py-2 text-sm text-yellow-800 dark:text-yellow-200 flex items-center gap-2">
                <Warning size={16} weight="bold" />
                <span>Session locked — enter the 6-digit PIN from your teacher to continue.</span>
              </div>
            )}
            <div className="max-w-3xl mx-auto flex gap-3 items-end relative">
              <SlashCommandPalette
                inputValue={inputValue}
                effectiveRole={roleLayout?.effective_role ?? 'student'}
                onSelect={(text) => setInputValue(text)}
                visible={showSlashPalette}
              />
              <Input
                id="chat-input"
                value={inputValue}
                onChange={(e) => {
                  if (sessionFrozen) {
                    // Only allow digits, max 6 characters
                    const val = e.target.value.replace(/\D/g, '').slice(0, 6)
                    setInputValue(val)
                  } else {
                    setInputValue(e.target.value)
                  }
                }}
                onKeyDown={handleKeyPress}
                placeholder={sessionFrozen ? '6-digit PIN' : (manifest.input_placeholder ?? manifest.placeholder_text)}
                disabled={isLoading}
                className="flex-1 text-base"
                inputMode={sessionFrozen ? 'numeric' : undefined}
                pattern={sessionFrozen ? '\\d{6}' : undefined}
              />
              <Button
                onClick={handleSend}
                disabled={!inputValue.trim() || isLoading}
                size="icon"
                className="bg-primary hover:bg-primary/90 text-primary-foreground h-10 w-10"
              >
                <PaperPlaneRight size={20} weight="bold" />
              </Button>
            </div>
          </div>
        </div>

        {/* Role sidebar */}
        {sidebarOpen && roleLayout && (roleLayout.sidebar_panels?.length ?? 0) > 0 && (
          <RoleSidebar
            roleLayout={roleLayout}
            auth={auth}
            onClose={() => setSidebarOpen(false)}
            domainId={domainId}
            domainKey={domainKey}
          />
        )}
      </div>
    </div>
  )
}

function App() {
  const [auth, setAuth] = useState<AuthState | null>(() => {
    if (typeof window === 'undefined') return null
    try {
      const stored = window.localStorage.getItem('lumina.auth')
      return stored ? (JSON.parse(stored) as AuthState) : null
    } catch {
      return null
    }
  })
  const [consentGiven, setConsentGiven] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem('lumina.consent_given') === 'true'
  })
  const [manifest, setManifest] = useState<UiManifest>(DEFAULT_MANIFEST)
  const [roleLayout, setRoleLayout] = useState<RoleLayout | undefined>(undefined)
  const [domainId, setDomainId] = useState<string | undefined>(undefined)
  const [domainKey, setDomainKey] = useState<string | undefined>(undefined)
  const [view, setView] = useState<'chat' | 'dashboard'>('chat')
  const showDashboard = auth !== null && (auth.role === 'root' || auth.role === 'domain_authority')

  // SSE event stream for governance-role users
  const { unreadCount, clearUnread } = useEventStream({
    token: auth?.token ?? '',
    enabled: showDashboard && consentGiven,
  })

  // Validate stored token against /api/auth/me on mount; clear if stale
  useEffect(() => {
    if (auth === null) return
    fetch(`${getApiBase()}/api/auth/me`, {
      headers: { Authorization: `Bearer ${auth.token}` },
    }).then((res) => {
      if (res.status === 401) {
        localStorage.removeItem('lumina.auth')
        setAuth(null)
      }
    }).catch(() => {
      // Network error — keep auth so the user can still see the login screen
    })
  }, [])

  useEffect(() => {
    fetchDomainInfo(auth?.token).then((info) => {
      if (!info) return
      setManifest(info.ui_manifest)
      applyThemeOverrides(info.ui_manifest.theme)
      setRoleLayout(info.role_layout)
      setDomainId(info.domain_id)
      setDomainKey(info.domain_key)
    })
  }, [auth?.token])

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('lumina.consent_given', String(consentGiven))
    }
  }, [consentGiven])

  const handleAuth = (newAuth: AuthState) => {
    setAuth(newAuth)
    setConsentGiven(false)
  }

  const handleLogout = () => {
    localStorage.removeItem('lumina.auth')
    setAuth(null)
    setConsentGiven(false)
  }

  if (auth === null) {
    const setupToken = new URLSearchParams(window.location.search).get('token')
    if (setupToken) {
      return <SetupPasswordPage token={setupToken} onAuth={handleAuth} title={manifest.title} />
    }
    return <LoginScreen manifest={manifest} onAuth={handleAuth} />
  }

  const isGovernanceRole = ['root', 'domain_authority', 'it_support', 'qa', 'auditor'].includes(auth.role)
  if (!consentGiven && !isGovernanceRole) {
    return (
      <ConsentScreen
        manifest={manifest}
        onConsent={async () => {
          try {
            await fetch(`${getApiBase()}/api/consent/accept`, {
              method: 'POST',
              headers: { Authorization: `Bearer ${auth.token}` },
            })
          } catch {
            // Backend consent recording is best-effort; proceed regardless
          }
          setConsentGiven(true)
        }}
      />
    )
  }

  const showDashboardView = view === 'dashboard' && showDashboard

  return (
    <>
      {showDashboardView && (
        <div className="min-h-screen flex flex-col">
          <AppHeader
            manifest={manifest}
            auth={auth}
            onLogout={handleLogout}
            showDashboard={showDashboard}
            view={view}
            onViewChange={setView}
            unreadCount={unreadCount}
            onClearUnread={clearUnread}
          />
          <DashboardPage auth={auth} manifest={manifest} />
        </div>
      )}
      <div style={{ display: showDashboardView ? 'none' : undefined }}>
        <ChatInterface
          manifest={manifest}
          auth={auth}
          onLogout={handleLogout}
          showDashboard={showDashboard}
          view={view}
          onViewChange={setView}
          unreadCount={unreadCount}
          onClearUnread={clearUnread}
          roleLayout={roleLayout}
          domainId={domainId}
          domainKey={domainKey}
        />
      </div>
    </>
  )
}

export default App
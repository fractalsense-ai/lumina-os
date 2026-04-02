import { useState, useEffect, useRef, Component, type ReactNode } from 'react'
import { Shield, PaperPlaneRight, User, Robot, SignOut, Gauge, Bell, SidebarSimple } from '@phosphor-icons/react'
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
import {
  createTranscriptStore,
  type TranscriptStore,
  type TranscriptTurn,
  type TranscriptMetadata,
  type StoredSession,
} from '@/services/transcriptStore'

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

function ChatMessage({ message, token }: { message: Message; token?: string }) {
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
          <ActionCard card={message.structured_content as ActionCardData} token={token} />
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
}) {
  return (
    <header className="border-b border-border bg-card px-6 py-4">
      <div className="flex items-center justify-between">
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
}) {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  // Stable session_id tied to the authenticated user
  const [sessionId] = useState<string>(`user_${auth.userId}`)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // ── Client-side transcript persistence ───────────────────
  const transcriptStoreRef = useRef<TranscriptStore>(createTranscriptStore())
  const sealRef = useRef<string>('')
  const sealMetadataRef = useRef<TranscriptMetadata | null>(null)
  const transcriptRef = useRef<TranscriptTurn[]>([])
  const turnCounterRef = useRef<number>(0)

  // Attempt to resume a locally-stored session on mount
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
        } else {
          // Server rejected the seal — wipe stale local data
          await store.deleteSession(sessionId)
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
      if (sealRef.current && transcriptRef.current.length > 0 && meta) {
        transcriptStoreRef.current.saveSession({
          sessionId,
          messages: transcriptRef.current,
          seal: sealRef.current,
          metadata: meta,
          updatedAt: Date.now(),
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

      // ── Persist transcript locally with rolling seal ───
      if (apiResponse.transcript_seal && apiResponse.transcript_seal_metadata) {
        sealRef.current = apiResponse.transcript_seal
        sealMetadataRef.current = apiResponse.transcript_seal_metadata
        turnCounterRef.current += 1
        const turn: TranscriptTurn = {
          turn: turnCounterRef.current,
          user: trimmedInput,
          assistant: apiResponse.response,
          ts: Date.now() / 1000,
          domain_id: apiResponse.transcript_seal_metadata?.domain_id ?? '',
        }
        transcriptRef.current = [...transcriptRef.current, turn]
        transcriptStoreRef.current.saveSession({
          sessionId,
          messages: transcriptRef.current,
          seal: sealRef.current,
          metadata: apiResponse.transcript_seal_metadata!,
          updatedAt: Date.now(),
        }).catch(() => {})
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

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Save transcript to IndexedDB before calling the parent logout handler.
  // The beforeunload handler does NOT fire on React state-driven logouts,
  // so we must explicitly save here to survive the re-login cycle.
  const handleLogoutWithSave = () => {
    const meta = sealMetadataRef.current
    if (sealRef.current && transcriptRef.current.length > 0 && meta) {
      transcriptStoreRef.current.saveSession({
        sessionId,
        messages: transcriptRef.current,
        seal: sealRef.current,
        metadata: meta,
        updatedAt: Date.now(),
      }).catch(() => {})
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
      />

      <div className="flex-1 flex overflow-hidden">
        {/* Chat column */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <ScrollArea className="flex-1 px-6">
            <div className="max-w-3xl mx-auto py-6 flex flex-col gap-4">
              {messages.map((message) => (
                <div key={message.id} className="flex flex-col gap-1">
                  <MessageErrorBoundary>
                    <ChatMessage message={message} token={auth.token} />
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
            <div className="max-w-3xl mx-auto flex gap-3 items-end">
              <Input
                id="chat-input"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyPress}
                placeholder={manifest.input_placeholder ?? manifest.placeholder_text}
                disabled={isLoading}
                className="flex-1 text-base"
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
    })
  }, [auth?.token])

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('lumina.consent_given', String(consentGiven))
    }
  }, [consentGiven])

  const handleAuth = (newAuth: AuthState) => {
    setAuth(newAuth)
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
        />
      </div>
    </>
  )
}

export default App
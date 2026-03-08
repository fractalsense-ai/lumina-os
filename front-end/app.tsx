import { useState, useEffect, useRef } from 'react'
import { Shield, PaperPlaneRight, User, Robot } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { motion, AnimatePresence } from 'framer-motion'

interface Message {
  role: 'user' | 'assistant'
  content: string
  id: string
  meta?: {
    action?: string
    promptType?: string
    escalated?: boolean
  }
}

type ApiChatResponse = {
  session_id: string
  response: string
  action: string
  prompt_type: string
  escalated: boolean
}

async function orchestratorApiCall(
  userText: string,
  sessionId: string | null,
): Promise<ApiChatResponse> {
  const apiBase = (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
  const res = await fetch(`${apiBase}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
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

function ConsentScreen({ onConsent }: { onConsent: () => void }) {
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
              Project Lumina
            </h1>
            <div className="bg-muted p-6 rounded-lg">
              <p className="text-base leading-relaxed text-foreground">
                I am not grading you for a report card. I do not keep transcripts of what you say. 
                If we get stuck, we ask for human help.
              </p>
            </div>
            <Button
              onClick={onConsent}
              size="lg"
              className="w-full bg-accent hover:bg-accent/90 text-accent-foreground font-medium tracking-wide transition-all hover:shadow-lg hover:-translate-y-0.5"
            >
              I Agree to the Magic Circle
            </Button>
          </div>
        </Card>
      </motion.div>
    </div>
  )
}

function ChatMessage({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  
  return (
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

function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

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
      const apiResponse = await orchestratorApiCall(trimmedInput, sessionId)
      setSessionId(apiResponse.session_id)

      const assistantMessage: Message = {
        role: 'assistant',
        content: apiResponse.response,
        id: `assistant-${Date.now()}`,
        meta: {
          action: apiResponse.action,
          promptType: apiResponse.prompt_type,
          escalated: apiResponse.escalated,
        },
      }
      setMessages((prev) => [...prev, assistantMessage])
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

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border bg-card px-6 py-4">
        <h1 className="font-bold text-2xl md:text-3xl tracking-tight text-foreground">
          Project Lumina
        </h1>
        <p className="text-sm md:text-base text-muted-foreground mt-1">
          Algebra Level 1 - Foundations
        </p>
      </header>

      <div className="flex-1 flex flex-col overflow-hidden">
        <ScrollArea className="flex-1 px-6">
          <div className="max-w-3xl mx-auto py-6 flex flex-col gap-4">
            {messages.map((message) => (
              <div key={message.id} className="flex flex-col gap-1">
                <ChatMessage message={message} />
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
              placeholder="Type your steps here..."
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
    </div>
  )
}

function App() {
  const [consentGiven, setConsentGiven] = useState<boolean>(() => {
    if (typeof window === 'undefined') {
      return false
    }
    return window.localStorage.getItem('lumina.consent_given') === 'true'
  })

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('lumina.consent_given', String(consentGiven))
    }
  }, [consentGiven])

  const handleConsent = () => {
    setConsentGiven(true)
  }

  if (!consentGiven) {
    return <ConsentScreen onConsent={handleConsent} />
  }

  return <ChatInterface />
}

export default App
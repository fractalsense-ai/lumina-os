import { useState } from 'react'
import { Shield } from '@phosphor-icons/react'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { motion } from 'framer-motion'

function getApiBase(): string {
  return (import.meta as any).env?.VITE_LUMINA_API_BASE_URL ?? 'http://localhost:8000'
}

interface AuthState {
  token: string
  userId: string
  username: string
  role: string
}

interface SetupPasswordPageProps {
  token: string
  onAuth: (auth: AuthState) => void
  title?: string
}

export function SetupPasswordPage({ token, onAuth, title = 'Lumina' }: SetupPasswordPageProps) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async () => {
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    setError(null)
    setIsLoading(true)
    try {
      const res = await fetch(`${getApiBase()}/api/auth/setup-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body?.detail ?? 'Setup failed. The link may have expired.')
        return
      }
      const data = await res.json()
      const auth: AuthState = {
        token: data.access_token,
        userId: data.user_id,
        username: '',
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
                {title}
              </h1>
              <p className="text-sm text-muted-foreground">
                Set your password to activate your account
              </p>
            </div>

            <div className="flex flex-col gap-3">
              <Input
                type="password"
                placeholder="New password (min 8 characters)"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={handleKey}
                disabled={isLoading}
                autoFocus
              />
              <Input
                type="password"
                placeholder="Confirm password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
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
              {isLoading ? 'Please wait…' : 'Set Password & Sign In'}
            </Button>
          </div>
        </Card>
      </motion.div>
    </div>
  )
}

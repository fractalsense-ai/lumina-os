import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { CheckCircle, Copy, EnvelopeSimple } from '@phosphor-icons/react'

interface InviteLinkDisplayProps {
  setupUrl: string
  username: string
  emailSent: boolean
}

export function InviteLinkDisplay({ setupUrl, username, emailSent }: InviteLinkDisplayProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(setupUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback for insecure contexts
      const ta = document.createElement('textarea')
      ta.value = setupUrl
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <Card className="p-3 mt-2 border border-blue-200 bg-blue-50/50 dark:border-blue-800 dark:bg-blue-950/30">
      <p className="text-xs font-medium text-blue-700 dark:text-blue-300 mb-1">
        Setup link for {username}
      </p>
      <div className="flex items-center gap-2">
        <a
          href={setupUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 text-xs bg-white dark:bg-black/20 border rounded px-2 py-1 truncate select-all text-blue-600 dark:text-blue-400 hover:underline"
        >
          {setupUrl}
        </a>
        <Button
          size="sm"
          variant="outline"
          onClick={handleCopy}
          className="shrink-0 gap-1 h-7 text-xs"
        >
          {copied
            ? <><CheckCircle size={14} className="text-green-500" /> Copied</>
            : <><Copy size={14} /> Copy</>
          }
        </Button>
      </div>
      <p className="text-[10px] text-muted-foreground mt-1.5 flex items-center gap-1">
        <EnvelopeSimple size={12} />
        {emailSent
          ? 'Invite email sent. Link also available above.'
          : 'No email configured — share this link with the user directly.'}
      </p>
    </Card>
  )
}

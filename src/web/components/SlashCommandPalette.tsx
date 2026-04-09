/**
 * SlashCommandPalette — autocomplete dropdown for slash commands.
 *
 * Appears above the chat input when the user types "/".
 * Filters by the current effective domain role and typed prefix.
 */

import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { getCommandsForRole, type SlashCommandDef } from '@/services/slashCommands'

interface SlashCommandPaletteProps {
  inputValue: string
  effectiveRole: string
  onSelect: (command: string) => void
  visible: boolean
}

export function SlashCommandPalette({
  inputValue,
  effectiveRole,
  onSelect,
  visible,
}: SlashCommandPaletteProps) {
  const [selectedIndex, setSelectedIndex] = useState(0)
  const listRef = useRef<HTMLUListElement>(null)

  // Get typed prefix after "/"
  const prefix = inputValue.startsWith('/')
    ? inputValue.slice(1).split(/\s/)[0]?.toLowerCase() ?? ''
    : ''

  const allCommands = getCommandsForRole(effectiveRole)
  const filtered = prefix
    ? allCommands.filter(
        (cmd) =>
          cmd.name.startsWith(prefix) ||
          (cmd.aliases ?? []).some((a) => a.startsWith(prefix)),
      )
    : allCommands

  // Reset selection when filter changes
  useEffect(() => {
    setSelectedIndex(0)
  }, [prefix])

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current) {
      const items = listRef.current.children
      if (items[selectedIndex]) {
        ;(items[selectedIndex] as HTMLElement).scrollIntoView({ block: 'nearest' })
      }
    }
  }, [selectedIndex])

  if (!visible || filtered.length === 0) return null

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Tab' || e.key === 'Enter') {
      e.preventDefault()
      const cmd = filtered[selectedIndex]
      if (cmd) {
        const argHint = cmd.args.length > 0 ? ' ' : ''
        onSelect(`/${cmd.name}${argHint}`)
      }
    } else if (e.key === 'Escape') {
      // Let parent handle
    }
  }

  return (
    <div
      className="absolute bottom-full left-0 right-0 mb-1 mx-auto max-w-3xl z-50"
      onKeyDown={handleKeyDown}
    >
      <ul
        ref={listRef}
        className="bg-card border border-border rounded-lg shadow-lg max-h-64 overflow-y-auto py-1"
        role="listbox"
        aria-label="Slash commands"
      >
        {filtered.map((cmd, i) => (
          <li
            key={cmd.name}
            role="option"
            aria-selected={i === selectedIndex ? 'true' : 'false'}
            className={`px-3 py-2 cursor-pointer flex items-center gap-3 text-sm ${
              i === selectedIndex ? 'bg-accent text-accent-foreground' : 'hover:bg-muted'
            }`}
            onMouseEnter={() => setSelectedIndex(i)}
            onMouseDown={(e) => {
              e.preventDefault()
              const argHint = cmd.args.length > 0 ? ' ' : ''
              onSelect(`/${cmd.name}${argHint}`)
            }}
          >
            <span className="font-mono text-primary">/{cmd.name}</span>
            {cmd.args.length > 0 && (
              <span className="text-muted-foreground font-mono text-xs">
                {cmd.args.map((a) => `<${a}>`).join(' ')}
              </span>
            )}
            <span className="text-muted-foreground ml-auto text-xs">{cmd.description}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * MathText — lightweight inline math renderer for chat messages.
 *
 * Converts plain-text fraction notation into styled HTML fraction
 * layout.  Supports two formats:
 *   - Parenthesized: (2)/(5)  or  (x)/(20)
 *   - Plain slash:   2/5  or  x/20
 * No external math library required.
 */
import { type ReactNode } from 'react'

// Parenthesized fractions: (numerator)/(denominator)
const PAREN_FRAC_RE = /\(([^()]+)\)\s*\/\s*\(([^()]+)\)/g

// Plain slash fractions: 2/5, x/20, 3x/4  (with word-boundary guards)
const PLAIN_FRAC_RE =
  /(?<!\w)([+-]?\d*[a-zA-Z]?\d*)\/(\d+[a-zA-Z]?\d*|[a-zA-Z])(?!\w)/g

function FractionSpan({ numerator, denominator }: { numerator: string; denominator: string }) {
  return (
    <span className="math-fraction inline-flex flex-col items-center mx-0.5 align-middle leading-none">
      <span className="text-[0.8em] border-b border-current px-0.5 pb-px">{numerator}</span>
      <span className="text-[0.8em] px-0.5 pt-px">{denominator}</span>
    </span>
  )
}

/** Apply a global regex to text, returning an array of ReactNodes. */
function applyFractionRegex(
  segments: (string | ReactNode)[],
  regex: RegExp,
  keyPrefix: string,
): (string | ReactNode)[] {
  const out: (string | ReactNode)[] = []
  for (const seg of segments) {
    if (typeof seg !== 'string') {
      out.push(seg)
      continue
    }
    let lastIndex = 0
    regex.lastIndex = 0
    let match: RegExpExecArray | null
    while ((match = regex.exec(seg)) !== null) {
      const [full, numerator, denominator] = match
      if (match.index > lastIndex) {
        out.push(seg.slice(lastIndex, match.index))
      }
      out.push(
        <FractionSpan
          key={`${keyPrefix}-${match.index}`}
          numerator={numerator.trim()}
          denominator={denominator.trim()}
        />,
      )
      lastIndex = match.index + full.length
    }
    if (lastIndex < seg.length) {
      out.push(seg.slice(lastIndex))
    }
  }
  return out
}

export function MathText({ text }: { text: string }) {
  // First pass: parenthesized fractions (higher priority)
  let parts: (string | ReactNode)[] = [text]
  parts = applyFractionRegex(parts, PAREN_FRAC_RE, 'pf')
  // Second pass: plain slash fractions on remaining text segments
  parts = applyFractionRegex(parts, PLAIN_FRAC_RE, 'sf')

  if (parts.length === 1 && parts[0] === text) {
    return <>{text}</>
  }

  return <>{parts}</>
}

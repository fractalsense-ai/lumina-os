import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function collectSourceFiles(dir: string): string[] {
  const entries = fs.readdirSync(dir, { withFileTypes: true })
  const files: string[] = []

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      files.push(...collectSourceFiles(fullPath))
      continue
    }
    if (entry.name.endsWith('.ts') || entry.name.endsWith('.tsx')) {
      if (entry.name === 'secret-hygiene.test.ts') {
        continue
      }
      files.push(fullPath)
    }
  }

  return files
}

describe('Secret hygiene', () => {
  it('frontend source does not reference openaikey.md', () => {
    const root = path.resolve(__dirname, '..')
    const files = collectSourceFiles(root)

    for (const file of files) {
      const text = fs.readFileSync(file, 'utf-8')
      expect(text, `Forbidden key file reference in ${file}`).not.toMatch(
        /(import\s+.*openaikey\.md|from\s+['"].*openaikey\.md|fetch\(.+openaikey\.md)/i,
      )
    }
  })
})

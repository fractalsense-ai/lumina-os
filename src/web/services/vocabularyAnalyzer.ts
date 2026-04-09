/**
 * vocabularyAnalyzer.ts — Client-side vocabulary complexity analysis
 *
 * Privacy model: chat content stays client-side.  Only the composite
 * complexity score is posted to the server as a single float.
 *
 * Metrics computed:
 * 1. Lexical diversity   — type/token ratio over student messages
 * 2. Average word length  — proxy for vocabulary sophistication
 * 3. Embedding spread     — cosine distance spread across per-message
 *    embeddings from Ollama (measures semantic variety)
 * 4. Domain term detection — counts recognised domain terms
 */

// ── Types ──────────────────────────────────────────────────

export interface VocabularyMetric {
  vocabulary_complexity_score: number
  lexical_diversity: number
  avg_word_length: number
  embedding_spread: number
  domain_terms_detected: string[]
  buffer_turns: number
  measurement_valid: boolean
}

export interface VocabAnalyzerConfig {
  ollamaBaseUrl?: string
  model?: string
  minTurns?: number
  domainTerms?: Record<string, string[]>  // module_id -> terms
}

// ── Defaults ───────────────────────────────────────────────

const DEFAULT_OLLAMA_BASE = 'http://localhost:11434'
const DEFAULT_MODEL = 'all-minilm:latest'
const DEFAULT_MIN_TURNS = 10

// ── Helpers ────────────────────────────────────────────────

function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9'\s-]/g, ' ')
    .split(/\s+/)
    .filter((w) => w.length > 0)
}

function computeLexicalDiversity(tokens: string[]): number {
  if (tokens.length === 0) return 0
  const types = new Set(tokens)
  return types.size / tokens.length
}

function computeAvgWordLength(tokens: string[]): number {
  if (tokens.length === 0) return 0
  const total = tokens.reduce((sum, w) => sum + w.length, 0)
  return total / tokens.length
}

function cosineSimilarity(a: number[], b: number[]): number {
  let dot = 0
  let magA = 0
  let magB = 0
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i]
    magA += a[i] * a[i]
    magB += b[i] * b[i]
  }
  const denom = Math.sqrt(magA) * Math.sqrt(magB)
  return denom === 0 ? 0 : dot / denom
}

function computeEmbeddingSpread(embeddings: number[][]): number {
  if (embeddings.length < 2) return 0
  let totalDist = 0
  let count = 0
  for (let i = 0; i < embeddings.length; i++) {
    for (let j = i + 1; j < embeddings.length; j++) {
      totalDist += 1 - cosineSimilarity(embeddings[i], embeddings[j])
      count++
    }
  }
  return count > 0 ? totalDist / count : 0
}

function detectDomainTerms(
  tokens: string[],
  domainTerms: Record<string, string[]>,
): string[] {
  const found: string[] = []
  const tokenSet = new Set(tokens)
  for (const [moduleId, terms] of Object.entries(domainTerms)) {
    for (const term of terms) {
      const termLower = term.toLowerCase()
      // Single-word terms: direct set lookup
      // Multi-word terms: check if all words present in token set
      const termTokens = termLower.split(/\s+/)
      if (termTokens.length === 1) {
        if (tokenSet.has(termLower)) {
          found.push(`${moduleId}:${term}`)
        }
      } else if (termTokens.every((t) => tokenSet.has(t))) {
        found.push(`${moduleId}:${term}`)
      }
    }
  }
  return found
}

// ── Embedding fetch ────────────────────────────────────────

async function fetchEmbeddings(
  texts: string[],
  baseUrl: string,
  model: string,
): Promise<number[][] | null> {
  if (texts.length === 0) return null
  try {
    const res = await fetch(`${baseUrl}/api/embed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, input: texts }),
    })
    if (!res.ok) return null
    const data = await res.json()
    return data.embeddings ?? null
  } catch {
    return null
  }
}

// ── Main analyzer ──────────────────────────────────────────

/**
 * Analyze the vocabulary complexity of student messages.
 *
 * @param studentMessages - Array of raw student message strings
 *   (only the student's own turns, NOT assistant responses)
 * @param config - Optional configuration overrides
 * @returns VocabularyMetric with the composite score,
 *   or null if analysis cannot be performed (too few turns, etc.)
 */
export async function analyzeVocabulary(
  studentMessages: string[],
  config?: VocabAnalyzerConfig,
): Promise<VocabularyMetric | null> {
  const minTurns = config?.minTurns ?? DEFAULT_MIN_TURNS
  const ollamaBase = config?.ollamaBaseUrl ?? DEFAULT_OLLAMA_BASE
  const model = config?.model ?? DEFAULT_MODEL
  const domainTerms = config?.domainTerms ?? {}

  if (studentMessages.length < minTurns) {
    return null
  }

  // Combine all student text for token-level analysis
  const allTokens = studentMessages.flatMap(tokenize)
  if (allTokens.length === 0) return null

  // 1. Lexical diversity (type-token ratio)
  const lexicalDiversity = computeLexicalDiversity(allTokens)

  // 2. Average word length
  const avgWordLength = computeAvgWordLength(allTokens)

  // 3. Embedding spread (semantic diversity)
  let embeddingSpread = 0
  const embeddings = await fetchEmbeddings(studentMessages, ollamaBase, model)
  if (embeddings && embeddings.length >= 2) {
    embeddingSpread = computeEmbeddingSpread(embeddings)
  }

  // 4. Domain term detection
  const domainTermsDetected = detectDomainTerms(allTokens, domainTerms)

  // ── Composite score ──────────────────────────────────
  // Weighted combination normalized to 0..1
  //   lexical diversity:  0..1 naturally (TTR)
  //   avg word length:    typically 3..8, normalize to 0..1
  //   embedding spread:   typically 0..1 (cosine distance)
  //   domain terms:       bonus, capped at 0.1 contribution
  const normWordLen = Math.min(1, Math.max(0, (avgWordLength - 3) / 5))
  const domainBonus = Math.min(0.1, domainTermsDetected.length * 0.02)

  const compositeScore = Math.min(
    1.0,
    lexicalDiversity * 0.35 +
      normWordLen * 0.25 +
      embeddingSpread * 0.30 +
      domainBonus * 0.10 / 0.1, // normalize the bonus weight
  )

  return {
    vocabulary_complexity_score: Math.round(compositeScore * 1000) / 1000,
    lexical_diversity: Math.round(lexicalDiversity * 1000) / 1000,
    avg_word_length: Math.round(avgWordLength * 100) / 100,
    embedding_spread: Math.round(embeddingSpread * 1000) / 1000,
    domain_terms_detected: domainTermsDetected,
    buffer_turns: studentMessages.length,
    measurement_valid: true,
  }
}

// ── Post metric to server ──────────────────────────────────

/**
 * Send the vocabulary complexity metric to the server.
 * Only the structured metric is sent — no chat content.
 */
export async function postVocabularyMetric(
  apiBase: string,
  token: string,
  userId: string,
  metric: VocabularyMetric,
): Promise<boolean> {
  try {
    const res = await fetch(`${apiBase}/api/user/${userId}/vocabulary-metric`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(metric),
    })
    return res.ok
  } catch {
    return false
  }
}

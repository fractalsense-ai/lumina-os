import { describe, expect, it, vi, beforeEach } from 'vitest'

import {
  analyzeVocabulary,
  postVocabularyMetric,
  type VocabularyMetric,
  type VocabAnalyzerConfig,
} from '@/services/vocabularyAnalyzer'

// ── analyzeVocabulary — lexical analysis ───────────────────

describe('analyzeVocabulary', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('returns null when fewer turns than minimum', async () => {
    const messages = ['hello', 'world']
    const result = await analyzeVocabulary(messages, { minTurns: 10 })
    expect(result).toBeNull()
  })

  it('returns null for empty messages array', async () => {
    const result = await analyzeVocabulary([])
    expect(result).toBeNull()
  })

  it('computes lexical diversity correctly', async () => {
    // Mock fetch to avoid real network calls to Ollama
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
    }))

    // 10 unique-token messages for diversity measurement
    const messages = Array.from({ length: 10 }, (_, i) =>
      `word${i} sentence${i} vocabulary${i} test${i}`,
    )
    const result = await analyzeVocabulary(messages, { minTurns: 10 })
    expect(result).not.toBeNull()
    expect(result!.lexical_diversity).toBeGreaterThan(0)
    expect(result!.lexical_diversity).toBeLessThanOrEqual(1)
  })

  it('computes avg word length', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))

    const messages = Array.from({ length: 10 }, () =>
      'photosynthesis electrochemistry thermodynamics',
    )
    const result = await analyzeVocabulary(messages, { minTurns: 10 })
    expect(result).not.toBeNull()
    // These are long words, avg should be > 10
    expect(result!.avg_word_length).toBeGreaterThan(10)
  })

  it('detects domain terms', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))

    const messages = Array.from({ length: 10 }, () =>
      'photosynthesis helps plants grow energy from sunlight',
    )
    const config: VocabAnalyzerConfig = {
      minTurns: 10,
      domainTerms: {
        biology: ['photosynthesis', 'sunlight'],
      },
    }
    const result = await analyzeVocabulary(messages, config)
    expect(result).not.toBeNull()
    expect(result!.domain_terms_detected).toContain('biology:photosynthesis')
    expect(result!.domain_terms_detected).toContain('biology:sunlight')
  })

  it('uses embedding spread when Ollama is available', async () => {
    // Mock successful Ollama embed response
    const mockEmbeddings = Array.from({ length: 10 }, (_, i) => {
      const emb = new Array(384).fill(0)
      emb[i % 384] = 1.0 // different directions -> high spread
      return emb
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ embeddings: mockEmbeddings }),
    }))

    const messages = Array.from({ length: 10 }, (_, i) => `message ${i} with content`)
    const result = await analyzeVocabulary(messages, { minTurns: 10 })
    expect(result).not.toBeNull()
    expect(result!.embedding_spread).toBeGreaterThan(0)
  })

  it('gracefully handles Ollama failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network error')))

    const messages = Array.from({ length: 10 }, (_, i) => `testing word${i} vocabulary`)
    const result = await analyzeVocabulary(messages, { minTurns: 10 })
    expect(result).not.toBeNull()
    // embedding_spread should be 0 on failure
    expect(result!.embedding_spread).toBe(0)
    // Other metrics should still work
    expect(result!.lexical_diversity).toBeGreaterThan(0)
  })

  it('score is between 0 and 1', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))

    const messages = Array.from({ length: 10 }, (_, i) => `complex word${i} sentence`)
    const result = await analyzeVocabulary(messages, { minTurns: 10 })
    expect(result).not.toBeNull()
    expect(result!.vocabulary_complexity_score).toBeGreaterThanOrEqual(0)
    expect(result!.vocabulary_complexity_score).toBeLessThanOrEqual(1)
  })

  it('sets buffer_turns to message count', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))

    const messages = Array.from({ length: 12 }, (_, i) => `hello world message ${i}`)
    const result = await analyzeVocabulary(messages, { minTurns: 10 })
    expect(result).not.toBeNull()
    expect(result!.buffer_turns).toBe(12)
  })

  it('sets measurement_valid to true', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))

    const messages = Array.from({ length: 10 }, () => 'some text here')
    const result = await analyzeVocabulary(messages, { minTurns: 10 })
    expect(result).not.toBeNull()
    expect(result!.measurement_valid).toBe(true)
  })
})

// ── postVocabularyMetric ───────────────────────────────────

describe('postVocabularyMetric', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('sends only metric, no chat content', async () => {
    let capturedBody: string | undefined
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      capturedBody = init.body as string
      return Promise.resolve({ ok: true })
    }))

    const metric: VocabularyMetric = {
      vocabulary_complexity_score: 0.45,
      lexical_diversity: 0.6,
      avg_word_length: 5.2,
      embedding_spread: 0.3,
      domain_terms_detected: ['biology:mitosis'],
      buffer_turns: 20,
      measurement_valid: true,
    }

    const ok = await postVocabularyMetric('http://localhost:8000', 'token123', 'user1', metric)
    expect(ok).toBe(true)

    // Verify request was made correctly
    expect(fetch).toHaveBeenCalledTimes(1)
    const [url, opts] = (fetch as any).mock.calls[0]
    expect(url).toBe('http://localhost:8000/api/user/user1/vocabulary-metric')
    expect(opts.method).toBe('POST')
    expect(opts.headers['Authorization']).toBe('Bearer token123')

    // Verify no chat content in body — only structured metric fields
    const body = JSON.parse(capturedBody!)
    expect(body.vocabulary_complexity_score).toBe(0.45)
    expect(body).not.toHaveProperty('messages')
    expect(body).not.toHaveProperty('content')
    expect(body).not.toHaveProperty('transcript')
  })

  it('returns false on network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    const metric: VocabularyMetric = {
      vocabulary_complexity_score: 0.5,
      lexical_diversity: 0.5,
      avg_word_length: 4.0,
      embedding_spread: 0.2,
      domain_terms_detected: [],
      buffer_turns: 15,
      measurement_valid: true,
    }
    const ok = await postVocabularyMetric('http://localhost:8000', 'tok', 'u1', metric)
    expect(ok).toBe(false)
  })

  it('returns false on server error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))

    const metric: VocabularyMetric = {
      vocabulary_complexity_score: 0.5,
      lexical_diversity: 0.5,
      avg_word_length: 4.0,
      embedding_spread: 0.2,
      domain_terms_detected: [],
      buffer_turns: 15,
      measurement_valid: true,
    }
    const ok = await postVocabularyMetric('http://localhost:8000', 'tok', 'u1', metric)
    expect(ok).toBe(false)
  })
})

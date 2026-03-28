/**
 * Client-side transcript persistence — IndexedDB primary, localStorage fallback.
 *
 * The server is a zero-knowledge processing engine: it never stores raw
 * transcripts at rest.  This module keeps the conversation on the user's
 * device, sealed with an HMAC signature the server can verify on resume.
 */

// ── Types ────────────────────────────────────────────────────

export interface TranscriptTurn {
  turn: number
  user: string
  assistant: string
  ts: number
  domain_id: string
}

export interface TranscriptMetadata {
  domain_id: string
  turn_count: number
  last_activity_utc: number
}

export interface StoredSession {
  sessionId: string
  messages: TranscriptTurn[]
  seal: string
  metadata: TranscriptMetadata
  updatedAt: number
}

export interface SessionSummary {
  sessionId: string
  turnCount: number
  updatedAt: number
  domainId: string
}

// ── Abstract interface ───────────────────────────────────────

export interface TranscriptStore {
  saveSession(session: StoredSession): Promise<void>
  loadSession(sessionId: string): Promise<StoredSession | null>
  deleteSession(sessionId: string): Promise<void>
  listSessions(): Promise<SessionSummary[]>
}

// ── IndexedDB implementation ─────────────────────────────────

const DB_NAME = 'lumina-transcripts'
const DB_VERSION = 1
const STORE_NAME = 'sessions'

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'sessionId' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

export class IndexedDBTranscriptStore implements TranscriptStore {
  async saveSession(session: StoredSession): Promise<void> {
    const db = await openDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      tx.objectStore(STORE_NAME).put(session)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
  }

  async loadSession(sessionId: string): Promise<StoredSession | null> {
    const db = await openDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly')
      const req = tx.objectStore(STORE_NAME).get(sessionId)
      req.onsuccess = () => resolve(req.result ?? null)
      req.onerror = () => reject(req.error)
    })
  }

  async deleteSession(sessionId: string): Promise<void> {
    const db = await openDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      tx.objectStore(STORE_NAME).delete(sessionId)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
  }

  async listSessions(): Promise<SessionSummary[]> {
    const db = await openDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly')
      const req = tx.objectStore(STORE_NAME).getAll()
      req.onsuccess = () => {
        const sessions: StoredSession[] = req.result ?? []
        resolve(
          sessions.map((s) => ({
            sessionId: s.sessionId,
            turnCount: s.messages.length,
            updatedAt: s.updatedAt,
            domainId: s.metadata.domain_id,
          })),
        )
      }
      req.onerror = () => reject(req.error)
    })
  }
}

// ── localStorage fallback ────────────────────────────────────

const LS_PREFIX = 'lumina.transcript.'

export class LocalStorageTranscriptStore implements TranscriptStore {
  async saveSession(session: StoredSession): Promise<void> {
    try {
      localStorage.setItem(LS_PREFIX + session.sessionId, JSON.stringify(session))
    } catch {
      console.warn('[TranscriptStore] localStorage write failed — storage may be full')
    }
  }

  async loadSession(sessionId: string): Promise<StoredSession | null> {
    const raw = localStorage.getItem(LS_PREFIX + sessionId)
    if (!raw) return null
    try {
      return JSON.parse(raw) as StoredSession
    } catch {
      return null
    }
  }

  async deleteSession(sessionId: string): Promise<void> {
    localStorage.removeItem(LS_PREFIX + sessionId)
  }

  async listSessions(): Promise<SessionSummary[]> {
    const summaries: SessionSummary[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key || !key.startsWith(LS_PREFIX)) continue
      try {
        const s = JSON.parse(localStorage.getItem(key)!) as StoredSession
        summaries.push({
          sessionId: s.sessionId,
          turnCount: s.messages.length,
          updatedAt: s.updatedAt,
          domainId: s.metadata.domain_id,
        })
      } catch {
        // corrupt entry — skip
      }
    }
    return summaries
  }
}

// ── Factory ──────────────────────────────────────────────────

export function createTranscriptStore(): TranscriptStore {
  if (typeof indexedDB !== 'undefined') {
    return new IndexedDBTranscriptStore()
  }
  return new LocalStorageTranscriptStore()
}

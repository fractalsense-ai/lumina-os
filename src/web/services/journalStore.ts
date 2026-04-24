/**
 * Client-side journal store — IndexedDB, zero-knowledge.
 *
 * Raw journal text and the local hash→displayName entity map are stored
 * exclusively on the client device.  Nothing in this file makes network
 * calls.  The server never sees raw journal text or entity names; it only
 * receives salted entity hashes alongside structured SVA evidence.
 *
 * Data model:
 *   entryId      — UUID, generated at save time
 *   sessionId    — Lumina session ID this turn belongs to
 *   timestamp    — Unix ms epoch
 *   rawText      — The user's raw journal input (local only, never sent)
 *   entityMap    — { entityHash → displayName }  (e.g. "Entity_A4F9" → "Mr. Davis")
 *   svaScores    — The SVA triple returned by the server for this turn
 *   turnNumber   — Optional sequential turn counter within the session
 */

const DB_NAME = 'lumina-journal';
const DB_VERSION = 1;
const STORE_NAME = 'entries';

export interface JournalEntry {
  entryId: string;
  sessionId: string;
  timestamp: number;
  rawText: string;
  entityMap: Record<string, string>;   // hash → displayName
  svaScores: { s: number; v: number; a: number } | null;
  turnNumber?: number;
}

// ── DB initialisation ─────────────────────────────────────────

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);

    req.onupgradeneeded = (evt) => {
      const db = (evt.target as IDBOpenDBRequest).result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'entryId' });
        store.createIndex('sessionId', 'sessionId', { unique: false });
        store.createIndex('timestamp', 'timestamp', { unique: false });
      }
    };

    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

// ── Public API ────────────────────────────────────────────────

/**
 * Persist a journal entry locally.  Returns the saved entry.
 */
export async function saveEntry(
  entry: Omit<JournalEntry, 'entryId'> & { entryId?: string },
): Promise<JournalEntry> {
  const db = await openDB();
  const full: JournalEntry = {
    entryId: entry.entryId ?? generateId(),
    sessionId: entry.sessionId,
    timestamp: entry.timestamp ?? Date.now(),
    rawText: entry.rawText,
    entityMap: entry.entityMap ?? {},
    svaScores: entry.svaScores ?? null,
    turnNumber: entry.turnNumber,
  };
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const req = tx.objectStore(STORE_NAME).put(full);
    req.onsuccess = () => resolve(full);
    req.onerror = () => reject(req.error);
  });
}

/**
 * List all entries, optionally filtered to a specific sessionId.
 * Results are ordered by timestamp ascending.
 */
export async function listEntries(sessionId?: string): Promise<JournalEntry[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const req = sessionId
      ? store.index('sessionId').getAll(IDBKeyRange.only(sessionId))
      : store.getAll();
    req.onsuccess = () => {
      const results: JournalEntry[] = req.result ?? [];
      results.sort((a, b) => a.timestamp - b.timestamp);
      resolve(results);
    };
    req.onerror = () => reject(req.error);
  });
}

/**
 * Delete a single entry by ID.
 */
export async function deleteEntry(entryId: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const req = tx.objectStore(STORE_NAME).delete(entryId);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

/**
 * Delete ALL journal entries.  Irreversible — used by the "delete my data"
 * flow.  If sessionId is provided, only entries for that session are deleted.
 */
export async function deleteAllEntries(sessionId?: string): Promise<void> {
  if (sessionId) {
    const entries = await listEntries(sessionId);
    for (const e of entries) {
      await deleteEntry(e.entryId);
    }
    return;
  }
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const req = tx.objectStore(STORE_NAME).clear();
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

/**
 * Resolve display names for a list of entity hashes using the entityMap
 * stored across all local journal entries.  Scans all entries so the
 * mapping survives across sessions.
 *
 * Returns a map { hash → displayName | hash } — unknown hashes fall back
 * to the hash string itself.
 */
export async function resolveEntityNames(
  hashes: string[],
): Promise<Record<string, string>> {
  const all = await listEntries();
  const combined: Record<string, string> = {};
  for (const entry of all) {
    for (const [hash, name] of Object.entries(entry.entityMap)) {
      combined[hash] = name;
    }
  }
  const result: Record<string, string> = {};
  for (const h of hashes) {
    result[h] = combined[h] ?? h;
  }
  return result;
}

// ── Internal helpers ──────────────────────────────────────────

function generateId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

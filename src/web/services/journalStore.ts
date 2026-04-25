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
const DB_VERSION = 2;
const STORE_NAME = 'entries';
const ADVISORY_STORE = 'advisories';

export interface JournalEntry {
  entryId: string;
  sessionId: string;
  timestamp: number;
  rawText: string;
  entityMap: Record<string, string>;   // hash → displayName
  svaScores: { s: number; v: number; a: number } | null;
  turnNumber?: number;
}

/**
 * Chronic spectral drift advisory delivered by the server in
 * ``decision.advisory`` (see Phase G.5 / journal_session_start /
 * journal_domain_step piggyback).  Stored locally so the banner survives
 * page reloads until the server-side TTL (24h) expires.
 */
export interface SpectralAdvisory {
  advisory_id: string;
  axis: 'valence' | 'arousal' | 'salience' | string;
  band: 'dc_drift' | 'circaseptan' | 'ultradian' | string;
  direction: 'positive' | 'negative' | string;
  message: string;
  expires_utc: string;   // ISO-8601 UTC
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
      if (!db.objectStoreNames.contains(ADVISORY_STORE)) {
        // Single-row keyed by 'current' — only one advisory active at a time.
        db.createObjectStore(ADVISORY_STORE, { keyPath: 'key' });
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

// ── Spectral advisory store (Phase G.5) ───────────────────────

/**
 * Persist the active chronic spectral advisory locally so the UI banner
 * survives reloads.  Replaces any prior advisory.
 */
export async function setAdvisory(adv: SpectralAdvisory): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ADVISORY_STORE, 'readwrite');
    const req = tx.objectStore(ADVISORY_STORE).put({ key: 'current', adv });
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

/**
 * Return the currently-active advisory, or ``null`` if none is stored or
 * the stored entry has passed its server-side TTL (``expires_utc``).
 * Auto-clears expired entries as a side-effect.
 */
export async function getAdvisory(): Promise<SpectralAdvisory | null> {
  const db = await openDB();
  const stored = await new Promise<SpectralAdvisory | null>((resolve, reject) => {
    const tx = db.transaction(ADVISORY_STORE, 'readonly');
    const req = tx.objectStore(ADVISORY_STORE).get('current');
    req.onsuccess = () => {
      const row = req.result as { key: string; adv: SpectralAdvisory } | undefined;
      resolve(row?.adv ?? null);
    };
    req.onerror = () => reject(req.error);
  });
  if (!stored) return null;
  const exp = Date.parse(stored.expires_utc);
  if (Number.isFinite(exp) && exp <= Date.now()) {
    await clearAdvisory();
    return null;
  }
  return stored;
}

/**
 * Remove the stored advisory (called on dismiss or after TTL expiry).
 */
export async function clearAdvisory(): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ADVISORY_STORE, 'readwrite');
    const req = tx.objectStore(ADVISORY_STORE).delete('current');
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

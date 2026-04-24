/**
 * Entity salt manager — device-local, privacy-preserving.
 *
 * A 32-byte random hex salt is generated once per device and stored in
 * localStorage.  It is sent with each journal-mode turn so the server can
 * hash named entities without ever learning entity names.
 *
 * The salt NEVER leaves the browser except as the opaque hex string used
 * for server-side hashing.  If the user clears localStorage (or calls
 * resetSalt()) all historical entity hashes become unrecoverable — that
 * is intentional and is the privacy guarantee.
 *
 * The hash→displayName mapping (e.g. Entity_A4F9 → "Mr. Davis") is kept
 * solely in the local journalStore IndexedDB.
 */

const SALT_KEY = 'lumina.journal.entity_salt';

/**
 * Return the device-local journal entity salt, generating one if absent.
 * The salt is a 64-character lowercase hex string (32 bytes).
 */
export function getSalt(): string {
  const existing = localStorage.getItem(SALT_KEY);
  if (existing && /^[0-9a-f]{64}$/.test(existing)) {
    return existing;
  }
  const salt = generateSalt();
  localStorage.setItem(SALT_KEY, salt);
  return salt;
}

/**
 * Clear the stored salt.  All previously generated entity hashes become
 * orphaned — they can no longer be linked back to entity names on this
 * device.  A new salt will be generated on the next call to getSalt().
 */
export function resetSalt(): void {
  localStorage.removeItem(SALT_KEY);
}

/**
 * Return true if a salt has already been generated for this device.
 */
export function hasSalt(): boolean {
  const v = localStorage.getItem(SALT_KEY);
  return v !== null && /^[0-9a-f]{64}$/.test(v);
}

// ── Internal helpers ──────────────────────────────────────────

function generateSalt(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

import { useEffect, useState } from 'react';
import { HYPER_MOTION_KEY, readHyperMotion } from './hyperState.js';

const EVENT = 'thermalagent:hyper-motion';
// Shared by all hook instances, including a waiting panel mounted after opt-out.
let sessionPreference = { enabled: true, persistent: false };
let sessionOnly = false;
function remember(preference, onlySession = false) {
  sessionPreference = { enabled: preference.enabled, persistent: preference.persistent };
  sessionOnly = onlySession;
  return sessionPreference;
}
function read(refreshStorage = false) {
  // A failed write may leave a readable but stale value in storage.
  if (sessionOnly && !refreshStorage) return sessionPreference;
  const stored = readHyperMotion();
  if (stored.persistent) return remember(stored);
  return remember({ enabled: sessionPreference.enabled, persistent: false }, sessionOnly);
}
export function useHyperMotion() {
  const [preference, setPreference] = useState(read);
  useEffect(() => {
    if (typeof document !== 'undefined') document.documentElement.dataset.hyperMotion = preference.enabled ? 'full' : 'reduced';
  }, [preference.enabled]);
  useEffect(() => {
    const sync = event => {
      if (event.type === EVENT && typeof event.detail?.enabled === 'boolean') setPreference(remember(event.detail, event.detail.persistent === false));
      else if (event.key === HYPER_MOTION_KEY || event.key === null) setPreference(read(true));
    };
    globalThis.addEventListener?.('storage', sync);
    globalThis.addEventListener?.(EVENT, sync);
    return () => { globalThis.removeEventListener?.('storage', sync); globalThis.removeEventListener?.(EVENT, sync); };
  }, []);
  const toggle = () => {
    const next = { enabled: !preference.enabled, persistent: true };
    try { globalThis.localStorage.setItem(HYPER_MOTION_KEY, next.enabled ? 'on' : 'off'); }
    catch { next.persistent = false; }
    remember(next, !next.persistent);
    setPreference(next);
    if (typeof globalThis.CustomEvent === 'function') globalThis.dispatchEvent?.(new CustomEvent(EVENT, { detail: next }));
  };
  return { ...preference, toggle };
}

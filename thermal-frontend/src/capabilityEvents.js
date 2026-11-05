export const CAPABILITIES_CHANGED_EVENT = 'thermalagent:capabilities-changed';

export function notifyCapabilitiesChanged(target = globalThis) {
  if (typeof target?.dispatchEvent !== 'function' || typeof globalThis.Event !== 'function') return false;
  target.dispatchEvent(new globalThis.Event(CAPABILITIES_CHANGED_EVENT));
  return true;
}

export function subscribeCapabilitiesChanged(listener, target = globalThis) {
  if (typeof target?.addEventListener !== 'function') return () => {};
  target.addEventListener(CAPABILITIES_CHANGED_EVENT, listener);
  return () => target.removeEventListener(CAPABILITIES_CHANGED_EVENT, listener);
}

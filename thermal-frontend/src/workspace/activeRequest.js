// A pending message is live only while its own request is running. Restored
// history and another conversation must never inherit the global busy state.
export function activePendingMessage(messages, messageId, loading) {
  if (!loading || !messageId) return null;
  return messages.find(message => message.id === messageId && message.pending === true) || null;
}

import { guardMessageIdentity } from './resultIdentity.js';

// Keep the existing storage key so earlier conversations remain available.
export const CONVERSATION_STORAGE_KEY = 'flowai_conversations';

export function normalizeConversations(value) {
  if (!Array.isArray(value)) return [];
  return value.filter(conversation => conversation && typeof conversation.id === 'string' && conversation.id)
    .map(conversation => ({
      ...conversation,
      title: typeof conversation.title === 'string' ? conversation.title : '历史对话',
      mode: ['report', 'task'].includes(conversation.mode) ? conversation.mode : 'chat',
      simulationMode: conversation.simulationMode === true,
      messages: Array.isArray(conversation.messages)
        ? conversation.messages.filter(message => message && ['user', 'bot'].includes(message.role)).map(message => guardMessageIdentity(message, conversation.id))
        : [],
    }));
}

export function loadConversations(storage) {
  try {
    return normalizeConversations(JSON.parse((storage || globalThis.localStorage).getItem(CONVERSATION_STORAGE_KEY)));
  } catch {
    return [];
  }
}

export function saveConversations(conversations, storage) {
  try {
    (storage || globalThis.localStorage).setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(conversations));
    return true;
  } catch {
    return false;
  }
}

export function isActiveConversationReply(activeConversationId, requestConversationId) {
  return Boolean(activeConversationId && activeConversationId === requestConversationId);
}

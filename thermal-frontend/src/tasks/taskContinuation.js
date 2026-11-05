import { guardMessageIdentity } from '../resultIdentity.js';

// Context comes only from the current conversation transcript. Opening the global
// task archive never changes which task a conversational revision refers to.
export function engineeringConversationContext(messages = []) {
  for (const message of [...messages].reverse()) {
    if (message?.role !== 'bot' || message.pending) continue;
    if (guardMessageIdentity(message).identityError) continue;
    const metadata = message.raw?.metadata;
    const id = message.taskSnapshot?.task_id || message.taskId;
    if (id) return { currentTaskId: id, currentContextKind: 'engineering' };
    // The stable API includes an idle simulation_execution object even for RAG
    // and reference-solver answers. Only an actual plan/execution owns context.
    if (metadata?.simulation_plan?.generated || metadata?.simulation_execution?.executed || metadata?.simulation_execution?.plan_id) {
      return { currentTaskId: null, currentContextKind: 'simulation' };
    }
  }
  return { currentTaskId: null, currentContextKind: 'other' };
}

export function validateContinuationRoute(response) {
  if (!response || !['task', 'clarification', 'rag', 'unhandled'].includes(response.route)) {
    throw new Error('工程上下文检查没有返回有效路由；请核对任务记录后再继续。');
  }
  if (response.route === 'task' && !response.task_id) {
    throw new Error('关联任务缺少受理编号；请先核对任务记录，避免重复提交。');
  }
  if (response.route === 'clarification' && !response.message) {
    throw new Error('工程上下文需要确认，但服务未返回确认内容。');
  }
  return response;
}

export const RESULT_IDENTITY_ERROR = 'RESULT_IDENTITY_MISMATCH';
export const RESULT_IDENTITY_MESSAGE = '结果与当前请求、会话或工程记录的身份不一致，已阻止展示。请从任务历史重新读取并核对。';

export function identityError(field) {
  return Object.assign(new Error(`${field === 'task_id' ? '任务编号不一致。' : ''}${RESULT_IDENTITY_MESSAGE}`), { code: RESULT_IDENTITY_ERROR, field });
}

function same(field, values) {
  const supplied = values.filter(value => value !== undefined && value !== null && value !== '');
  if (supplied.some(value => typeof value !== 'string') || new Set(supplied).size > 1) throw identityError(field);
}

/** Missing optional fields are legacy-compatible; explicitly conflicting identities are not. */
export function assertResultIdentity({ task, response, taskId, sessionId, requestId, query, requestFingerprint, inputFingerprint, calculationFingerprint, runId } = {}) {
  const payload = response || task?.result;
  const meta = payload?.metadata || {};
  const link = meta.engineering_task || {};
  const run = meta.engineering_run || {};
  const storedRun = task?.result?.metadata?.engineering_run || {};
  same('task_id', [taskId, task?.task_id, link.task_id, run.task_id, storedRun.task_id]);
  same('session_id', [sessionId, task?.session_id, task?.request?.session_id, payload?.session_id, link.session_id, run.session_id]);
  same('request_id', [requestId, payload?.request_id, link.request_id, run.request_id]);
  if (query !== undefined || task?.task_id || link.task_id) same('query', [query, task?.query, payload?.query, link.query].map(value => typeof value === 'string' ? value.trim() : value));
  same('request_fingerprint', [requestFingerprint, task?.request_fingerprint, link.request_fingerprint, run.request_fingerprint]);
  same('input_fingerprint', [inputFingerprint, task?.input_fingerprint, link.input_fingerprint]);
  same('calculation_fingerprint', [calculationFingerprint, task?.calculation_fingerprint, link.calculation_fingerprint, run.calculation_fingerprint]);
  same('run_id', [runId, task?.run_id, link.run_id, run.run_id, run.persistence?.run_id, storedRun.run_id]);
  same('run_input_fingerprint', [run.input_fingerprint, storedRun.input_fingerprint]);
  if (task?.scope === 'bounded_reference_conduction' || link.scope === 'bounded_reference_conduction') {
    same('reference_input_fingerprint', [task?.input_fingerprint, link.input_fingerprint, run.input_fingerprint]);
  }
  const declaredRuns = [...(Array.isArray(task?.run_ids) ? task.run_ids : []), ...(Array.isArray(task?.steps) ? task.steps : []).map(step => step?.run_id).filter(Boolean)];
  if (run.run_id && declaredRuns.length && !declaredRuns.includes(run.run_id)) throw identityError('declared_run_id');
  if (task?.result && response && response !== task.result) assertResultIdentity({ task, response: task.result, taskId, sessionId, requestId, query, requestFingerprint, inputFingerprint, calculationFingerprint, runId });
  return payload;
}

export function captureResultIdentity({ task, response, sessionId, requestId } = {}) {
  assertResultIdentity({ task, response, sessionId, requestId });
  const meta = (response || task?.result)?.metadata || {};
  return Object.fromEntries(Object.entries({
    sessionId, requestId, taskId: task?.task_id || meta.engineering_task?.task_id, query: task?.query,
    requestFingerprint: task?.request_fingerprint || meta.engineering_task?.request_fingerprint,
    inputFingerprint: task?.input_fingerprint || meta.engineering_task?.input_fingerprint,
    calculationFingerprint: task?.calculation_fingerprint || meta.engineering_task?.calculation_fingerprint,
    runId: task?.run_id || meta.engineering_task?.run_id || meta.engineering_run?.run_id,
  }).filter(([, value]) => value !== undefined && value !== null));
}

export function guardMessageIdentity(message, conversationId) {
  if (message?.role !== 'bot' || message.identityError) return message;
  try {
    const binding = message.resultIdentity || {};
    same('conversation_id', [conversationId, message.conversationId, binding.sessionId]);
    same('message_request_id', [message.requestId, binding.requestId]);
    same('message_task_id', [message.taskId, binding.taskId]);
    assertResultIdentity({ ...binding, task: message.taskSnapshot, response: message.raw,
      taskId: message.taskId || binding.taskId, sessionId: message.conversationId || binding.sessionId || conversationId, requestId: message.requestId || binding.requestId,
      query: message.taskId || message.taskSnapshot ? message.query || binding.query : undefined });
    return message;
  } catch (error) {
    if (error.code !== RESULT_IDENTITY_ERROR) throw error;
    return { ...message, pending: false, content: RESULT_IDENTITY_MESSAGE, sources: [], taskSnapshot: null,
      raw: { error: RESULT_IDENTITY_MESSAGE }, identityError: RESULT_IDENTITY_ERROR, isError: true };
  }
}

/** A reply may replace only its still-pending slot; late or duplicate deliveries are inert. */
export function replaceOwnedReply(messages, reply, owner) {
  if (!Array.isArray(messages) || reply.requestId !== owner.requestId || reply.conversationId !== owner.conversationId) return messages;
  const index = messages.findIndex(message => message.id === owner.pendingMessageId && message.requestId === owner.requestId
    && message.conversationId === owner.conversationId && message.pending === true);
  if (index < 0) return messages;
  return messages.map((message, i) => i === index ? guardMessageIdentity(reply, owner.conversationId) : message);
}

export function assertRunIdentity(run, expectedRunId) {
  same('history_run_id', [expectedRunId, run?.run_id, run?.receipt?.run_id]);
  if (!run?.run_id) throw identityError('history_run_id');
  same('history_input_fingerprint', [run.input_fingerprint, run.receipt?.input_fingerprint]);
  assertResultIdentity({ response: { metadata: { engineering_run: run.receipt } }, runId: run.run_id });
  return run;
}

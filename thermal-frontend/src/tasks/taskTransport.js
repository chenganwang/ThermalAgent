import { answerAgent, getEngineeringTask, submitEngineeringTask } from '../api/client.js';
import { acceptTaskSnapshot, isTerminalTask } from './taskState.js';
import { assertResultIdentity, identityError } from '../resultIdentity.js';

export function isLegacyTaskEndpoint(error) {
  return error?.statusCode === 405 || (error?.statusCode === 404 && (error.detail === 'Not Found' || error.payload?.detail === 'Not Found'));
}

function pause(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException('Stopped waiting for the task', 'AbortError')); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, milliseconds);
    if (signal?.aborted) abort(); else signal?.addEventListener('abort', abort, { once: true });
  });
}

// No retry of POST: a lost response can conceal an already accepted operation.
export async function executeVisibleTask(request, { onSnapshot = () => {}, signal, services = {}, acceptedTask = null } = {}) {
  const submit = services.submit || submitEngineeringTask;
  const read = services.read || getEngineeringTask;
  const legacy = services.legacy || answerAgent;
  const wait = services.wait || pause;
  let accepted = acceptedTask;
  try { if (!accepted) accepted = await submit(request, { signal }); }
  catch (error) {
    if (isLegacyTaskEndpoint(error)) {
      const result = await legacy(request, { signal });
      assertResultIdentity({ response: result, sessionId: request.sessionId, requestId: request.requestId, query: request.query });
      return { result, snapshot: null, legacy: true };
    }
    throw error;
  }
  let snapshot = null;
  const taskId = accepted?.task_id;
  if (typeof taskId !== 'string' || !taskId) throw new Error('任务提交回执缺少任务编号；请先检查历史，避免重复提交。');
  const expected = { taskId, sessionId: request.sessionId, requestId: request.requestId, query: request.query,
    requestFingerprint: accepted.request_fingerprint, inputFingerprint: accepted.input_fingerprint,
    calculationFingerprint: accepted.calculation_fingerprint, runId: accepted.run_id };
  try {
    assertResultIdentity({ ...expected, task: accepted });
    if (Array.isArray(accepted.steps)) { snapshot = acceptTaskSnapshot(null, accepted, expected); onSnapshot(snapshot); }
    while (!isTerminalTask(snapshot)) {
      const received = await read(taskId, { signal });
      if (received?.task_id !== taskId) throw identityError('task_id');
      snapshot = acceptTaskSnapshot(snapshot, received, expected);
      onSnapshot(snapshot);
      if (!isTerminalTask(snapshot)) await wait(1000, signal);
    }
    return { result: snapshot.result, snapshot, legacy: false };
  } catch (error) {
    error.taskId = taskId;
    error.taskSnapshot = snapshot;
    throw error;
  }
}

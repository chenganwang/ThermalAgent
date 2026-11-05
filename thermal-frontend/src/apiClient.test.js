import assert from 'node:assert/strict';
import test from 'node:test';

import {
  answerAgent,
  exportAgentReport,
  getCapabilities,
  AGENT_REQUEST_TIMEOUT_MS,
  DEFAULT_REQUEST_TIMEOUT_MS,
  requestFailureMessage,
  getSimulationModelAssets,
  submitSimulationModelAssetReview,
  uploadSimulationModelAsset,
} from './api/client.js';
import { replaceOwnedReply } from './resultIdentity.js';

function controlledNetwork({ bodyPending = false } = {}) {
  const original = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const requests = [];
  const timers = new Map();
  let timerId = 0;
  globalThis.setTimeout = (callback, milliseconds) => { const id = ++timerId; timers.set(id, { callback, milliseconds }); return id; };
  globalThis.clearTimeout = id => timers.delete(id);
  const pending = signal => new Promise((resolve, reject) => {
    if (signal.aborted) reject(signal.reason);
    else signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  });
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    if (bodyPending) return { ok: true, text: () => pending(options.signal) };
    return pending(options.signal);
  };
  return { requests, timers, restore: () => Object.assign(globalThis, original) };
}

test('对话请求显式携带 simulation capability 与确认动作', async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ answer: 'ok' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  try {
    await answerAgent({
      query: '确认执行',
      sessionId: 'conversation-1',
      simulationMode: true,
      simulationAction: 'confirm',
      simulationPlanId: 'sim-1',
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(request.url, '/api/agent/answer');
  const payload = JSON.parse(request.options.body);
  assert.equal(payload.simulation_mode, true);
  assert.equal(payload.simulation_action, 'confirm');
  assert.equal(payload.simulation_plan_id, 'sim-1');
});

test('multipart 上传交给 FormData 生成 boundary，不强设 application/json', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ asset_id: 'asset-1' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  try {
    const file = new Blob(['model-data'], { type: 'application/octet-stream' });
    await uploadSimulationModelAsset(file);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(requests[0].url, '/api/simulation/model-assets/upload');
  assert.equal(requests[0].options.method, 'POST');
  assert.ok(requests[0].options.body instanceof FormData);
  assert.equal(requests[0].options.headers['Content-Type'], undefined);
  assert.equal(requests[0].options.body.has('file'), true);
});

test('列表与提交复核只调用公开路由', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, options });
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  try {
    await getSimulationModelAssets();
    await submitSimulationModelAssetReview('asset id');
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(requests.map(item => item.url), [
    '/api/simulation/model-assets',
    '/api/simulation/model-assets/asset%20id/submit-review',
  ]);
  assert.equal(requests[1].options.method, 'POST');
  assert.equal(requests[1].options.body, undefined);
  assert.equal(requests.some(item => item.url.includes('/admin/')), false);
});

test('Agent and report requests time out once without resubmitting or leaking transport options into fetch', async () => {
  for (const send of [answerAgent, exportAgentReport]) {
    const network = controlledNetwork();
    try {
      const result = send({ query: '本地等待测试', sessionId: 'timeout-session' });
      const rejection = assert.rejects(result, error => error.name === 'TimeoutError' && /不会自动重新提交/.test(requestFailureMessage(error)));
      const [timer] = network.timers.values();
      assert.equal(timer.milliseconds, AGENT_REQUEST_TIMEOUT_MS);
      timer.callback();
      await rejection;
      assert.equal(network.requests.length, 1);
      assert.equal(network.requests[0].options.method, 'POST');
      assert.equal(network.requests[0].options.timeoutMs, undefined);
      assert.equal(network.timers.size, 0);
    } finally { network.restore(); }
  }
});

test('request deadline remains active while reading a stalled response body', async () => {
  const network = controlledNetwork({ bodyPending: true });
  try {
    const result = answerAgent({ query: 'body' });
    const rejection = assert.rejects(result, { name: 'TimeoutError' });
    await Promise.resolve();
    network.timers.values().next().value.callback();
    await rejection;
    assert.equal(network.requests.length, 1);
    assert.equal(network.timers.size, 0);
  } finally { network.restore(); }
});

test('caller abort stops Agent and report waits and pre-aborted requests never reach fetch', async () => {
  for (const send of [answerAgent, exportAgentReport]) {
    const network = controlledNetwork();
    const controller = new AbortController();
    try {
      const result = send({ query: 'stop' }, { signal: controller.signal });
      const rejection = assert.rejects(result, error => error.name === 'AbortError' && /后台操作可能仍在运行/.test(requestFailureMessage(error)));
      controller.abort();
      await rejection;
      assert.equal(network.requests[0].options.signal.aborted, true);
      assert.equal(network.timers.size, 0);
      await assert.rejects(send({ query: 'already stopped' }, { signal: controller.signal }), { name: 'AbortError' });
      assert.equal(network.requests.length, 1);
    } finally { network.restore(); }
  }
});

test('status deadlines are finite and configured deadlines are bounded', async () => {
  for (const [options, expected] of [[{}, DEFAULT_REQUEST_TIMEOUT_MS], [{ timeoutMs: 25 }, 25], [{ timeoutMs: Infinity }, DEFAULT_REQUEST_TIMEOUT_MS], [{ timeoutMs: 900_000 }, 300_000]]) {
    const network = controlledNetwork();
    try {
      const result = getCapabilities(options);
      const rejection = assert.rejects(result, { name: 'TimeoutError' });
      const [timer] = network.timers.values();
      assert.equal(timer.milliseconds, expected);
      timer.callback();
      await rejection;
    } finally { network.restore(); }
  }
});

test('aborted message stays in its owner slot and a fresh request succeeds without reusing its signal', async () => {
  const network = controlledNetwork();
  const owner = { conversationId: 'conv-a', requestId: 'req-a', pendingMessageId: 'pending-a' };
  const pending = { id: owner.pendingMessageId, ...owner, role: 'bot', pending: true };
  const other = { id: 'other-pending', conversationId: 'conv-b', requestId: 'req-b', role: 'bot', pending: true };
  try {
    const controller = new AbortController();
    const result = answerAgent({ query: 'old' }, { signal: controller.signal }).catch(error => error);
    controller.abort();
    const error = await result;
    const stopped = { id: 'stopped', ...owner, role: 'bot', content: requestFailureMessage(error), isError: true };
    const updated = replaceOwnedReply([pending, other], stopped, owner);
    assert.equal(updated[0].content, requestFailureMessage(error));
    assert.equal(updated[1], other);
    assert.equal(replaceOwnedReply(updated, { ...stopped, content: 'late answer' }, owner), updated);
    globalThis.fetch = async (url, options) => {
      assert.equal(options.signal.aborted, false);
      return new Response(JSON.stringify({ answer: 'new answer', session_id: 'conv-b' }));
    };
    assert.equal((await answerAgent({ query: 'new', sessionId: 'conv-b' })).answer, 'new answer');
    assert.equal(network.timers.size, 0);
  } finally { network.restore(); }
});

test('auth failures preserve status and detail with one request and cleaned-up deadlines', async () => {
  const network = controlledNetwork();
  let calls = 0;
  try {
    globalThis.fetch = async () => { calls++; return new Response(JSON.stringify({ detail: 'Invalid or missing bearer token.' }), { status: 401 }); };
    await assert.rejects(answerAgent({ query: 'protected' }), error => error.statusCode === 401 && error.detail === 'Invalid or missing bearer token.');
    assert.equal(calls, 1);
    assert.equal(network.timers.size, 0);
  } finally { network.restore(); }
});

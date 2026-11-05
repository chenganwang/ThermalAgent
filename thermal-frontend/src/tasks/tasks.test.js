import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { readFileSync } from 'node:fs';
import { acceptTaskSnapshot, canRetryTask, isTerminalTask, LIQUID_COOLING_EXAMPLE, orderedTaskEvents, taskConnectionError, taskDependencyLayout } from './taskState.js';
import { executeVisibleTask, isLegacyTaskEndpoint } from './taskTransport.js';
import { continueEngineeringTask, cancelEngineeringTask, getEngineeringTask, getEngineeringTasks, retryEngineeringTask, submitEngineeringTask } from '../api/client.js';
import { normalizeConversations } from '../conversationStorage.js';
import { engineeringConversationContext, validateContinuationRoute } from './taskContinuation.js';

const fixture = JSON.parse(readFileSync(new URL('./taskResponse.fixture.json', import.meta.url), 'utf8'));
const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: TaskProgressCard } = await vite.ssrLoadModule('/src/tasks/TaskProgressCard.jsx');
const { ThemeContext } = await vite.ssrLoadModule('/src/theme/useAppTheme.js');
const { default: WelcomePanel } = await vite.ssrLoadModule('/src/workspace/WelcomePanel.jsx');
const { default: App } = await vite.ssrLoadModule('/src/App.jsx');
after(() => vite.close());

test('task client uses fixed routes and explicit revision confirmation without external solver flags', async () => {
  const original = globalThis.fetch; const calls = [];
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return new Response('{}'); };
  try {
    await submitEngineeringTask({ query: LIQUID_COOLING_EXAMPLE, sessionId: 'test' });
    await getEngineeringTasks({ offset: 20 }); await getEngineeringTask('task/a');
    await retryEngineeringTask('task/a', { revision: 7, query: ' 修订问题 ' });
    await cancelEngineeringTask('task/a', 8);
  } finally { globalThis.fetch = original; }
  assert.equal(calls[0].url, '/api/engineering/tasks');
  assert.deepEqual(JSON.parse(calls[0].options.body), { query: LIQUID_COOLING_EXAMPLE, session_id: 'test', uploaded_model_filename: null, requested_outputs: ['report'], analysis_report_mode: true, simulation_mode: false });
  assert.equal(calls[1].url, '/api/engineering/tasks?limit=20&offset=20');
  assert.equal(calls[2].url, '/api/engineering/tasks/task%2Fa');
  assert.deepEqual(JSON.parse(calls[3].options.body), { expected_revision: 7, confirmed: true, query: '修订问题' });
  assert.deepEqual(JSON.parse(calls[4].options.body), { expected_revision: 8 });
});
test('polling follows real snapshots and stops on the actual terminal state', async () => {
  let reads = 0; let submits = 0; let waits = 0; const seen = [];
  const returned = await executeVisibleTask({ query: fixture.queued.query }, { onSnapshot: snapshot => seen.push(snapshot), services: {
    submit: async () => { submits++; return { task_id: fixture.queued.task_id }; },
    read: async () => { reads++; return reads === 1 ? fixture.queued : fixture.finished; },
    wait: async () => { waits++; },
  } });
  assert.equal(submits, 1); assert.equal(reads, 2); assert.equal(waits, 1);
  assert.equal(seen[0].status, 'queued'); assert.equal(isTerminalTask(seen[1]), true);
  assert.deepEqual(returned.result, fixture.finished.result);
});
test('unknown POST outcomes never trigger fallback, polling or another submission', async () => {
  for (const failure of [new TypeError('offline'), { name: 'AbortError' }, { statusCode: 503 }, { statusCode: 429 }, { statusCode: 404, detail: { code: 'ENGINEERING_PROJECT_NOT_FOUND' } }]) {
    let submissions = 0; let forbidden = 0;
    await assert.rejects(executeVisibleTask({}, { services: { submit: async () => { submissions++; throw failure; }, legacy: async () => { forbidden++; }, read: async () => { forbidden++; } } }));
    assert.equal(submissions, 1); assert.equal(forbidden, 0);
  }
});
test('legacy fallback is only available for an unequivocally absent endpoint or unsupported method', async () => {
  let fallback = 0;
  const result = await executeVisibleTask({ query: 'question' }, { services: { submit: async () => { throw { statusCode: 404, detail: 'Not Found' }; }, legacy: async request => { fallback++; return { answer: request.query }; } } });
  assert.equal(fallback, 1); assert.equal(result.legacy, true); assert.equal(result.result.answer, 'question');
  assert.equal(isLegacyTaskEndpoint({ statusCode: 405 }), true);
  assert.equal(isLegacyTaskEndpoint({ statusCode: 404, detail: { code: 'TASK_NOT_FOUND' } }), false);
});
test('a disconnected accepted task retains its ID and latest actual snapshot for reopening', async () => {
  let count = 0; let submissions = 0;
  await assert.rejects(executeVisibleTask({}, { services: { submit: async () => { submissions++; return { task_id: fixture.queued.task_id }; }, read: async () => { if (++count === 1) return fixture.queued; throw Error('offline'); }, wait: async () => {} } }), error => {
    assert.equal(error.taskId, fixture.queued.task_id); assert.equal(error.taskSnapshot.status, 'queued');
    assert.match(taskConnectionError(error, error.taskId), /不会自动重新提交/); return true;
  });
  assert.equal(submissions, 1);
});
test('snapshots ignore stale revisions and events retain server order with duplicate sequences removed', () => {
  assert.equal(acceptTaskSnapshot(fixture.finished, fixture.queued), fixture.finished);
  assert.deepEqual(orderedTaskEvents([{ sequence: 3 }, { sequence: 1 }, { sequence: 3 }, { sequence: '2' }]).map(event => event.sequence), [1, 3]);
  assert.throws(() => acceptTaskSnapshot(null, { task_id: 'x', status: 'fictional_progress', revision: 2 }));
});
test('responses for a different task cannot appear in the accepted task view', async () => {
  await assert.rejects(executeVisibleTask({}, { services: { submit: async () => ({ task_id: 'expected' }), read: async () => fixture.finished } }), /任务编号不一致/);
});
test('actual liquid task preserves the flow-to-pressure input chain and incomplete evidence state', () => {
  const { finished } = fixture;
  const flow = finished.steps.find(step => step.step_id === 'flow');
  const pressure = finished.steps.find(step => step.step_id === 'pressure');
  assert.equal(flow.outputs.volume_flow_L_min, pressure.inputs.flow_rate_lpm);
  assert.deepEqual(pressure.depends_on, ['flow']);
  const html = renderToStaticMarkup(React.createElement(TaskProgressCard, { task: finished }));
  assert.match(html, /根据流量计算管路压降/); assert.match(html, /真实事件时间线/);
  assert.match(html, /中间变量与单位/); assert.match(html, /已通过已配置物理检查/);
  assert.match(html, /证据不完整/); assert.doesNotMatch(html, /100%|自主认证|正在估算/);
});
test('dependency diagram draws only declared edges including branches and joins', () => {
  const graph = taskDependencyLayout(fixture.finished.steps);
  const edges = graph.edges.map(edge => `${edge.from.step_id}->${edge.to.step_id}`);
  assert.ok(edges.includes('flow->pressure'));
  assert.ok(edges.includes('retrieval->report'));
  assert.ok(edges.includes('pressure->validation'));
  assert.ok(!edges.includes('retrieval->flow'));
  assert.ok(graph.nodes.find(node => node.step_id === 'pressure').x > graph.nodes.find(node => node.step_id === 'flow').x);
  assert.deepEqual(taskDependencyLayout([{ step_id: 'x', depends_on: ['not-declared'] }]).edges, []);
});
test('recoverable failures require declared terminal state and valid revision', () => {
  assert.equal(canRetryTask({ status: 'blocked', recoverable: true, revision: 4 }), true);
  assert.equal(canRetryTask({ status: 'running', recoverable: true, revision: 4 }), false);
  assert.equal(canRetryTask({ status: 'failed', recoverable: false, revision: 4 }), false);
});
test('task mode and server task IDs survive existing conversation storage normalization', () => {
  const list = normalizeConversations([{ id: 'chat', mode: 'task', messages: [{ role: 'bot', taskId: fixture.queued.task_id }] }]);
  assert.equal(list[0].mode, 'task'); assert.equal(list[0].messages[0].taskId, fixture.queued.task_id);
});
test('redesigned shell retains old workflows and exposes a natural-language task entry', () => {
  const welcome = renderToStaticMarkup(React.createElement(WelcomePanel, { onExample: () => {} }));
  assert.match(welcome, /liquid-cooling-example/); assert.match(welcome, /规划液冷回路/);
  const shell = renderToStaticMarkup(React.createElement(App));
  for (const marker of ['chat-message-list', 'chat-composer', 'conversation-history', 'open-engineering-history', 'open-task-history', 'theme-engineering', 'theme-cel']) assert.ok(shell.includes(marker), marker);
  assert.match(shell, /工程任务/); assert.match(shell, /生成报告/); assert.match(shell, /仿真管理/);
});
test('small-screen shell defaults navigation closed while keeping task mode and composer accessible', () => {
  const original = globalThis.matchMedia;
  globalThis.matchMedia = () => ({ matches: true });
  try {
    const html = renderToStaticMarkup(React.createElement(App));
    assert.match(html, /aria-expanded="false" aria-label="展开侧边栏"/);
    assert.match(html, /chat-composer/);
    assert.match(html, /工程任务/);
    assert.doesNotMatch(html, /data-testid="conversation-history"/);
  } finally { if (original) globalThis.matchMedia = original; else delete globalThis.matchMedia; }
});
test('Anime mission view preserves incomplete evidence, real tool names and technical records', () => {
  const html = renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId: 'cel' } }, React.createElement(TaskProgressCard, { task: fixture.finished })));
  assert.match(html, /data-testid="mission-board"/);
  assert.match(html, /EVIDENCE INCOMPLETE/);
  assert.match(html, /liquid_flow_rate_required/);
  assert.match(html, /liquid_pressure_drop_estimate/);
  assert.match(html, /DEPENDENCY MAP/);
  assert.match(html, /中间变量与单位/);
  assert.match(html, /真实事件时间线/);
  assert.match(html, new RegExp(fixture.finished.task_id));
  assert.doesNotMatch(html, /mission-completed-stamp|100%/);
  const professional = renderToStaticMarkup(React.createElement(TaskProgressCard, { task: fixture.finished }));
  assert.doesNotMatch(professional, /mission-board|MISSION/);
  assert.match(professional, /任务依赖图/);
});
test('Anime mission cannot turn queued, blocked or failed records into completed steps', () => {
  for (const status of ['queued', 'blocked', 'failed']) {
    const task = { ...fixture.queued, status };
    const html = renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId: 'cel' } }, React.createElement(TaskProgressCard, { task })));
    assert.match(html, /aria-label="已完成 0\/6 个已声明步骤"/);
    assert.match(html, /STANDBY/);
    assert.doesNotMatch(html, /mission-completed-stamp|ACTIVE CHAPTER|✓/);
  }
});
test('Anime mission highlights the actual running tool and only stamps the completed task state', () => {
  const task = { ...fixture.queued, status: 'running', steps: fixture.queued.steps.map(step => ({ ...step, status: step.step_id === 'flow' ? 'running' : 'pending' })) };
  const renderTask = record => renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId: 'cel' } }, React.createElement(TaskProgressCard, { task: record })));
  const html = renderTask(task);
  assert.match(html, /ACTIVE CHAPTER/);
  assert.match(html, /data-status="running"/);
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /liquid_flow_rate_required/);
  assert.doesNotMatch(html, /mission-completed-stamp/);
  const complete = { ...fixture.finished, status: 'completed' };
  assert.match(renderTask(complete), /mission-completed-stamp/);
});


test('continuation context belongs to the active transcript and survives an unrelated answer', () => {
  const first = [{ role: 'bot', taskId: 'task-one', taskSnapshot: { task_id: 'task-one' } }, { role: 'bot', content: '知识回答' }];
  assert.deepEqual(engineeringConversationContext(first), { currentTaskId: 'task-one', currentContextKind: 'engineering' });
  assert.deepEqual(engineeringConversationContext([{ role: 'bot', taskId: 'task-two' }]), { currentTaskId: 'task-two', currentContextKind: 'engineering' });
  assert.deepEqual(engineeringConversationContext([]), { currentTaskId: null, currentContextKind: 'other' });
  assert.equal(engineeringConversationContext([...first, { role: 'bot', pending: true, taskId: 'pending-other' }]).currentTaskId, 'task-one');
});

test('a newer MATLAB plan prevents binding an older engineering task', () => {
  const messages = [{ role: 'bot', taskId: 'old-wall' }, { role: 'bot', raw: { metadata: { simulation_plan: { generated: true, plan_id: 'matlab-plan' } } } }];
  assert.deepEqual(engineeringConversationContext(messages), { currentTaskId: null, currentContextKind: 'simulation' });
  messages.push({ role: 'bot', taskId: 'new-wall' });
  assert.equal(engineeringConversationContext(messages).currentTaskId, 'new-wall');
});

test('legacy fallback forwards cancellation to the real Agent client', async () => {
  const controller = new AbortController();
  let received;
  await executeVisibleTask({ query: 'question' }, { signal: controller.signal, services: {
    submit: async () => { throw { statusCode: 404, detail: 'Not Found' }; },
    legacy: async (request, options) => { received = options.signal; return { answer: request.query }; },
  } });
  assert.equal(received, controller.signal);
});

test('stable API idle simulation metadata never steals engineering or knowledge context', () => {
  const idle = { simulation_plan: { generated: false, plan_id: null }, simulation_execution: { executed: false, plan_id: null, status: 'not_started' } };
  const task = { role: 'bot', taskId: 'real-wall', raw: { metadata: idle } };
  const knowledge = { role: 'bot', content: '知识回答', raw: { metadata: idle } };
  assert.deepEqual(engineeringConversationContext([task]), { currentTaskId: 'real-wall', currentContextKind: 'engineering' });
  assert.deepEqual(engineeringConversationContext([task, knowledge]), { currentTaskId: 'real-wall', currentContextKind: 'engineering' });
  assert.deepEqual(engineeringConversationContext([knowledge]), { currentTaskId: null, currentContextKind: 'other' });
  const simulation = { role: 'bot', raw: { metadata: { simulation_execution: { executed: false, plan_id: 'failed-plan', status: 'failed' } } } };
  assert.equal(engineeringConversationContext([task, simulation]).currentContextKind, 'simulation');
});

test('continuation client sends only explicit session and task context to the fixed route', async () => {
  const original = globalThis.fetch; let call;
  globalThis.fetch = async (url, options) => { call = { url, options }; return new Response('{"route":"clarification","message":"请选择任务"}'); };
  try {
    const result = await continueEngineeringTask({ query: '保留原任务，把上限改成200W重新评估。', sessionId: 'conversation-a', currentTaskId: 'task-one', currentContextKind: 'engineering' });
    assert.equal(result.route, 'clarification');
  } finally { globalThis.fetch = original; }
  assert.equal(call.url, '/api/engineering/tasks/continue');
  assert.deepEqual(JSON.parse(call.options.body), { query: '保留原任务，把上限改成200W重新评估。', session_id: 'conversation-a', current_task_id: 'task-one', current_context_kind: 'engineering' });
});

test('accepted continuation is polled without creating or resubmitting a task', async () => {
  let submissions = 0; let reads = 0;
  const returned = await executeVisibleTask({ query: fixture.finished.query }, { acceptedTask: { route: 'task', task_id: fixture.queued.task_id }, services: {
    submit: async () => { submissions++; throw Error('duplicate'); },
    read: async () => { reads++; return fixture.finished; },
  } });
  assert.equal(submissions, 0); assert.equal(reads, 1); assert.equal(returned.snapshot.task_id, fixture.queued.task_id);
});

test('lost continuation reads retain the accepted ID and never fall back to RAG', async () => {
  let forbidden = 0;
  await assert.rejects(executeVisibleTask({}, { acceptedTask: { route: 'task', task_id: 'accepted-child' }, services: {
    submit: async () => { forbidden++; }, legacy: async () => { forbidden++; }, read: async () => { throw Error('offline'); },
  } }), error => error.taskId === 'accepted-child');
  assert.equal(forbidden, 0);
});

test('invalid continuation receipts fail closed instead of selecting an unrelated answer route', () => {
  for (const response of [null, {}, { route: 'task' }, { route: 'clarification' }, { route: 'unknown' }]) assert.throws(() => validateContinuationRoute(response));
  for (const response of [{ route: 'task', task_id: 'child' }, { route: 'clarification', message: '请指定层号' }, { route: 'rag' }, { route: 'unhandled' }]) assert.equal(validateContinuationRoute(response), response);
});

test('accepted task identity is frozen across polling and a crossed embedded result is never published', async () => {
  const base = { ...fixture.queued, session_id: 'conv', request_fingerprint: 'requested' };
  for (const patch of [
    { request_fingerprint: 'other-request' },
    { session_id: 'other-session' },
    { result: { metadata: { engineering_task: { task_id: 'other-task' } } } },
  ]) {
    let published = 0;
    await assert.rejects(executeVisibleTask({ sessionId: 'conv' }, { acceptedTask: { task_id: base.task_id, request_fingerprint: 'requested' },
      onSnapshot: () => { published++; }, services: { read: async () => ({ ...base, status: 'completed', ...patch }) },
    }), error => error.code === 'RESULT_IDENTITY_MISMATCH');
    assert.equal(published, 0);
  }
});

test('snapshot and history selection refuse wrong task IDs and mutable fingerprints but retain older valid revisions', () => {
  assert.throws(() => acceptTaskSnapshot(fixture.queued, { ...fixture.finished, task_id: 'other' }), /身份不一致/);
  assert.throws(() => acceptTaskSnapshot(null, fixture.finished, { taskId: 'selected-other' }), /身份不一致/);
  assert.throws(() => acceptTaskSnapshot(fixture.queued, { ...fixture.finished, request_fingerprint: 'changed' }), /身份不一致/);
  assert.equal(acceptTaskSnapshot(fixture.finished, fixture.queued), fixture.finished);
});

test('a quarantined historical task cannot become the next engineering continuation context', () => {
  assert.deepEqual(engineeringConversationContext([{ role: 'bot', taskId: 'stale', taskSnapshot: { task_id: 'different' } }]), { currentTaskId: null, currentContextKind: 'other' });
});

test('a same-session receipt for a prior query is rejected before reading or publishing its old result', async () => {
  let reads = 0;
  await assert.rejects(executeVisibleTask({ query: '当前两层平壁：360K和290K', sessionId: 'same-conversation' }, {
    acceptedTask: { task_id: 'old-task', session_id: 'same-conversation', query: '之前两层平壁：350K和300K' },
    services: { read: async () => { reads++; return fixture.finished; } },
  }), error => error.code === 'RESULT_IDENTITY_MISMATCH' && error.field === 'query');
  assert.equal(reads, 0);
});

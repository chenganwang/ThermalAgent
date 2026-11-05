import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { HYPER_MOTION_KEY, readHyperMotion, resolveHyperState } from './hyperState.js';
import { engineeringResult, resultNumber } from './engineeringResult.js';

test('new pending request never displays a prior task completion or prior running tool', () => {
  for (const status of ['completed', 'running']) {
    const state = resolveHyperState({ task: { task_id: 'old', status, steps: [{ status: 'running', tool_name: 'matlab' }] }, loading: true, pendingMessage: { pending: true, mode: 'task' } });
    assert.equal(state.state, 'planning'); assert.equal(state.taskId, null); assert.equal(state.current, null); assert.equal(state.busy, true);
    assert.match(state.detail, /尚未确认/);
  }
});

test('loading without a new receipt never reuses terminal task state', () => {
  assert.equal(resolveHyperState({ task: { status: 'completed' }, loading: true }).state, 'llm');
  assert.equal(resolveHyperState({ task: { status: 'failed' }, loading: true, mode: 'task' }).state, 'planning');
});

test('only the actual running step selects a tool stage', () => {
  const variants = [['retrieval', 'hybrid_retrieval', 'retrieval'], ['calculation', 'liquid_cooling_flow', 'calculation'], ['validation', 'physics_validation', 'validation'], ['simulation', 'matlab_engine', 'matlab'], ['report', 'engineering_report', 'llm']];
  for (const [id, tool, expected] of variants) {
    const task = { task_id: 'current', status: 'running', steps: [{ step_id: 'old', status: 'completed', tool_name: 'matlab_engine' }, { step_id: id, status: 'running', tool_name: tool, title: '真实阶段' }] };
    const state = resolveHyperState({ task, loading: true, pendingMessage: { pending: true, taskSnapshot: task } });
    assert.equal(state.state, expected); assert.equal(state.current.tool_name, tool); assert.match(state.detail, /真实阶段/); assert.equal(state.taskId, 'current');
  }
});

test('matching pending receipt ID can associate a task while a different ID cannot', () => {
  const task = { task_id: 'current', status: 'running', steps: [{ status: 'running', tool_name: 'reference_solver' }] };
  assert.equal(resolveHyperState({ task, loading: true, pendingMessage: { taskId: 'current' } }).state, 'calculation');
  assert.equal(resolveHyperState({ task, loading: true, pendingMessage: { taskId: 'different' } }).state, 'llm');
});

test('queued tasks never claim tool execution, even when planned tool names exist', () => {
  const state = resolveHyperState({ task: { status: 'queued', steps: [{ status: 'pending', tool_name: 'matlab_engine' }] } });
  assert.equal(state.state, 'planning'); assert.equal(state.busy, true); assert.match(state.detail, /还没有开始/);
});

test('terminal states override stale step activity and preserve blocked/cancelled meaning', () => {
  for (const [status, state] of [['completed', 'complete'], ['failed', 'failed'], ['interrupted', 'failed'], ['blocked', 'warning'], ['incomplete', 'warning'], ['cancelled', 'warning']]) {
    const view = resolveHyperState({ task: { status, steps: [{ status: 'running', tool_name: 'matlab' }] } });
    assert.equal(view.state, state); assert.equal(view.busy, false);
  }
  assert.match(resolveHyperState({ task: { status: 'blocked' } }).detail, /缺少必要参数/);
  assert.match(resolveHyperState({ task: { status: 'cancelled' } }).detail, /已取消/);
});

test('MATLAB wait requires confirmed structured backend, never a query keyword', () => {
  const base = { pending: true, content: '用MATLAB计算', simulationBackend: 'matlab' };
  assert.equal(resolveHyperState({ loading: true, pendingMessage: base }).state, 'llm');
  assert.equal(resolveHyperState({ loading: true, pendingMessage: { ...base, simulationAction: 'confirm' } }).state, 'matlab');
  assert.equal(resolveHyperState({ loading: true, pendingMessage: { ...base, simulationAction: 'confirm', simulationBackend: 'mock' } }).state, 'llm');
});

test('physics failure shows a warning while ordinary prose cannot assert completion', () => {
  assert.equal(resolveHyperState({ latestMessage: { content: 'MATLAB已完成，所有验证通过。' } }).state, 'idle');
  assert.equal(resolveHyperState({ latestMessage: { raw: { metadata: { calculation_result: { physics_validation: { passed: false } } } } } }).state, 'warning');
  assert.equal(resolveHyperState({ latestMessage: { isError: true } }).state, 'failed');
  assert.equal(resolveHyperState({ task: { status: 'unrecognized' } }).state, 'warning');
});

test('motion preference defaults on, preserves opt-out and tolerates storage failure', () => {
  const keys = [];
  assert.deepEqual(readHyperMotion({ getItem: key => { keys.push(key); return null; } }), { enabled: true, persistent: true });
  assert.deepEqual(keys, [HYPER_MOTION_KEY]);
  assert.deepEqual(readHyperMotion({ getItem: () => 'off' }), { enabled: false, persistent: true });
  assert.deepEqual(readHyperMotion({ getItem: () => { throw Error('denied'); } }), { enabled: true, persistent: false });
});

test('explicit response errors override a completed task without borrowing stale errors while loading', () => {
  const props = { task: { status: 'completed' }, latestMessage: { raw: { error: { message: 'connection lost' } } } };
  assert.equal(resolveHyperState(props).state, 'failed');
  assert.equal(resolveHyperState({ ...props, loading: true, pendingMessage: { pending: true } }).state, 'llm');
});

test('completed engineering records celebrate only when failure evidence is absent', () => {
  const view = record => resolveHyperState({ latestMessage: { raw: { metadata: record } } });
  assert.equal(view({ engineering_run: { status: 'completed', validation: { status: 'passed', passed: true } } }).state, 'complete');
  assert.equal(view({ engineering_run: { status: 'completed', validation: { status: 'failed', passed: false } } }).state, 'warning');
  assert.equal(view({ engineering_run: { status: 'completed' }, physics_validation: { passed: false } }).state, 'warning');
  assert.equal(view({ engineering_run: { status: 'incomplete' } }).state, 'warning');
});

test('solver completion requires actual execution and respects execution and critic failures', () => {
  const view = execution => resolveHyperState({ latestMessage: { raw: { metadata: { simulation_execution: execution } } } });
  assert.equal(view({ status: 'completed', executed: false, result: { heat_rate: 384 } }).state, 'idle');
  assert.equal(view({ status: 'completed', executed: true, result: { heat_rate: 384 }, errors: [] }).state, 'complete');
  assert.equal(view({ status: 'failed', executed: false, errors: [] }).state, 'failed');
  assert.equal(view({ status: 'completed', executed: true, result: {}, errors: ['failure'] }).state, 'failed');
  assert.equal(view({ status: 'completed', executed: true, result: {}, evidence: { result_critic: { verdict: 'fail' } } }).state, 'warning');
  assert.match(view({ status: 'completed', executed: true, result: {}, solver_backend: 'mock' }).detail, /Mock/);
});

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { HyperPilot, HyperWaiting, HyperWelcome } = await vite.ssrLoadModule('/src/hyper/index.js');
const { default: AtelierActivity } = await vite.ssrLoadModule('/src/hyper/AtelierActivity.jsx');
const { useHyperMotion } = await vite.ssrLoadModule('/src/hyper/useHyperMotion.js');
const { default: EngineeringResultSummary } = await vite.ssrLoadModule('/src/hyper/EngineeringResultSummary.jsx');
const { default: HyperWorkspaceControls } = await vite.ssrLoadModule('/src/workspace/HyperWorkspaceControls.jsx');
const { default: ConversationMessages } = await vite.ssrLoadModule('/src/workspace/ConversationMessages.jsx');
const { ThemeContext } = await vite.ssrLoadModule('/src/theme/useAppTheme.js');
after(() => vite.close());
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));
function withStorage(storage, action) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get: () => storage });
  try { return action(); } finally { if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor); else delete globalThis.localStorage; }
}

test('inactive waiting does not render fictional activity', () => {
  assert.equal(render(HyperWaiting, { active: false, message: '未开始' }), '');
});

test('active wait renders local Elysia portrait and escapes response text', () => {
  const html = withStorage({ getItem: () => null }, () => render(HyperWaiting, { active: true, message: '<script>fake()</script>' }));
  assert.match(html, /少女祈祷中/); assert.match(html, /atelier-elysia/); assert.match(html, /&lt;script&gt;/); assert.doesNotMatch(html, /<script>|https:|100%|验证通过/);
});

test('motion opt-out retains real waiting text and static character', () => {
  const html = withStorage({ getItem: () => 'off' }, () => render(HyperWaiting, { active: true, message: '正在排队，还未执行。' }));
  assert.match(html, /data-motion="off"/); assert.match(html, /正在排队，还未执行/); assert.match(html, /启用 Hyper 等待动画/); assert.match(html, /atelier-elysia/);
});

test('pilot preserves real task ID and reports storage failure without crashing', () => {
  const html = withStorage({ getItem: () => { throw Error('denied'); } }, () => render(HyperPilot, { task: { task_id: 'task_saved_12345678', status: 'blocked' } }));
  assert.match(html, /ELYSIA/); assert.match(html, /爱莉希雅/); assert.match(html, /#12345678/); assert.match(html, /缺少必要参数/); assert.match(html, /仅对本次访问/); assert.doesNotMatch(html, /少女祈祷中/);
});

test('polling response failure overrides a retained running snapshot and stops the pilot animation', () => {
  const task = { task_id: 'task_poll_12345678', status: 'running', steps: [{ step_id: 'calculation', status: 'running', tool_name: 'reference_solver' }] };
  const props = { task, loading: false, latestMessage: { taskSnapshot: task, raw: { error: { message: 'Polling connection lost' } } } };
  const state = resolveHyperState(props);
  assert.equal(state.state, 'failed'); assert.equal(state.busy, false); assert.equal(state.current, null);
  assert.equal(state.taskId, task.task_id); assert.equal(state.taskStatus, 'running'); assert.match(state.detail, /快照不代表当前执行状态.*任务档案/);
  const html = render(HyperPilot, props);
  assert.match(html, /data-busy="false"/); assert.match(html, /当前响应报告异常/); assert.doesNotMatch(html, /少女祈祷中|当前步骤：|COMPUTE ENGINE/);
});

test('restored pending history is a warning rather than permanent activity, while live polling remains busy', () => {
  const task = { task_id: 'task_saved_12345678', status: 'running', steps: [{ step_id: 'retrieval', status: 'running', tool_name: 'hybrid_retrieval' }] };
  const latestMessage = { pending: true, taskSnapshot: task };
  const props = { task, loading: false, latestMessage };
  const state = resolveHyperState(props);
  assert.equal(state.state, 'warning'); assert.equal(state.busy, false); assert.equal(state.current, null); assert.equal(state.taskId, task.task_id);
  assert.match(state.detail, /历史等待记录.*任务档案/);
  const html = render(HyperPilot, props);
  assert.match(html, /data-busy="false"/); assert.match(html, /当前没有活动请求/); assert.doesNotMatch(html, /少女祈祷中|KNOWLEDGE LINK/);
  assert.equal(resolveHyperState({ loading: false, latestMessage: { pending: true } }).busy, false);
  assert.equal(resolveHyperState({ ...props, loading: true, pendingMessage: latestMessage }).state, 'retrieval');
  assert.equal(resolveHyperState({ task }).busy, true);
});

test('welcome presents usable task examples and states that selecting does not submit', () => {
  const html = render(HyperWelcome, { onExample() { throw Error('render must not submit'); } });
  assert.equal((html.match(/<button/g) || []).length, 3); assert.match(html, /确认参数后再发送/); assert.match(html, /规划液冷回路/); assert.match(html, /来一次可信计算/);
});

test('atelier landing renders the supplied working composer exactly once beside the character', () => {
  const composer = React.createElement('textarea', { 'aria-label': '工程问题', defaultValue: '已有草稿' });
  const html = render(HyperWelcome, { composer, onExample() { throw Error('render must not submit'); } });
  assert.equal((html.match(/<textarea/g) || []).length, 1);
  assert.match(html, /已有草稿/); assert.match(html, /atelier-home-composer/); assert.match(html, /atelier-elysia/);
});

test('activity ribbon gives a real task a dossier entry and retains its received tool', () => {
  const html = render(AtelierActivity, { task: { task_id: 'task_kept', status: 'running', steps: [{ step_id: 'calculation', title: '计算导热', status: 'running', tool_name: 'reference_solver' }] } });
  assert.match(html, /展开任务卷宗/); assert.match(html, /reference_solver/); assert.match(html, /计算导热/);
  assert.doesNotMatch(html, /MISSION COMPLETE|查阅工程记录/);
});

test('activity ribbon offers records only for actual completed execution, never ordinary prose', () => {
  const idle = render(AtelierActivity, { latestMessage: { content: '答案完成' } });
  assert.doesNotMatch(idle, /<button|MISSION COMPLETE/);
  const completed = render(AtelierActivity, { latestMessage: { raw: { metadata: { engineering_run: { status: 'completed' } } } } });
  assert.match(completed, /查阅工程记录/);
  const failed = render(AtelierActivity, { latestMessage: { raw: { metadata: { engineering_run: { status: 'completed', validation: { passed: false } } } } } });
  assert.doesNotMatch(failed, /查阅工程记录|MISSION COMPLETE/); assert.match(failed, /data-state="warning"/);
});

test('new pending activity cannot open the completed mission from the preceding request', () => {
  const html = render(AtelierActivity, { task: { task_id: 'old', status: 'completed' }, loading: true, pendingMessage: { pending: true, mode: 'task' } });
  assert.doesNotMatch(html, /展开任务卷宗|MISSION COMPLETE/); assert.match(html, /任务准备/);
});

function mountMotionControl() {
  let control;
  function MotionControl() { control = useHyperMotion(); return null; }
  render(MotionControl, {});
  return control;
}

test('storage denial preserves opted-out motion when a waiting panel and another controller mount later', () => {
  withStorage({ getItem: () => { throw Error('denied'); }, setItem: () => { throw Error('denied'); } }, () => {
    const first = mountMotionControl();
    if (!first.enabled) first.toggle();
    mountMotionControl().toggle();
    const second = mountMotionControl();
    assert.equal(second.enabled, false); assert.equal(second.persistent, false);
    const waiting = render(HyperWaiting, { active: true, message: '新请求正在等待服务响应。' });
    assert.match(waiting, /data-motion="off"/); assert.match(waiting, /新请求正在等待服务响应/); assert.match(waiting, /启用 Hyper 等待动画/);
    second.toggle();
    assert.equal(mountMotionControl().enabled, true);
  });
});

test('failed writes do not let a readable stale stored value re-enable animation on mount', () => {
  const writes = [];
  withStorage({ getItem: () => 'on', setItem: (key, value) => { writes.push([key, value]); throw Error('quota denied'); } }, () => {
    const first = mountMotionControl();
    assert.equal(first.enabled, true);
    first.toggle();
    assert.deepEqual(writes, [[HYPER_MOTION_KEY, 'off']]);
    assert.equal(mountMotionControl().enabled, false);
    assert.match(render(HyperWaiting, { active: true }), /data-motion="off"/);
  });
});

test('a successful write restores persistent preference and later mounts read external storage changes', () => {
  let stored = 'on';
  withStorage({ getItem: () => stored, setItem: (key, value) => { assert.equal(key, HYPER_MOTION_KEY); stored = value; } }, () => {
    const first = mountMotionControl();
    if (first.enabled) first.toggle();
    // The session choice survives until an explicit successful toggle persists it.
    assert.equal(mountMotionControl().enabled, false);
    mountMotionControl().toggle();
    assert.equal(stored, 'on'); assert.equal(mountMotionControl().persistent, true);
    stored = 'off';
    assert.equal(mountMotionControl().enabled, false);
    assert.match(render(HyperWaiting, { active: true }), /data-motion="off"/);
  });
});

function resultTask(maximum = 100) {
  const passed = maximum >= 166.1129568106312;
  return {
    task_id: `test-result-${maximum}`, parent_task_id: maximum === 200 ? 'test-result-100' : null,
    status: passed ? 'completed' : 'incomplete',
    variables: [{ role: 'output', name: 'heat_rate', value: 166.1129568106312, unit: 'W' }],
    validation: { status: 'passed', passed: true },
    design_review: { status: passed ? 'passed' : 'violated', passed, checks: [{ criterion: 'max_heat_rate_abs_w', label: '传热量绝对值', maximum, actual: 166.1129568106312, unit: 'W', status: passed ? 'passed' : 'violated' }] },
    steps: [{ step_id: 'retrieval', status: 'completed' }, { step_id: 'calculation', status: 'completed' }, { step_id: 'design_review', status: passed ? 'completed' : 'incomplete' }],
    report: { generated: true },
    result: { sources: [{ doc_id: 'test-source', chunk_id: 'test-chunk' }], metadata: { engineering_run: { schema_version: '1.1', scope: 'reference_calculation', persistence: { saved: true, enabled: true } } } },
  };
}

test('engineering summary keeps physics PASS, design FAIL and evidence completeness independent', () => {
  const task = resultTask();
  const view = engineeringResult({ task });
  assert.equal(view.primary.value, 166.1129568106312);
  assert.equal(view.physics, 'pass'); assert.equal(view.design, 'fail'); assert.equal(view.evidence, 'complete');
  const html = render(EngineeringResultSummary, { task });
  for (const text of ['166.11', '✓ PASS', '✕ FAIL', '≤ 100 W', '✓ 完整', '方案尚未达标']) assert.ok(html.includes(text), text);
});

test('associated 200 W review displays its own check and preserved parent without mutating either input', () => {
  const parent = resultTask(); const child = resultTask(200);
  const before = JSON.stringify([parent, child]);
  const view = engineeringResult({ task: child });
  assert.equal(view.physics, 'pass'); assert.equal(view.design, 'pass'); assert.equal(view.parentTaskId, parent.task_id);
  const html = render(EngineeringResultSummary, { task: child, onOpenTask() {} });
  assert.match(html, /≤ 200 W/); assert.match(html, /原任务已保留/); assert.match(html, /test-result-100/);
  assert.doesNotMatch(html, /✕ FAIL/); assert.equal(JSON.stringify([parent, child]), before);
});

test('summary never reads claims from prose, treats absent checks honestly and preserves small physical values', () => {
  assert.equal(engineeringResult({ response: { answer: 'Heat Flow 166.11 W PHYSICS PASS DESIGN PASS' } }), null);
  assert.equal(engineeringResult({ task: { variables: [{ role: 'input', name: 'heat_rate', value: 166 }] } }), null);
  assert.equal(engineeringResult({ task: { variables: [{ role: 'output', name: 'heat_rate', value: '166' }] } }), null);
  const task = { ...resultTask(), validation: { status: 'incomplete', passed: false }, design_review: { status: 'passed', passed: true, checks: [] } };
  const view = engineeringResult({ task });
  assert.equal(view.physics, 'unknown'); assert.equal(view.design, 'unknown'); assert.equal(view.evidence, 'incomplete');
  assert.equal(resultNumber(0.00001234), '0.0000123'); assert.equal(resultNumber(NaN), '未记录');
});

test('missing knowledge sources or a failed persistence receipt prevents a complete evidence claim', () => {
  const task = resultTask(200);
  const noSources = { ...task, result: { ...task.result, sources: [] } };
  assert.equal(engineeringResult({ task: noSources }).evidence, 'incomplete');
  task.result.metadata.engineering_run.persistence.saved = false;
  assert.equal(engineeringResult({ task }).evidence, 'incomplete');
});

test('Hyper transcript places the engineering conclusion before a collapsed report; established themes keep their report', () => {
  const task = resultTask();
  const props = { messages: [{ id: 'result', role: 'bot', content: '完整原始报告正文', taskSnapshot: task, mode: 'task' }], onOpenTask() {} };
  const transcript = themeId => renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId } }, React.createElement(ConversationMessages, props)));
  const hyper = transcript('hyper');
  assert.ok(hyper.indexOf('ENGINEERING RESULT') < hyper.indexOf('完整原始报告正文'));
  assert.match(hyper, /<details class="ta-hyper-answer-report">/);
  assert.match(hyper, /物理校验、工具版本与完整 Trace/);
  for (const theme of ['engineering', 'cel']) {
    const html = transcript(theme);
    assert.match(html, /完整原始报告正文/); assert.doesNotMatch(html, /ENGINEERING RESULT|ta-hyper-answer-report/);
  }
});

test('workspace controls default to a folded mission in conversation and expose both a focus exit and width control', () => {
  const chat = render(HyperWorkspaceControls, { mode: 'chat' });
  const task = render(HyperWorkspaceControls, { mode: 'task' });
  assert.match(chat, /展开任务手记/); assert.match(task, /收起任务手记/);
  assert.match(chat, /专注阅读/); assert.match(chat, /Esc 退出/); assert.match(chat, /aria-label="任务手记宽度"/);
  assert.match(chat, /min="240" max="420"/);
});

test('the current wall receipt shows both 232.56 W and 0.301 K/W, independently of the previous wall result', () => {
  const task = resultTask();
  task.variables = [{ role: 'output', name: 'heat_rate', value: 232.5581395348837, unit: 'W' }, { role: 'output', name: 'equivalent_resistance', value: 0.301, unit: 'K/W' }];
  task.design_review.checks[0].actual = 232.5581395348837;
  const html = render(EngineeringResultSummary, { task });
  assert.match(html, /232.56/); assert.match(html, /Total Thermal Resistance/); assert.match(html, /0.301 K\/W/);
  assert.match(html, /✓ PASS/); assert.match(html, /✕ FAIL/); assert.doesNotMatch(html, /166.11/);
});

test('result summary cannot combine current task validation with an old raw run or task response', () => {
  const task = { ...resultTask(), run_id: 'run-new' };
  const response = { metadata: { engineering_run: { run_id: 'run-old' }, engineering_task: { task_id: 'old-task' } } };
  assert.equal(engineeringResult({ task, response }), null);
  const props = { conversationId: 'conv', messages: [{ role: 'bot', conversationId: 'conv', taskId: task.task_id, content: '旧结果166.11W', taskSnapshot: task, raw: response }] };
  const html = renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId: 'hyper' } }, React.createElement(ConversationMessages, props)));
  assert.match(html, /已阻止展示/); assert.doesNotMatch(html, /166.11|ENGINEERING RESULT|✓ PASS/);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import {
  actionResultView,
  buildActionRequest,
  canDryRunAction,
  canInvokeAction,
  defaultActionParameters,
  hasActionPermission,
  normalizeActionDescriptor,
  riskMeta,
} from './actionFlow.js';
import {
  dryRunAdminAction,
  getAdminAction,
  getAdminActions,
  invokeAdminAction,
} from './api/adminClient.js';

const EMPTY_SCHEMA_ACTION = normalizeActionDescriptor({
  action_id: 'simulation.catalog.validate',
  name: 'Validate catalog',
  category: 'simulation',
  risk_level: 'low',
  read_only: true,
  side_effects: [],
  supports_dry_run: true,
  execution_mode: 'synchronous',
  required_permission: 'action.execute.low',
  timeout_seconds: 5,
  concurrency_limit: 2,
  enabled: true,
  available: true,
  parameter_schema: { type: 'object', properties: {}, additionalProperties: false },
});

const VIEWER_PERMISSIONS = ['action.read', 'action.dry_run', 'action.execute.low'];

test('Action descriptor 保留只读、风险、超时和并发合同', () => {
  assert.equal(EMPTY_SCHEMA_ACTION.action_id, 'simulation.catalog.validate');
  assert.equal(EMPTY_SCHEMA_ACTION.read_only, true);
  assert.equal(EMPTY_SCHEMA_ACTION.risk_level, 'low');
  assert.equal(EMPTY_SCHEMA_ACTION.timeout_seconds, 5);
  assert.equal(EMPTY_SCHEMA_ACTION.concurrency_limit, 2);
});

test('空参数 Action 构造严格 parameters={}', () => {
  assert.deepEqual(buildActionRequest(EMPTY_SCHEMA_ACTION, {}), { parameters: {} });
});

test('Parameter Schema default 只从已声明 properties 生成', () => {
  const action = { parameter_schema: { properties: { depth: { type: 'string', default: 'safe' }, absent: { type: 'string' } } } };
  assert.deepEqual(defaultActionParameters(action), { depth: 'safe' });
});

test('command 参数在前端预检拒绝', () => {
  assert.throws(() => buildActionRequest(EMPTY_SCHEMA_ACTION, { command: 'whoami' }), /禁止字段/);
});

test('path 与 file_path 参数在前端预检拒绝', () => {
  assert.throws(() => buildActionRequest(EMPTY_SCHEMA_ACTION, { path: 'x' }), /禁止字段/);
  assert.throws(() => buildActionRequest(EMPTY_SCHEMA_ACTION, { file_path: 'x' }), /禁止字段/);
});

test('SQL、script、handler 和 query 参数在前端预检拒绝', () => {
  for (const field of ['sql', 'script', 'handler', 'query']) {
    assert.throws(() => buildActionRequest(EMPTY_SCHEMA_ACTION, { [field]: 'x' }), /禁止字段/);
  }
});

test('additionalProperties=false 拒绝未声明参数', () => {
  assert.throws(() => buildActionRequest(EMPTY_SCHEMA_ACTION, { unexpected: true }), /未声明参数/);
});

test('required 参数缺失时不允许 dry-run payload', () => {
  const action = { parameter_schema: { properties: { fixture_id: { type: 'string' } }, required: ['fixture_id'], additionalProperties: false } };
  assert.throws(() => buildActionRequest(action, {}), /缺少必填参数/);
});

test('结构化 integer 与 boolean 参数严格归一化', () => {
  const action = { parameter_schema: { properties: { count: { type: 'integer' }, enabled: { type: 'boolean' } }, required: ['count', 'enabled'], additionalProperties: false } };
  assert.deepEqual(buildActionRequest(action, { count: '2', enabled: false }), { parameters: { count: 2, enabled: false } });
  assert.throws(() => buildActionRequest(action, { count: '2.5', enabled: false }), /整数/);
  assert.throws(() => buildActionRequest(action, { count: 2, enabled: 'false' }), /布尔/);
});

test('枚举参数只能选择 Schema 允许值', () => {
  const action = { parameter_schema: { properties: { depth: { type: 'string', enum: ['safe'] } }, additionalProperties: false } };
  assert.deepEqual(buildActionRequest(action, { depth: 'safe' }), { parameters: { depth: 'safe' } });
  assert.throws(() => buildActionRequest(action, { depth: 'deep' }), /允许范围/);
});

test('风险标签覆盖低中高关键', () => {
  assert.equal(riskMeta('low').label, '低');
  assert.equal(riskMeta('medium').label, '中');
  assert.equal(riskMeta('high').label, '高');
  assert.equal(riskMeta('critical').label, '关键');
});

test('Viewer 明确拥有 low-risk Action 权限', () => {
  assert.equal(hasActionPermission(VIEWER_PERMISSIONS, 'action.read'), true);
  assert.equal(hasActionPermission(VIEWER_PERMISSIONS, 'action.execute.low'), true);
  assert.equal(hasActionPermission(VIEWER_PERMISSIONS, 'action.execute.medium'), false);
});

test('可用 Action 且具备 action.dry_run 才可 Dry-run', () => {
  assert.equal(canDryRunAction(EMPTY_SCHEMA_ACTION, VIEWER_PERMISSIONS), true);
  assert.equal(canDryRunAction({ ...EMPTY_SCHEMA_ACTION, available: false }, VIEWER_PERMISSIONS), false);
  assert.equal(canDryRunAction(EMPTY_SCHEMA_ACTION, ['action.read']), false);
});

test('low-risk read-only 且 Dry-run allowed 才可执行安全检查', () => {
  assert.equal(canInvokeAction(EMPTY_SCHEMA_ACTION, { allowed: true }, VIEWER_PERMISSIONS), true);
  assert.equal(canInvokeAction(EMPTY_SCHEMA_ACTION, { allowed: false }, VIEWER_PERMISSIONS), false);
});

test('medium Action 对 Viewer 永远不可执行', () => {
  const medium = { ...EMPTY_SCHEMA_ACTION, risk_level: 'medium', required_permission: 'action.execute.medium' };
  assert.equal(canInvokeAction(medium, { allowed: true }, [...VIEWER_PERMISSIONS, 'action.execute.medium']), false);
});

test('非只读或声明 side effects 的 Action 不可执行', () => {
  assert.equal(canInvokeAction({ ...EMPTY_SCHEMA_ACTION, read_only: false }, { allowed: true }, VIEWER_PERMISSIONS), false);
  assert.equal(canInvokeAction({ ...EMPTY_SCHEMA_ACTION, side_effects: ['write'] }, { allowed: true }, VIEWER_PERMISSIONS), false);
});

test('成功结果视图提取 status、duration、summary、metrics 和 invocation', () => {
  const view = actionResultView({
    status: 'succeeded', duration_ms: 12, invocation_id: 'act-1', warnings: [],
    result_summary: { summary: { valid: true }, metrics: { count: 7 }, details: {} },
  });
  assert.deepEqual(view, {
    status: 'succeeded', durationMs: 12, invocationId: 'act-1', summary: { valid: true }, metrics: { count: 7 }, details: {}, warnings: [],
  });
});

test('failed 结果与 warnings 保持结构化', () => {
  const view = actionResultView({ status: 'failed', invocation_id: 'act-2', warnings: ['safe warning'], result_summary: {} });
  assert.equal(view.status, 'failed');
  assert.deepEqual(view.warnings, ['safe warning']);
});

test('Action client 使用四条固定 API 且不发送 Config Write Token', async () => {
  const previousFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'req-action' },
      json: async () => ({ success: true, request_id: 'req-action', data: { items: [], allowed: true, status: 'succeeded' } }),
    };
  };
  try {
    await getAdminActions('memory-token', { category: 'simulation', riskLevel: 'low', available: true });
    await getAdminAction('memory-token', 'simulation.catalog.validate');
    await dryRunAdminAction('memory-token', 'simulation.catalog.validate', {});
    await invokeAdminAction('memory-token', 'simulation.catalog.validate', {});
  } finally {
    globalThis.fetch = previousFetch;
  }
  assert.equal(calls.length, 4);
  assert.match(calls[0].url, /\/actions\?category=simulation&risk_level=low&available=true/);
  assert.match(calls[2].url, /simulation.catalog.validate\/dry-run$/);
  assert.match(calls[3].url, /simulation.catalog.validate\/invoke$/);
  assert.equal(calls[2].options.body, '{"parameters":{}}');
  for (const call of calls) {
    assert.equal(call.options.headers['X-Admin-Token'], 'memory-token');
    assert.equal(call.options.headers['X-Admin-Config-Token'], undefined);
    assert.equal(call.url.includes('memory-token'), false);
  }
});

test('/admin/actions 路由与普通根路由保持隔离', async () => {
  const adminSource = await readFile(new URL('./AdminApp.jsx', import.meta.url), 'utf8');
  const mainSource = await readFile(new URL('../main.jsx', import.meta.url), 'utf8');
  assert.match(adminSource, /path="actions"/);
  assert.match(mainSource, /path="\/admin\/\*"/);
  assert.match(mainSource, /path="\*" element=\{<App/);
});

test('Action 页面覆盖列表、筛选、详情、unavailable、loading、empty 与 API error', async () => {
  const source = await readFile(new URL('./pages/ActionsPage.jsx', import.meta.url), 'utf8');
  for (const marker of ['操作中心', 'Category', 'Risk', 'Availability', 'Parameter Schema', 'PageState', 'loading', 'Empty', 'actionError']) {
    assert.equal(source.includes(marker), true, marker);
  }
});

test('Action 页面明确先 Dry-run 再执行安全检查，并展示成功失败超时字段', async () => {
  const source = await readFile(new URL('./pages/ActionsPage.jsx', import.meta.url), 'utf8');
  for (const marker of ['当前仅开放只读安全操作', 'Dry-run', '执行安全检查', 'resultView.status', 'Duration', 'Invocation ID', 'ADMIN_ACTION_TIMEOUT', 'Request ID']) {
    assert.equal(source.includes(marker), true, marker);
  }
  assert.equal(source.includes('运行命令'), false);
  assert.equal(source.includes('执行脚本'), false);
});

test('Action Center 不新增持久化 Token 或 Action Token', async () => {
  const files = await Promise.all([
    readFile(new URL('./pages/ActionsPage.jsx', import.meta.url), 'utf8'),
    readFile(new URL('./auth/AdminAuthContext.jsx', import.meta.url), 'utf8'),
    readFile(new URL('./api/adminClient.js', import.meta.url), 'utf8'),
  ]);
  const source = files.join('\n');
  for (const forbidden of ['localStorage', 'sessionStorage', 'indexedDB', 'Action Token', 'X-Admin-Action-Token', 'console.']) {
    assert.equal(source.includes(forbidden), false, forbidden);
  }
});

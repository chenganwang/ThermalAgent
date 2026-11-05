import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import { readFile } from 'node:fs/promises';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { getCfdJob, getCfdJobReport, getCfdJobs, getCfdStatus, prepareCfdJob, runCfdJob } from '../api/client.js';
import { canRunFluentJob, cfdProvenance, fluentAvailability, fluentError, fluentJobStatus, fluentValidation, historySeries, prepareFluentInputs, publicCfdEnvironment } from './fluentPresentation.js';

const status = {
  schema_version: '1.0', enabled: true, execution_enabled: true, solver_found: true, license_checked: false,
  selected_backend: 'fluent', requested_backend: 'auto', real_execution_enabled: true,
  cases: [{ case_id: 'cold_plate', title: '冷板', dimension: '3ddp', reports: [{ name: '出口温度', unit: 'K' }] }],
  limits: { max_iterations: 1000, max_processors: 4 },
};
const prepared = { job_id: 'job-1', case_id: 'cold_plate', status: 'prepared', iterations: 100, processors: 1, input_fingerprint: 'frozen-input', effective_backend: 'fluent', is_mock: false };

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: FluentJobDetails } = await vite.ssrLoadModule('/src/fluent/FluentJobDetails.jsx');
const { default: FluentPanel } = await vite.ssrLoadModule('/src/fluent/FluentPanel.jsx');
const { default: PhysicsValidationCard } = await vite.ssrLoadModule('/src/PhysicsValidationCard.jsx');
const { default: CfdEnvironmentReport } = await vite.ssrLoadModule('/src/fluent/CfdEnvironmentReport.jsx');
after(() => vite.close());

test('Fluent availability never infers a license check or overrides backend gates', () => {
  assert.equal(fluentAvailability(null).canPrepare, false);
  assert.equal(fluentAvailability({ ...status, enabled: false }).canPrepare, false);
  assert.equal(fluentAvailability({ ...status, cases: [] }).canPrepare, false);
  assert.equal(fluentAvailability({ ...status, execution_enabled: false }).canPrepare, true);
  assert.equal(fluentAvailability({ ...status, solver_found: false }).canRun, false);
  assert.equal(fluentAvailability(status, true).canRun, false);
  assert.match(fluentAvailability(status).message, /运行后才能确认/);
});

test('Fluent preparation accepts only registered cases and bounded positive integers', () => {
  const values = { case_id: 'cold_plate', iterations: 50, processors: 2, path: 'ignored', command: 'ignored' };
  assert.deepEqual(prepareFluentInputs(values, status).payload, { case_id: 'cold_plate', iterations: 50, processors: 2 });
  for (const override of [{ case_id: 'unknown' }, { iterations: 0 }, { iterations: 1001 }, { processors: 5 }, { processors: 1.5 }, { processors: null }, { iterations: NaN }, { iterations: '50' }]) {
    assert.equal(prepareFluentInputs({ ...values, ...override }, status).payload, null);
  }
});

test('only a prepared fingerprinted task can be explicitly run', () => {
  assert.equal(canRunFluentJob(prepared, status), true);
  for (const state of ['running', 'completed', 'failed', 'timed_out', 'interrupted', 'unknown']) {
    assert.equal(canRunFluentJob({ ...prepared, status: state }, status), false);
  }
  assert.equal(canRunFluentJob({ ...prepared, input_fingerprint: '' }, status), false);
  assert.equal(canRunFluentJob(prepared, { ...status, execution_enabled: false }), false);
});

test('completion and missing validation are never presented as verified physics', () => {
  assert.notEqual(fluentJobStatus('completed').color, 'success');
  assert.equal(fluentValidation(null).type, 'warning');
  assert.equal(fluentValidation({ status: 'failed' }).type, 'error');
  assert.equal(fluentValidation({ status: 'passed' }).label, '已通过已配置检查');
});

test('chart uses actual finite monitor values and drops invalid points without inventing samples', () => {
  assert.deepEqual(historySeries({ points: [[1, 300], [2, NaN], [3, Infinity], ['4', 303], null, [5, 302]] }), [[1, 300], [5, 302]]);
  assert.deepEqual(historySeries(null), []);
});

test('Fluent client uses fixed routes, explicit confirmation and the prepared fingerprint', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => { requests.push({ url, options }); return new Response('{}', { status: 200 }); };
  try {
    await getCfdStatus();
    await getCfdJobs();
    await prepareCfdJob({ case_id: 'cold_plate', iterations: 100, processors: 1, path: 'not sent' });
    await getCfdJob('job 1');
    await runCfdJob('job 1', 'frozen-input');
    await getCfdJobReport('job 1');
  } finally { globalThis.fetch = originalFetch; }
  assert.deepEqual(requests.map(request => request.url), ['/api/simulation/cfd/status', '/api/simulation/cfd/jobs', '/api/simulation/cfd/jobs', '/api/simulation/cfd/jobs/job%201', '/api/simulation/cfd/jobs/job%201/run', '/api/simulation/cfd/jobs/job%201/report']);
  assert.deepEqual(JSON.parse(requests[2].options.body), { case_id: 'cold_plate', iterations: 100, processors: 1 });
  assert.deepEqual(JSON.parse(requests[4].options.body), { confirmed: true, input_fingerprint: 'frozen-input' });
  assert.equal(requests.every(request => request.options.signal instanceof AbortSignal), true);
});

test('Fluent API forwards cancellation and keeps structured error response available', async () => {
  const originalFetch = globalThis.fetch;
  const controller = new AbortController();
  controller.abort();
  globalThis.fetch = async (_, options) => {
    assert.equal(options.signal.aborted, true);
    throw new DOMException('cancelled', 'AbortError');
  };
  try { await assert.rejects(getCfdStatus({ signal: controller.signal }), { name: 'AbortError' }); }
  finally { globalThis.fetch = originalFetch; }
  assert.match(fluentError({ name: 'AbortError' }), /确认服务器是否已接收任务/);
  assert.match(fluentError({ statusCode: 422 }), /参数/);
  assert.doesNotMatch(fluentError({ message: 'private C:/path/token' }), /private|token/);
});

test('disabled and mock Fluent panel renders honest state without a runnable fake case', () => {
  const html = renderToStaticMarkup(React.createElement(FluentPanel, { active: false, useMockResponses: true }));
  assert.match(html, /前端离线演示模式/);
  assert.match(html, /暂无任务/);
  assert.doesNotMatch(html, /确认启动 CFD|真实 Fluent 输出/);
});

test('prepared task renders its frozen inputs and distinct confirmation action', () => {
  const html = renderToStaticMarkup(React.createElement(FluentJobDetails, { job: prepared, status }));
  assert.match(html, /确认启动 CFD/);
  assert.match(html, /frozen-input/);
  assert.match(html, /修改表单后需重新准备任务/);
});

test('real task output shows monitor chart and incomplete validation independently', () => {
  const job = { ...prepared, status: 'completed', result: { is_mock: false, metrics: [{ name: '出口温度', value: 301, unit: 'K' }], histories: [{ name: '出口温度', unit: 'K', points: [[1, 300], [2, 301]] }], validation: { status: 'incomplete', checks: [{ name: '能量平衡', status: 'incomplete', message: '缺少入口焓流' }] } } };
  const html = renderToStaticMarkup(React.createElement(FluentJobDetails, { job, status }));
  assert.match(html, /真实 Fluent 输出/);
  assert.match(html, /验证证据不完整/);
  assert.match(html, /301 K/);
  assert.match(html, /role="img"/);
  assert.match(html, /缺少入口焓流/);
  assert.doesNotMatch(html, /确认启动 CFD/);
});

test('polling is bounded to visible running tasks and never issues run requests automatically', async () => {
  const hook = await readFile(new URL('./useFluentJobs.js', import.meta.url), 'utf8');
  assert.match(hook, /!active.*!hasRunning/);
  assert.match(hook, /clearTimeout\(timer\)/);
  assert.match(hook, /controller\.abort\(\)/);
  assert.match(hook, /const run = job => perform/);
});

test('physics validation attaches only to explicit backend evidence and shows failed issues', () => {
  assert.equal(renderToStaticMarkup(React.createElement(PhysicsValidationCard, { response: { answer: '普通回答' } })), '');
  const evidence = { schema_version: '1.0', validator_version: 'physics-v1', passed: false, status: 'failed', checked_quantity_count: 2, energy_balance_checked: false, issues: [{ code: 'NEGATIVE', message: '导热系数必须为正数' }], limitations: ['输入采用 SI 单位'] };
  for (const metadata of [{ calculation: { raw: { physics_validation: evidence } } }, { calculation_result: { physics_validation: evidence } }]) {
    const html = renderToStaticMarkup(React.createElement(PhysicsValidationCard, { response: { metadata } }));
    assert.match(html, /规则校验未通过/);
    assert.match(html, /检查 2 个物理量/);
    assert.match(html, /导热系数必须为正数/);
    assert.match(html, /未检查能量平衡/);
    assert.doesNotMatch(html, /已通过已配置规则/);
  }
});

test('backend-selected Mock can run without a solver and remains distinct from offline UI fixtures', () => {
  const mock = { ...status, selected_backend: 'mock', solver_found: false, real_execution_enabled: false };
  assert.equal(fluentAvailability(mock).canRun, true);
  assert.equal(fluentAvailability(mock, true).canRun, false);
  assert.equal(fluentAvailability({ ...mock, enabled: false }).canRun, false);
  assert.equal(fluentAvailability({ ...mock, execution_enabled: false }).canRun, false);
  assert.equal(fluentAvailability({ ...mock, selected_backend: 'unavailable' }).canRun, false);
});

test('any Mock provenance marker prevents a real-output claim, including contradictory fields', () => {
  const real = { ...prepared, result: { is_mock: false, effective_backend: 'fluent' } };
  assert.equal(cfdProvenance(real).resultLabel, '真实 Fluent 输出');
  for (const record of [
    { ...real, is_mock: true },
    { ...real, effective_backend: 'mock' },
    { ...real, result: { is_mock: true, effective_backend: 'fluent' } },
    { ...real, result: { is_mock: false, effective_backend: 'mock' } },
  ]) {
    assert.equal(cfdProvenance(record).isMock, true);
    assert.equal(cfdProvenance(record).resultLabel, 'Mock CFD 演示输出');
    assert.match(cfdProvenance(record).warning, /不能用于真实工程结论/);
  }
  assert.equal(cfdProvenance({ result: { is_mock: false } }).resultLabel, '执行来源未确认');
});

test('prepared server job remains confirmable when auto selection changes its available case list', () => {
  const mockStatus = { ...status, selected_backend: 'mock', solver_found: false, cases: [{ case_id: 'mock_cfd_demo' }] };
  assert.equal(canRunFluentJob(prepared, mockStatus), true);
  assert.equal(canRunFluentJob({ ...prepared, input_fingerprint: '' }, mockStatus), false);
});

test('Mock job result and fallback show effective demo case without claiming original-case simulation', () => {
  const job = { ...prepared, status: 'completed', is_mock: true, effective_backend: 'mock', requested_case_id: 'cold_plate', effective_case_id: 'mock_cfd_demo', fallback_reason: { code: 'FLUENT_UNAVAILABLE', message: '本机求解环境不可用，切换为演示。' }, result: { is_mock: true, effective_backend: 'mock', metrics: [{ name: '出口温度', value: 301, unit: 'K' }], histories: [{ name: '出口温度', unit: 'K', points: [[1, 300], [2, 301]] }], validation: { status: 'passed', checks: [] } } };
  const html = renderToStaticMarkup(React.createElement(FluentJobDetails, { job, status }));
  assert.match(html, /Mock CFD \/ 演示数据，不能用于真实工程结论/);
  assert.match(html, /未求解请求算例/);
  assert.match(html, /演示数据检查/);
  assert.match(html, /本机求解环境不可用/);
  assert.match(html, /role="img"/);
  assert.doesNotMatch(html, /真实 Fluent 输出/);
});

test('Mock preparation retains its explicit confirmation action', () => {
  const mock = { ...status, selected_backend: 'mock', solver_found: false };
  const html = renderToStaticMarkup(React.createElement(FluentJobDetails, { job: { ...prepared, is_mock: true, effective_backend: 'mock' }, status: mock }));
  assert.match(html, /确认运行 Mock CFD/);
  assert.match(html, /输出不是实际流场求解结果/);
  assert.doesNotMatch(html, /真实 Fluent 输出|确认启动 CFD/);
});

test('environment report projects public fields only and never treats missing license evidence as checked', () => {
  const statusWithEnvironment = { ...status, environment: { schema_version: '1.0', status: 'unavailable', solver_found: false, version: null, license_checked: false, requested_path_kind: 'framework', resolution_source: 'sibling_search', executable_path: 'private-path', checks: [{ name: '求解器', status: 'failed', code: 'NOT_FOUND', message: '未找到求解器', path: 'private-path' }] } };
  const projection = publicCfdEnvironment(statusWithEnvironment);
  assert.equal(projection.license_checked, false);
  assert.doesNotMatch(JSON.stringify(projection), /private-path|executable_path/);
  const html = renderToStaticMarkup(React.createElement(CfdEnvironmentReport, { status: statusWithEnvironment }));
  assert.match(html, /环境检测报告/);
  assert.match(html, /真实环境未就绪/);
  assert.match(html, /未检查/);
  assert.match(html, /下载环境报告/);
  assert.doesNotMatch(html, /private-path/);
});

test('Mock spatial temperature plots use position in metres and do not claim iteration convergence', () => {
  const job = { ...prepared, status: 'completed', is_mock: true, effective_backend: 'mock', result: { is_mock: true, effective_backend: 'mock', metrics: [], histories: [{ name: '温度分布', unit: 'K', axis: 'position_m', axis_unit: 'm', points: [[0, 310], [0.05, 300]] }], validation: { status: 'incomplete', checks: [] } } };
  const html = renderToStaticMarkup(React.createElement(FluentJobDetails, { job, status }));
  assert.match(html, /位置 \(m\)/);
  assert.match(html, /空间分布/);
  assert.match(html, /Mock 演示/);
  assert.match(html, /不能用于真实工程结论/);
  assert.doesNotMatch(html, /迭代次数的变化|次迭代|随迭代/);
});

test('deferred or unchecked environments never report that a solver was not found', () => {
  for (const environmentStatus of ['deferred', 'not_checked', null]) {
    const deferredStatus = { ...status, environment: { schema_version: '1.0', status: environmentStatus, solver_found: false, version: null, license_checked: false, checks: [{ name: '真实集成', status: 'not_checked', message: '按当前范围暂缓检查，使用 Mock。' }] } };
    const html = renderToStaticMarkup(React.createElement(CfdEnvironmentReport, { status: deferredStatus }));
    assert.match(html, environmentStatus === 'deferred' ? /暂缓检查/ : /尚未检查/);
    assert.match(html, /未检查/);
    assert.doesNotMatch(html, /未找到|真实环境未就绪|未识别/);
  }
  assert.equal(publicCfdEnvironment({ environment: { status: 'available' } }).solver_found, null);
});

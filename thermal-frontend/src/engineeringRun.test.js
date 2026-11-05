import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { createServer } from 'vite';
import { engineeringRunPresentation, engineeringValue } from './engineeringRunPresentation.js';

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: EngineeringRunCard } = await vite.ssrLoadModule('/src/EngineeringRunCard.jsx');
after(() => vite.close());

const run = {
  schema_version: '1.0', scope: 'deterministic_calculation', run_id: 'run-1', status: 'completed', tool_name: 'conductive_thermal_resistance', tool_version: '1.0', input_fingerprint: 'input-hash',
  steps: [{ step_id: 'input', title: '检查输入', depends_on: [], status: 'completed' }, { step_id: 'calculate', title: '计算热阻', depends_on: ['input'], status: 'completed' }],
  variables: [{ name: 'thickness', value: 0.005, unit: 'm', role: 'input', source: 'user', step_id: 'input' }, { name: 'resistance', value: 0.25, unit: 'K/W', role: 'output', source: 'tool', step_id: 'calculate' }],
  validation: { status: 'passed', passed: true, checks: [{ name: '正值检查', status: 'passed', message: '几何参数大于零' }], limitations: ['常物性条件'] },
  evidence: [{ doc_id: 1, chunk_id: 2, title: '导热参考资料', page_start: 3, page_end: 4 }], report: { generated: true, content_sha256: 'report-hash' }, limitations: ['常物性条件'],
};
const response = engineeringRun => ({ metadata: { engineering_run: engineeringRun } });
// Captured from the real /engineering/reference/solve router with temporary SQLite.
const referenceResponse = JSON.parse(readFileSync(new URL('./engineering/referenceResponse.fixture.json', import.meta.url), 'utf8'));

test('engineering execution card appears only for explicitly supported schema and scope pairs', () => {
  assert.equal(engineeringRunPresentation({ answer: '普通问答' }), null);
  assert.equal(engineeringRunPresentation(response({ ...run, schema_version: '2.0' })), null);
  assert.equal(engineeringRunPresentation(response({ ...run, scope: 'llm_reasoning' })), null);
  assert.equal(engineeringRunPresentation(response({ ...run, scope: 'reference_calculation' })), null);
  assert.equal(engineeringRunPresentation(response({ ...run, schema_version: '1.1' })), null);
  assert.equal(renderToStaticMarkup(React.createElement(EngineeringRunCard, { response: {} })), '');
});

test('real reference response renders its declared 1.1 receipt and preserves reproducibility evidence', () => {
  const reference = referenceResponse.engineering_run;
  const view = engineeringRunPresentation(response(reference));
  assert.equal(view.record.schema_version, '1.1');
  assert.equal(view.record.scope, 'reference_calculation');
  assert.equal(view.record.model_version, 'steady-1d-constant-k-v1');
  assert.equal(view.record.project_id, 'local');
  assert.equal(view.record.persistence.saved, true);
  assert.equal(view.record.persistence.revision, reference.persistence.revision);
  assert.equal(view.record.persistence.report_sha256, reference.report.content_sha256);
  assert.equal(view.persistence.label, '已保存到工程历史');
  assert.equal(view.record.evidence[0].type, 'formula');
  assert.equal(view.record.evidence[0].formula, reference.evidence[0].formula);
  assert.equal(view.record.evidence[0].source, 'steady conduction conservation');
  assert.equal(view.record.validation.energy_relative_error, 0);
  assert.equal(view.record.validation.energy_balance_checked, true);
  assert.deepEqual(view.record.verification, reference.verification);
  assert.deepEqual(view.record.input_snapshot, reference.input_snapshot);
  const heat = view.record.variables.find(variable => variable.name === 'heat_rate');
  assert.deepEqual([heat.value, heat.unit], [384, 'W']);
  const html = renderToStaticMarkup(React.createElement(EngineeringRunCard, { response: response(reference) }));
  assert.match(html, /engineering-run-card/);
  assert.match(html, /steady-1d-constant-k-v1/);
  assert.match(html, /已保存到工程历史/);
  assert.match(html, /R_i = L_i/);
  assert.doesNotMatch(html, /engineering-persistence-warning/);
});

test('immediate persistence failures are visible outside the collapsed receipt without leaking extra fields', () => {
  const reference = { ...referenceResponse.engineering_run, persistence: { enabled: true, saved: false, error_code: 'ENGINEERING_PERSISTENCE_FAILED', error_type: 'OSError', message: '本次执行记录未完整保存；计算结果仍可查看。', private_path: 'private-storage-path' }, verification: { ...referenceResponse.engineering_run.verification, private_debug: 'private-solver-debug' } };
  const view = engineeringRunPresentation(response(reference));
  assert.equal(view.persistence.failed, true);
  assert.equal(view.record.persistence.error_code, 'ENGINEERING_PERSISTENCE_FAILED');
  assert.doesNotMatch(JSON.stringify(view.record), /private-storage-path|private-solver-debug|private_path|private_debug/);
  const html = renderToStaticMarkup(React.createElement(EngineeringRunCard, { response: response(reference) }));
  assert.ok(html.indexOf('engineering-persistence-warning') < html.indexOf('engineering-run-card'));
  assert.match(html, /执行记录未完整保存/);
  assert.doesNotMatch(html, /已保存到工程历史/);
});

test('legacy receipts without persistence remain readable with a neutral save status', () => {
  const view = engineeringRunPresentation(response(run));
  assert.equal(view.record.schema_version, '1.0');
  assert.equal(view.record.scope, 'deterministic_calculation');
  assert.equal(view.record.persistence, null);
  assert.equal(view.persistence.failed, false);
  assert.equal(view.persistence.label, '未提供保存状态');
  const html = renderToStaticMarkup(React.createElement(EngineeringRunCard, { response: response(run) }));
  assert.doesNotMatch(html, /engineering-persistence-warning|已保存到工程历史|执行记录未完整保存/);
});

test('engineering record keeps numeric values and explicit units without inventing missing units', () => {
  const view = engineeringRunPresentation(response({ ...run, variables: [...run.variables, { name: 'unknown', value: 0, unit: null, role: 'output' }] }));
  assert.equal(view.variables[0].display, '0.005');
  assert.equal(view.variables[0].unit, 'm');
  assert.equal(view.variables[1].unit, 'K/W');
  assert.equal(view.variables[2].display, '0');
  assert.equal(view.variables[2].unit, null);
  assert.equal(engineeringValue(NaN), '无有效数值');
  assert.equal(engineeringValue({ a: 1 }), '{"a":1}');
});

test('completed execution does not imply validation passed when evidence is incomplete', () => {
  const view = engineeringRunPresentation(response({ ...run, validation: { status: 'incomplete', passed: false } }));
  assert.equal(view.status.label, '执行完成');
  assert.equal(view.validation.type, 'warning');
  assert.equal(engineeringRunPresentation(response({ ...run, validation: { status: 'passed', passed: false } })).validation.type, 'warning');
});

test('execution record projection preserves reproducibility fields and excludes undeclared private details', () => {
  const view = engineeringRunPresentation(response({ ...run, local_path: 'private-path', validation: { ...run.validation, raw_debug: 'private-secret' }, evidence: [{ ...run.evidence[0], local_path: 'private-path' }] }));
  assert.equal(view.record.input_fingerprint, 'input-hash');
  assert.equal(view.record.report.content_sha256, 'report-hash');
  assert.equal(view.record.variables[1].step_id, 'calculate');
  assert.deepEqual(view.limitations, ['常物性条件']);
  assert.doesNotMatch(JSON.stringify(view.record), /private-path|private-secret|local_path|raw_debug/);
});

test('collapsed execution card displays steps, values, validation and limitations as an auditable record', () => {
  const html = renderToStaticMarkup(React.createElement(EngineeringRunCard, { response: response(run) }));
  assert.match(html, /工程执行记录/);
  assert.match(html, /计算热阻/);
  assert.match(html, /0.005/);
  assert.match(html, /K\/W/);
  assert.match(html, /已通过已配置检查/);
  assert.match(html, /常物性条件/);
  assert.match(html, /导热参考资料/);
  assert.match(html, /下载执行记录/);
  assert.doesNotMatch(html, /<details[^>]* open|自主规划成功|多Agent执行成功/);
});

test('blocked and sparse execution records remain readable and never manufacture a result', () => {
  const sparse = { schema_version: '1.0', scope: 'deterministic_calculation', status: 'blocked', steps: [{ title: '等待输入', status: 'blocked', error: { message: '缺少面积' } }] };
  const html = renderToStaticMarkup(React.createElement(EngineeringRunCard, { response: response(sparse) }));
  assert.match(html, /等待补充条件/);
  assert.match(html, /缺少面积/);
  assert.match(html, /未提供输入输出变量/);
  assert.match(html, /校验证据不完整/);
  assert.doesNotMatch(html, /已通过已配置检查/);
});

test('download preserves declared problem, formula, snapshots, events and timestamps without private extras', () => {
  const detailed = { ...run, formula: 'R=L/(k*A)', problem: { description: '计算平壁热阻', required_parameters: ['L', 'k', 'A'], missing_parameters: [], assumptions: ['稳态一维导热'], debug: 'private-problem' }, input_snapshot: { L: 0.005, k: 10, A: 0.002, layers: [{ name: 'wall', conductivity: 10 }] }, events: [{ sequence: 1, step_id: 'input', status: 'completed', at: '2026-09-09T10:00:00Z', internal_path: 'private-event' }], created_at: '2026-09-09T10:00:00Z', finished_at: '2026-09-09T10:00:01Z' };
  const view = engineeringRunPresentation(response(detailed));
  assert.equal(view.record.formula, 'R=L/(k*A)');
  assert.deepEqual(view.record.problem, { description: '计算平壁热阻', required_parameters: ['L', 'k', 'A'], missing_parameters: [], assumptions: ['稳态一维导热'] });
  assert.deepEqual(view.record.input_snapshot, detailed.input_snapshot);
  assert.deepEqual(view.record.events, [{ sequence: 1, step_id: 'input', status: 'completed', at: '2026-09-09T10:00:00Z' }]);
  assert.equal(view.record.created_at, detailed.created_at);
  assert.equal(view.record.finished_at, detailed.finished_at);
  assert.doesNotMatch(JSON.stringify(view.record), /private-problem|private-event|internal_path/);
  const html = renderToStaticMarkup(React.createElement(EngineeringRunCard, { response: response(detailed) }));
  assert.match(html, /问题与计算依据/);
  assert.match(html, /稳态一维导热/);
  assert.match(html, /R=L\/\(k\*A\)/);
});

test('shared validator issues remain visible and exported when no checks array exists', () => {
  const failed = { ...run, status: 'failed', validation: { status: 'failed', passed: false, issues: [{ code: 'NON_POSITIVE', field: 'k', message: '导热系数必须为正数', debug: 'private-validator' }] } };
  const view = engineeringRunPresentation(response(failed));
  assert.deepEqual(view.record.validation.issues, [{ code: 'NON_POSITIVE', field: 'k', message: '导热系数必须为正数' }]);
  assert.deepEqual(view.validation.checks, []);
  const html = renderToStaticMarkup(React.createElement(EngineeringRunCard, { response: response(failed) }));
  assert.match(html, /校验未通过/);
  assert.match(html, /导热系数必须为正数/);
  assert.match(html, /NON_POSITIVE/);
  assert.doesNotMatch(JSON.stringify(view.record), /private-validator/);
});

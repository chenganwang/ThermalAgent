import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { createServer } from 'vite';
import { compareEngineeringRuns, createEngineeringProject, getEngineeringArtifact, getEngineeringProjects, getEngineeringRun, getEngineeringRuns, resumeEngineeringRun, solveReferenceWall } from '../api/client.js';
import { canResumeRun, historyError, referenceInputs, runStatus } from './engineeringHistory.js';
import { assertRunIdentity } from '../resultIdentity.js';

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: RunDetails } = await vite.ssrLoadModule('/src/engineering/RunDetails.jsx');
const { default: RunComparison } = await vite.ssrLoadModule('/src/engineering/RunComparison.jsx');
const { default: ReferenceWallForm } = await vite.ssrLoadModule('/src/engineering/ReferenceWallForm.jsx');
const { default: EngineeringHistoryPanel } = await vite.ssrLoadModule('/src/engineering/EngineeringHistoryPanel.jsx');
after(() => vite.close());
const referenceResponse = JSON.parse(readFileSync(new URL('./referenceResponse.fixture.json', import.meta.url), 'utf8'));

test('run-history detail identity is checked before a stored receipt can be marked saved', () => {
  assert.throws(() => assertRunIdentity({ run_id: 'wrong' }, 'requested'), /身份不一致/);
  const html = renderToStaticMarkup(React.createElement(RunDetails, { run: { run_id: 'requested', receipt: { run_id: 'old', input_fingerprint: 'old-input' } } }));
  assert.match(html, /已阻止展示/); assert.doesNotMatch(html, /已保存到工程历史/);
});

test('engineering requests use fixed routes, revision confirmation and declared payloads', async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return new Response('{}', { headers: { 'Content-Type': 'application/json' } }); };
  try {
    await getEngineeringProjects();
    await createEngineeringProject({ title: '热设计', description: '壁面' });
    await getEngineeringRuns({ projectId: 'local', offset: 30 });
    await getEngineeringRun('run/1');
    await compareEngineeringRuns(['a', 'b']);
    await resumeEngineeringRun('a', 7);
    await solveReferenceWall({ area_m2: 1 }, 'project-a');
  } finally { globalThis.fetch = original; }
  assert.equal(calls[0].url, '/api/engineering/projects');
  assert.deepEqual(JSON.parse(calls[1].options.body), { title: '热设计', description: '壁面' });
  assert.equal(calls[2].url, '/api/engineering/runs?project_id=local&limit=30&offset=30');
  assert.equal(calls[3].url, '/api/engineering/runs/run%2F1');
  assert.deepEqual(JSON.parse(calls[4].options.body), { run_ids: ['a', 'b'] });
  assert.deepEqual(JSON.parse(calls[5].options.body), { expected_revision: 7, confirmed: true });
  assert.deepEqual(JSON.parse(calls[6].options.body), { inputs: { area_m2: 1 }, project_id: 'project-a' });
});

test('artifact download preserves exact bytes instead of reserializing JSON', async () => {
  const raw = '{ "input": 0.000001 }\n';
  const original = globalThis.fetch;
  let requested;
  globalThis.fetch = async url => { requested = url; return new Response(raw, { headers: { 'Content-Type': 'application/json' } }); };
  try {
    const blob = await getEngineeringArtifact('run-1', 'artifact/1');
    assert.equal(await blob.text(), raw);
    assert.equal(requested, '/api/engineering/runs/run-1/artifacts/artifact%2F1');
  } finally { globalThis.fetch = original; }
});

test('resumption requires explicit recoverability, inactive state and valid revision', () => {
  const run = { run_id: 'a', status: 'failed', recoverable: true, active: false, revision: 2, resumed_by: null };
  assert.equal(canResumeRun(run), true);
  for (const fields of [{ active: true }, { active: undefined }, { status: 'completed' }, { recoverable: false }, { revision: 0 }, { revision: '2' }, { resumed_by: 'b' }]) assert.equal(canResumeRun({ ...run, ...fields }), false);
});

test('reference form preserves SI values and accepts reversed heat-flow direction', () => {
  const values = { area: 0.002, thickness: 0.005, conductivity: 16, left: 290, right: 350 };
  assert.deepEqual(referenceInputs(values), { errors: [], inputs: { area_m2: 0.002, left_temperature_k: 290, right_temperature_k: 350, layers: [{ thickness_m: 0.005, conductivity_w_mk: 16 }], cells_per_layer: 2 } });
  for (const value of [0, -1, null, '5', Infinity, NaN]) assert.equal(referenceInputs({ ...values, thickness: value }).inputs, null);
});

test('incompatible comparisons suppress a supplied delta and do not invent units', () => {
  const html = renderToStaticMarkup(React.createElement(RunComparison, { comparison: { compatible: false, warnings: ['单位不一致'], runs: [{ run_id: 'a' }, { run_id: 'b' }], variables: [{ name: 'Q', unit: null, values: [0, 10], delta: 999 }] } }));
  assert.match(html, /单位不一致/);
  assert.match(html, /未提供\/不一致/);
  assert.match(html, /不可比较/);
  assert.doesNotMatch(html, />999</);
});

test('compatible comparisons display server values and zero deltas unchanged', () => {
  const html = renderToStaticMarkup(React.createElement(RunComparison, { comparison: { compatible: true, runs: [{ run_id: 'a' }, { run_id: 'b' }], variables: [{ name: 'Q', unit: 'W', values: [384, 384], delta: 0 }] } }));
  assert.match(html, /384/);
  assert.match(html, />0<\/td>/);
  assert.match(html, />W<\/td>/);
});

test('failed-run details expose auditable timeline and explicit linked recalculation', () => {
  assert.equal(runStatus('planned'), '已规划');
  assert.equal(runStatus('skipped'), '已跳过');
  const run = { run_id: 'a', status: 'failed', recoverable: true, active: false, revision: 2, receipt: { events: [{ at: '2026-09-09T10:00:00Z', step_id: 'calculate', status: 'failed' }] }, artifacts: [{ artifact_id: 'report-a', kind: 'report', sha256: 'fingerprint' }] };
  const html = renderToStaticMarkup(React.createElement(RunDetails, { run }));
  assert.match(html, /2026-09-09T10:00:00Z/);
  assert.match(html, /calculate/);
  assert.match(html, /恢复为关联重算/);
  assert.match(html, /保留原记录/);
  assert.match(html, /fingerprint/);
  const completed = renderToStaticMarkup(React.createElement(RunDetails, { run: { ...run, status: 'completed' } }));
  assert.doesNotMatch(completed, /恢复为关联重算/);
});

test('reference form labels actual one-dimensional inputs and never claims CFD execution', () => {
  const html = renderToStaticMarkup(React.createElement(ReferenceWallForm, {}));
  assert.match(html, /面积 \(m²\)/);
  assert.match(html, /绝对 K/);
  assert.match(html, /不求解 CFD 流场/);
  assert.match(html, /执行并保存参考计算/);
  const resultHtml = renderToStaticMarkup(React.createElement(ReferenceWallForm, { response: { result: {} } }));
  assert.match(resultHtml, /输入与状态以回执为准/);
});

test('stored reference detail displays its existing checkpoint as saved without mutating the receipt', () => {
  const receipt = structuredClone(referenceResponse.engineering_run);
  const persistence = receipt.persistence;
  delete receipt.persistence;
  const html = renderToStaticMarkup(React.createElement(RunDetails, { run: { ...persistence, receipt, status: receipt.status, created_at: receipt.created_at, model_version: receipt.model_version, active: false, recoverable: false } }));
  assert.match(html, /engineering-run-card/);
  assert.match(html, /已保存到工程历史/);
  assert.match(html, /steady conduction conservation/);
  assert.doesNotMatch(html, /engineering-persistence-warning|未提供保存状态/);
  assert.equal(receipt.persistence, undefined);
});

test('actual reference solve response shows a receipt alongside the spatial chart and report', () => {
  const html = renderToStaticMarkup(React.createElement(ReferenceWallForm, { response: referenceResponse }));
  assert.match(html, /engineering-run-card/);
  assert.match(html, /已保存到工程历史/);
  assert.match(html, /位置/);
  assert.match(html, /<table/);
  assert.match(html, /384/);
});

test('offline history makes its disabled service boundary visible', () => {
  const html = renderToStaticMarkup(React.createElement(EngineeringHistoryPanel, { active: true, useMockResponses: true }));
  assert.match(html, /前端离线示例模式不连接工程历史服务/);
  assert.match(html, /Mock 演示不等于真实 CFD/);
});

test('conflict and abort feedback never claim that a server run was cancelled', () => {
  assert.match(historyError({ statusCode: 409 }), /刷新后核对/);
  assert.match(historyError({ name: 'AbortError' }), /后台操作可能仍在完成/);
  assert.match(historyError({ statusCode: 404 }), /旧版后端/);
});

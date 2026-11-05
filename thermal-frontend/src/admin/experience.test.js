import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { coverageView, knownCount, monitorTotal, revisionIndexStatus, taskProgress, taskStatus } from './presentation/experience.js';
import { getAgentTask, getAgentTasks, getKnowledgeCoverage } from './api/adminClient.js';

test('unknown counts and unavailable task stores remain unknown', () => {
  for (const value of [null, undefined, true, '0', -1, NaN, Infinity]) assert.equal(knownCount(value), null);
  assert.equal(knownCount(0), 0);
  assert.equal(monitorTotal({ total: 0, store_available: false }), null);
  assert.equal(monitorTotal({ total: 0, store_available: true }), 0);
});
test('coverage separates source ingestion from active index mapping', () => {
  const view = coverageView({ status: 'gap', active_chunks: 909, indexed_active_chunks: 367, missing_chunks: 542 });
  assert.equal(view.known, true);
  assert.equal(view.missing, 542);
  assert.match(view.description, /尚未进入/);
  assert.ok(view.percent > 40 && view.percent < 41);
});
test('inconsistent mapping cannot become covered or an invented percentage', () => {
  for (const data of [undefined, { active_chunks: 9 }, { status: 'covered', active_chunks: 9, indexed_active_chunks: 10, missing_chunks: 0 }, { status: 'unknown', active_chunks: 0, indexed_active_chunks: 0, missing_chunks: 0 }]) {
    const view = coverageView(data);
    assert.equal(view.known, false);
    assert.equal(view.percent, null);
    assert.equal(view.status, 'unknown');
  }
});
test('stale mappings remain a warning even with all active chunks covered', () => {
  const view = coverageView({ status: 'gap', active_chunks: 2, indexed_active_chunks: 2, missing_chunks: 0 });
  assert.match(view.description, /失效/);
  assert.equal(view.status, 'gap');
});
test('revision sync cannot assert full index coverage in document detail', () => {
  assert.equal(revisionIndexStatus('synced').label, '无待同步修订');
  assert.equal(revisionIndexStatus('synced').color, 'default');
  assert.equal(revisionIndexStatus('unknown').label, '修订状态未获取');
});
test('failed and interrupted task status is distinct from progress', () => {
  assert.equal(taskStatus('failed').color, 'error');
  assert.equal(taskStatus('interrupted').label, '已中断');
  assert.equal(taskStatus('mystery').label, '状态未知');
  assert.equal(taskProgress({ step_summary: { total: 4, completed: 2 } }).percent, 50);
  assert.equal(taskProgress({ step_summary: { total: 2, completed: 3 } }).percent, null);
});
test('read-only monitoring clients use existing Admin auth and encoded identifiers', async () => {
  const prior = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ success: true, data: { observed: true } }), { status: 200 });
  };
  try {
    await getKnowledgeCoverage('read-token');
    await getAgentTasks('read-token', { limit: 20, offset: 20 });
    await getAgentTask('read-token', 'id/with?separator');
    assert.ok(calls[0].url.endsWith('/admin/api/v1/knowledge/coverage'));
    assert.ok(calls[1].url.endsWith('/agent-tasks?limit=20&offset=20'));
    assert.ok(calls[2].url.endsWith('/agent-tasks/id%2Fwith%3Fseparator'));
    for (const call of calls) {
      assert.equal(call.options.method, 'GET');
      assert.equal(call.options.headers['X-Admin-Token'], 'read-token');
      assert.equal(call.options.headers['X-Admin-Workflow-Token'], undefined);
      assert.equal(call.options.body, undefined);
    }
  } finally { globalThis.fetch = prior; }
});
test('all prior management routes remain reachable beside shared theme and monitor', () => {
  const layout = readFileSync(new URL('./layouts/AdminLayout.jsx', import.meta.url), 'utf8');
  for (const path of ['knowledge', 'simulation-models', 'jobs', 'audit', 'config', 'actions', 'system', 'agent-tasks']) assert.ok(layout.includes(`/admin/${path}`));
  assert.ok(layout.includes('<ThemeSwitcher compact'));
  const app = readFileSync(new URL('./AdminApp.jsx', import.meta.url), 'utf8');
  assert.ok(!app.includes('ConfigProvider'));
});
test('knowledge list uses server pagination while upload and correction workflows remain', () => {
  const page = readFileSync(new URL('./pages/KnowledgePage.jsx', import.meta.url), 'utf8');
  assert.ok(page.includes('page_size: 20'));
  assert.ok(page.includes('total: documentTotal'));
  for (const capability of ['commitKnowledgeDocument', 'dryRunKnowledgeDocument', 'editStagedChunk', 'restoreStagedChunk', 'withdrawKnowledgeStaging', 'KnowledgeCoverage']) assert.ok(page.includes(capability));
});

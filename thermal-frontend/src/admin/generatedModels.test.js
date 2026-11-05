import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  approveGeneratedModel,
  compileGeneratedModel,
  createGeneratedModelRevision,
  deleteGeneratedModel,
  enableGeneratedModel,
  getGeneratedModels,
  promoteGeneratedModel,
  updateGeneratedModelMetadata,
} from './api/adminClient.js';
import { modelStatusPresentation, normalizeGeneratedModel } from './presentation/adminPresentation.js';


test('generated model presentation exposes topology summary without paths', () => {
  const item = normalizeGeneratedModel({
    generation_id: 'gen_0123456789abcdef0123456789abcdef',
    revision: 4,
    status: 'approved',
    display_name: '三支路稳态热网络',
    origin: 'llm_generated',
    retention: 'resident',
    description: '三条并联热阻与两个温度边界。',
    last_executed_at: '2026-09-01T01:02:03+00:00',
    use_count: 3,
    execution_eligible: false,
    validation_report: { valid: true },
    model_summary: {
      model_id: 'generated_thermal',
      component_count: 4,
      connection_count: 3,
      component_types: ['temperature_source', 'thermal_resistance'],
      components: [
        { id: 'hot', type: 'temperature_source', parameters: { temperature_k: { value: 365, unit: 'K' } } },
        { id: 'branch_1', type: 'thermal_resistance', parameters: { resistance_k_w: { value: 2, unit: 'K/W' } } },
        { id: 'branch_2', type: 'thermal_resistance', parameters: { resistance_k_w: { value: 4, unit: 'K/W' } } },
      ],
      topology: [
        { from_component: 'hot', from_port: 'A', to_component: 'branch_1', to_port: 'A' },
        { from_component: 'hot', from_port: 'A', to_component: 'branch_2', to_port: 'A' },
      ],
      requested_outputs: [
        { id: 'source_heat_flow', type: 'heat_flow', source_component_id: 'branch_1', source_port: 'A' },
      ],
    },
  });
  assert.equal(item.generationId.startsWith('gen_'), true);
  assert.equal(item.displayName, '三支路稳态热网络');
  assert.equal(item.originLabel, 'LLM 生成');
  assert.equal(item.retentionLabel, '常驻');
  assert.equal(item.useCount, 3);
  assert.equal(item.componentCount, 4);
  assert.equal(item.executionEligible, false);
  assert.equal(item.validationPassed, true);
  assert.equal(item.components.length, 3);
  assert.equal(item.topology.length, 2);
  assert.equal(item.requestedOutputs[0].sourcePort, undefined);
  assert.equal(item.requestedOutputs[0].source_port, 'A');
  assert.equal('path' in item, false);
  assert.equal(modelStatusPresentation('enabled').label, '已启用');
});


test('generated model client uses fixed workflow routes', async () => {
  const previousFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return { ok: true, status: 200, headers: { get: () => 'request-generated' }, json: async () => ({ success: true, data: { items: [] } }) };
  };
  try {
    const id = 'gen_0123456789abcdef0123456789abcdef';
    await getGeneratedModels('reader');
    await compileGeneratedModel('reader', 'writer', id);
    await approveGeneratedModel('reader', 'writer', id, 'reviewed');
    await enableGeneratedModel('reader', 'writer', id);
    await updateGeneratedModelMetadata('reader', 'writer', id, { display_name: '热网络' });
    await createGeneratedModelRevision('reader', 'writer', id, { model_ir: {}, reason: 'edit' });
    await promoteGeneratedModel('reader', 'writer', id);
    await deleteGeneratedModel('reader', 'writer', id, 'cleanup');
  } finally {
    globalThis.fetch = previousFetch;
  }
  assert.deepEqual(calls.map(call => call.url.replace(/^.*\/admin\/api\/v1/, '')), [
    '/generated-models',
    '/generated-models/gen_0123456789abcdef0123456789abcdef/compile',
    '/generated-models/gen_0123456789abcdef0123456789abcdef/approve',
    '/generated-models/gen_0123456789abcdef0123456789abcdef/enable',
    '/generated-models/gen_0123456789abcdef0123456789abcdef/metadata',
    '/generated-models/gen_0123456789abcdef0123456789abcdef/revisions',
    '/generated-models/gen_0123456789abcdef0123456789abcdef/promote',
    '/generated-models/gen_0123456789abcdef0123456789abcdef',
  ]);
  assert.equal(calls.slice(1).every(call => call.options.headers['X-Admin-Workflow-Token'] === 'writer'), true);
});


test('generated model Admin UI is name-first and exposes lifecycle controls', () => {
  const source = readFileSync(new URL('./pages/SimulationModelsPage.jsx', import.meta.url), 'utf8');
  for (const text of ['模型名称', '来源 / 保留', '最近使用', '编辑信息', '工程修订', '转为常驻', '删除', '按名称、ID 或摘要搜索']) {
    assert.match(source, new RegExp(text));
  }
  assert.match(source, /只接受结构化 Model IR/);
  assert.match(source, /不会继承批准/);
  assert.doesNotMatch(source, /artifact_path|filesystem_path|absolute_path/);
});

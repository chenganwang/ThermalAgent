import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildScenarioResultViewModel,
  canRunScenario,
  collectionFromPayload,
  initialValuesFromSchema,
  planReady,
  prepareScenarioParams,
  supportedModelIds,
} from './scenarioForm.js';

test('场景和模型列表兼容直接数组与包装响应', () => {
  assert.deepEqual(collectionFromPayload([{ scenario_id: 's1' }], ['scenarios']), [{ scenario_id: 's1' }]);
  assert.deepEqual(collectionFromPayload({ scenarios: [{ scenario_id: 's1' }] }, ['scenarios']), [{ scenario_id: 's1' }]);
  assert.deepEqual(collectionFromPayload(null, ['scenarios']), []);
});

test('只从后端 supported_models 提取模型 ID', () => {
  assert.deepEqual(supportedModelIds({ supported_models: ['model-a', { model_id: 'model-b' }] }), ['model-a', 'model-b']);
});

test('动态 schema 默认值与数组对象参数可解析', () => {
  const schema = [
    { name: 'area_m2', type: 'number', default: 2 },
    { name: 'layers', type: 'array', default: [{ thickness_m: 0.01 }] },
    { name: 'options', type: 'object' },
  ];
  const values = initialValuesFromSchema(schema);
  assert.equal(values.area_m2, 2);
  assert.match(values.layers, /thickness_m/);
  const prepared = prepareScenarioParams(schema, { ...values, options: '{"mode":"safe"}' });
  assert.equal(prepared.success, true);
  assert.deepEqual(prepared.params.layers, [{ thickness_m: 0.01 }]);
  assert.deepEqual(prepared.params.options, { mode: 'safe' });
});

test('非法 array JSON 在调用 plan 前拒绝', () => {
  const prepared = prepareScenarioParams([{ name: 'layers', type: 'array' }], { layers: '{"not":"array"}' });
  assert.equal(prepared.success, false);
  assert.match(prepared.errors.layers, /JSON 数组/);
});

test('plan ready 同时需要 capability、available 模型和 execution_allowed', () => {
  const base = {
    plan: { ready: true, execution_allowed: true },
    capabilityEnabled: true,
    scenario: { status: 'available' },
    model: { status: 'available', execution_mode: 'controlled_function' },
  };
  assert.equal(planReady(base.plan), true);
  assert.equal(canRunScenario(base), true);
  assert.equal(canRunScenario({ ...base, capabilityEnabled: false }), false);
  assert.equal(canRunScenario({ ...base, plan: { ready: false, execution_allowed: true } }), false);
  assert.equal(canRunScenario({ ...base, plan: { ready: true, execution_allowed: true, solver_guard_passed: false } }), false);
  assert.equal(canRunScenario({ ...base, model: { status: 'preparation_only' } }), false);
  assert.equal(canRunScenario({ ...base, model: { status: 'available', execution_mode: 'preparation_only' } }), false);
  assert.equal(canRunScenario({ ...base, model: { status: 'available', registration_type: 'user_uploaded_unvalidated' } }), false);
  assert.equal(canRunScenario({ ...base, useMockResponses: true }), false);
});

test('后端 status ready/executable 计划形态可执行', () => {
  const allowed = canRunScenario({
    plan: { status: 'ready', executable: true },
    capabilityEnabled: true,
    scenario: { status: 'available' },
    model: { status: 'available' },
  });
  assert.equal(allowed, true);
});

test('通用结果卡保留明确 K 单位、MATLAB、耗时和证据 ID', () => {
  const view = buildScenarioResultViewModel({
    success: true,
    status: 'success',
    scenario: { scenario_id: 'plane_wall_steady_conduction', display_name: '一维平壁稳态导热' },
    model: { model_id: 'registered-model', display_name: 'MATLAB 模型', backend: 'matlab', human_validated: false },
    outputs: { temperature_difference_k: 60, heat_rate_w: 1920 },
    units: { temperature_difference_k: 'K', heat_rate_w: 'W' },
    duration_ms: 1250,
    evidence: { evidence_id: 'evidence-7d' },
    assumptions: ['One-dimensional steady conduction.'],
  }, [
    { name: 'temperature_difference_k', label_zh: '温差', unit: 'K' },
    { name: 'heat_rate_w', label_zh: '热流率', unit: 'W' },
  ]);
  assert.equal(view.solver, 'MATLAB');
  assert.equal(view.duration_display, '1.25 秒');
  assert.equal(view.evidence_id, 'evidence-7d');
  assert.equal(view.human_review_label, '尚未复核');
  assert.deepEqual(view.assumptions, ['采用一维稳态导热假设。']);
  assert.deepEqual(view.output_items.map(item => item.display), ['60 K', '1920 W']);
  assert.doesNotMatch(view.detail_json, /evidence_path/);
});

test('温差响应未给出单位时不由前端猜测 K', () => {
  const view = buildScenarioResultViewModel({
    success: true,
    outputs: { temperature_difference_k: 60 },
    units: {},
  });
  assert.equal(view.output_items[0].display, '60');
});

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildHeatConductionPayload,
  buildHeatConductionResultViewModel,
  formatDurationMs,
  formatTemperatureDifferenceK,
  parseHeatConductionText,
  safeSimulationError,
  validateHeatConductionParams,
} from './simulationForm.js';

const STANDARD_PARAMS = {
  length_m: 0.05,
  thermal_conductivity_w_mk: 0.8,
  area_m2: 2,
  t_hot_c: 100,
  t_cold_c: 40,
};

test('标准平壁问题解析为一维导热参数', () => {
  const parsed = parseHeatConductionText(
    '一块平壁厚度为0.05 m，导热系数为0.8 W/(m·K)，传热面积为2 m²，热端温度为100℃，冷端温度为40℃。',
  );
  assert.deepEqual(parsed.values, STANDARD_PARAMS);
  assert.deepEqual(parsed.missing_parameters, []);
});

test('导热系数三种完整单位都映射到 thermal_conductivity_w_mk', () => {
  for (const unit of ['W/(m·K)', 'W/(m*K)', 'W/mK']) {
    const parsed = parseHeatConductionText(`导热系数为0.8 ${unit}`);
    assert.equal(parsed.values.thermal_conductivity_w_mk, 0.8);
    assert.equal(Object.hasOwn(parsed.values, 'heat_source_power'), false);
  }
});

test('符号形式 L k A T_hot T_cold 可解析', () => {
  const parsed = parseHeatConductionText('L=0.05 m; k=0.8 W/mK; A=2 m2; T_hot=100 C; T_cold=40 C');
  assert.deepEqual(parsed.values, STANDARD_PARAMS);
});

test('厚度 50 mm 统一换算为 0.05 m', () => {
  const parsed = parseHeatConductionText('厚度为50 mm');
  assert.equal(parsed.values.length_m, 0.05);
});

test('温度允许负值', () => {
  const parsed = parseHeatConductionText('热端温度为10℃，冷端温度为-20°C');
  assert.equal(parsed.values.t_hot_c, 10);
  assert.equal(parsed.values.t_cold_c, -20);
});

test('缺少面积时报告 missing_parameters 且不构造请求', () => {
  const { area_m2: _area, ...withoutArea } = STANDARD_PARAMS;
  const result = buildHeatConductionPayload(withoutArea);
  assert.equal(result.success, false);
  assert.deepEqual(result.missing_parameters, ['area_m2']);
  assert.equal(result.payload, null);
});

test('非正厚度、面积和导热系数拒绝执行', () => {
  for (const key of ['length_m', 'area_m2', 'thermal_conductivity_w_mk']) {
    const validation = validateHeatConductionParams({ ...STANDARD_PARAMS, [key]: 0 });
    assert.equal(validation.success, false);
    assert.deepEqual(validation.invalid_parameters, [key]);
  }
});

test('有效表单构造精确 MATLAB demo 请求', () => {
  const result = buildHeatConductionPayload(STANDARD_PARAMS);
  assert.equal(result.success, true);
  assert.deepEqual(result.payload, {
    demo_name: 'heat_conduction_1d',
    params: STANDARD_PARAMS,
  });
});

test('结果视图模型提取 60 K、1920 W 和 evidence', () => {
  const raw = {
    success: true,
    status: 'success',
    demo_name: 'heat_conduction_1d',
    inputs: STANDARD_PARAMS,
    outputs: { heat_rate_w: 1920, temperature_difference_k: 60 },
    units: { heat_rate_w: 'W', temperature_difference_k: 'K' },
    engine_type: 'Matlab',
    is_real_matlab: true,
    human_validated: false,
    evidence_id: 'evidence-1',
    duration_ms: 40289,
    assumptions: [
      'One-dimensional steady conduction.',
      'No contact resistance, radiation, convection, or transient storage is included.',
      'This is a controlled demo path, not a production validated model.',
    ],
  };
  const view = buildHeatConductionResultViewModel(raw);
  assert.equal(view.temperature_difference_k, 60);
  assert.equal(view.temperature_difference_display, '60 K');
  assert.equal(view.heat_rate_w, 1920);
  assert.equal(view.evidence_id, 'evidence-1');
  assert.equal(view.engine_label, 'MATLAB');
  assert.equal(view.human_review_label, '尚未复核');
  assert.equal(view.duration_display, '40.29 秒');
  assert.deepEqual(view.assumptions_zh, [
    '采用一维稳态导热假设。',
    '不包含接触热阻、辐射、对流或瞬态蓄热。',
    '这是受控演示流程，不是经过生产验证的工程模型。',
  ]);
  assert.equal(view.formula_lines[2], 'Q̇ = 1920 W');
  assert.match(view.detail_json, /"heat_rate_w": 1920/);
});

test('温差只接受后端显式 K 单位且不会映射成长度单位', () => {
  assert.equal(formatTemperatureDifferenceK(60, 'K'), '60 K');
  assert.equal(formatTemperatureDifferenceK(60, 'km'), '—');
  assert.equal(formatTemperatureDifferenceK(60, undefined), '—');
  const withoutBackendTemperatureDifference = buildHeatConductionResultViewModel({
    success: true,
    inputs: STANDARD_PARAMS,
    outputs: { heat_rate_w: 1920 },
    units: { heat_rate_w: 'W' },
  });
  assert.equal(withoutBackendTemperatureDifference.temperature_difference_k, null);
  assert.equal(withoutBackendTemperatureDifference.temperature_difference_display, '—');
});

test('运行耗时按毫秒或秒显示', () => {
  assert.equal(formatDurationMs(825), '825 毫秒');
  assert.equal(formatDurationMs(1500), '1.5 秒');
});

test('结构化 FastAPI 错误转为用户可读 guard 原因', () => {
  const error = {
    payload: {
      detail: {
        status: 'license_not_confirmed',
        error: { code: 'matlab_license_not_confirmed', message: 'Operator confirmation required.' },
      },
    },
  };
  assert.match(safeSimulationError(error), /^MATLAB guard 未通过/);
  assert.doesNotMatch(safeSimulationError(error), /\[object Object\]/);
});

test('普通网络错误不暴露对象字符串', () => {
  assert.equal(safeSimulationError(new Error('Failed to fetch')), '请求失败：Failed to fetch');
  assert.equal(safeSimulationError({ message: '[object Object]' }), '请求失败，请检查后端连接和功能状态。');
});

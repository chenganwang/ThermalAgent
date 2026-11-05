export const HEAT_CONDUCTION_DEMO_NAME = 'heat_conduction_1d';

export const HEAT_CONDUCTION_FIELDS = Object.freeze([
  Object.freeze({ key: 'length_m', label: '平壁厚度', unit: 'm', positive: true }),
  Object.freeze({ key: 'thermal_conductivity_w_mk', label: '导热系数', unit: 'W/(m·K)', positive: true }),
  Object.freeze({ key: 'area_m2', label: '传热面积', unit: 'm²', positive: true }),
  Object.freeze({ key: 't_hot_c', label: '热端温度', unit: '℃', positive: false }),
  Object.freeze({ key: 't_cold_c', label: '冷端温度', unit: '℃', positive: false }),
]);

export const EMPTY_HEAT_CONDUCTION_PARAMS = Object.freeze(
  Object.fromEntries(HEAT_CONDUCTION_FIELDS.map(field => [field.key, null])),
);

const NUMBER_PATTERN = '([-+]?\\d+(?:\\.\\d+)?)';

const ASSUMPTION_TRANSLATIONS = Object.freeze({
  'One-dimensional steady conduction.': '采用一维稳态导热假设。',
  'No contact resistance, radiation, convection, or transient storage is included.': '不包含接触热阻、辐射、对流或瞬态蓄热。',
  'This is a controlled demo path, not a production validated model.': '这是受控演示流程，不是经过生产验证的工程模型。',
});

const PARAMETER_PATTERNS = Object.freeze({
  length_m: new RegExp(
    `(?:平壁厚度|厚度|length(?:_m)?|\\bL\\b)\\s*(?:=|:|：|为|是)?\\s*${NUMBER_PATTERN}\\s*(mm|m)?`,
    'i',
  ),
  thermal_conductivity_w_mk: new RegExp(
    `(?:导热系数|热导率|thermal\\s+conductivity|thermal_conductivity_w_mk|\\bk\\b)\\s*(?:=|:|：|为|是)?\\s*${NUMBER_PATTERN}(?:\\s*W\\s*(?:\\/\\s*(?:\\(\\s*m\\s*(?:[·*]\\s*)?K\\s*\\)|m\\s*K)|\\/\\s*mK))?`,
    'i',
  ),
  area_m2: new RegExp(
    `(?:传热面积|面积|area(?:_m2)?|\\bA\\b)\\s*(?:=|:|：|为|是)?\\s*${NUMBER_PATTERN}\\s*(?:m(?:²|2))?`,
    'i',
  ),
  t_hot_c: new RegExp(
    `(?:热端(?:温度)?|hot(?:\\s+(?:side|temperature))?|t_hot(?:_c)?)\\s*(?:=|:|：|为|是)?\\s*${NUMBER_PATTERN}\\s*(?:℃|°\\s*C|degC|C)?`,
    'i',
  ),
  t_cold_c: new RegExp(
    `(?:冷端(?:温度)?|cold(?:\\s+(?:side|temperature))?|t_cold(?:_c)?)\\s*(?:=|:|：|为|是)?\\s*${NUMBER_PATTERN}\\s*(?:℃|°\\s*C|degC|C)?`,
    'i',
  ),
});

function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const normalized = typeof value === 'string' ? value.trim() : value;
  if (normalized === '') return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

export function parseHeatConductionText(text) {
  const input = String(text || '').replaceAll('，', ',').replaceAll('；', ';');
  const values = {};

  for (const field of HEAT_CONDUCTION_FIELDS) {
    const match = PARAMETER_PATTERNS[field.key].exec(input);
    if (!match) continue;
    let value = Number(match[1]);
    if (field.key === 'length_m' && String(match[2] || '').toLowerCase() === 'mm') value /= 1000;
    values[field.key] = value;
  }

  const missingParameters = HEAT_CONDUCTION_FIELDS
    .map(field => field.key)
    .filter(key => values[key] === undefined);
  return {
    values,
    matched_parameters: Object.keys(values),
    missing_parameters: missingParameters,
  };
}

export function validateHeatConductionParams(values = {}) {
  const params = {};
  const missingParameters = [];
  const invalidParameters = [];

  for (const field of HEAT_CONDUCTION_FIELDS) {
    const value = finiteNumber(values[field.key]);
    if (value === null) {
      missingParameters.push(field.key);
      continue;
    }
    if (!Number.isFinite(value) || (field.positive && value <= 0)) {
      invalidParameters.push(field.key);
      continue;
    }
    params[field.key] = value;
  }

  return {
    success: missingParameters.length === 0 && invalidParameters.length === 0,
    params,
    missing_parameters: missingParameters,
    invalid_parameters: invalidParameters,
  };
}

export function buildHeatConductionPayload(values = {}) {
  const validation = validateHeatConductionParams(values);
  return {
    ...validation,
    payload: validation.success
      ? { demo_name: HEAT_CONDUCTION_DEMO_NAME, params: validation.params }
      : null,
  };
}

function displayNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return Number.isInteger(number) ? String(number) : String(Number(number.toPrecision(12)));
}

export function formatTemperatureDifferenceK(value, unit) {
  const number = finiteNumber(value);
  if (!Number.isFinite(number) || unit !== 'K') return '—';
  return `${number.toLocaleString('zh-CN')} K`;
}

export function formatDurationMs(value) {
  const duration = finiteNumber(value);
  if (!Number.isFinite(duration) || duration < 0) return '—';
  if (duration < 1000) return `${Math.round(duration).toLocaleString('zh-CN')} 毫秒`;
  const seconds = Number((duration / 1000).toFixed(2));
  return `${seconds.toLocaleString('zh-CN')} 秒`;
}

function engineLabel(value) {
  const engine = String(value || 'none');
  return engine.toLowerCase() === 'matlab' ? 'MATLAB' : engine;
}

function translateAssumption(value) {
  const assumption = String(value || '').trim();
  if (!assumption) return null;
  return ASSUMPTION_TRANSLATIONS[assumption]
    || '存在未提供中文说明的附加假设，请在详细数据中核对。';
}

export function buildHeatConductionResultViewModel(raw = {}) {
  const inputs = raw.inputs && typeof raw.inputs === 'object' ? raw.inputs : {};
  const outputs = raw.outputs && typeof raw.outputs === 'object' ? raw.outputs : {};
  const units = raw.units && typeof raw.units === 'object' ? raw.units : {};
  const temperatureDifference = finiteNumber(outputs.temperature_difference_k);
  const heatRate = finiteNumber(outputs.heat_rate_w);
  const k = displayNumber(inputs.thermal_conductivity_w_mk);
  const area = displayNumber(inputs.area_m2);
  const length = displayNumber(inputs.length_m);
  const hot = displayNumber(inputs.t_hot_c);
  const cold = displayNumber(inputs.t_cold_c);

  return {
    success: raw.success === true,
    status: String(raw.status || (raw.success ? 'success' : 'failed')),
    demo_name: String(raw.demo_name || HEAT_CONDUCTION_DEMO_NAME),
    temperature_difference_k: Number.isFinite(temperatureDifference) ? temperatureDifference : null,
    temperature_difference_display: formatTemperatureDifferenceK(
      temperatureDifference,
      units.temperature_difference_k,
    ),
    heat_rate_w: Number.isFinite(heatRate) ? heatRate : null,
    engine_type: String(raw.engine_type || 'none'),
    engine_label: engineLabel(raw.engine_type),
    is_real_matlab: raw.is_real_matlab === true,
    human_validated: raw.human_validated === true,
    human_review_label: raw.human_validated === true ? '已复核' : '尚未复核',
    matlab_version: raw.matlab_version || null,
    evidence_id: raw.evidence_id || null,
    duration_ms: Number.isFinite(finiteNumber(raw.duration_ms)) ? finiteNumber(raw.duration_ms) : null,
    duration_display: formatDurationMs(raw.duration_ms),
    assumptions_zh: Array.isArray(raw.assumptions)
      ? raw.assumptions.map(translateAssumption).filter(Boolean)
      : [],
    formula_lines: [
      'Q̇ = kA(T_hot - T_cold) / L',
      `Q̇ = ${k} × ${area} × (${hot} - ${cold}) / ${length}`,
      `Q̇ = ${displayNumber(heatRate)} W`,
    ],
    detail_json: JSON.stringify(raw, null, 2),
  };
}

function errorDetail(error) {
  const payload = error?.detail ?? error?.payload?.detail ?? error?.payload;
  return payload && typeof payload === 'object' ? payload : {};
}

export function safeSimulationError(error) {
  const detail = errorDetail(error);
  const status = String(detail.status || error?.statusCode || '').toLowerCase();
  const code = String(detail.error?.code || detail.code || '').toLowerCase();
  const backendMessage = detail.error?.message || detail.message;

  if (status === 'disabled' || code.includes('disabled')) return '功能未启用，后端已拒绝执行。';
  if (
    ['not_configured', 'license_not_confirmed', 'engine_not_installed'].includes(status)
    || code.includes('license')
    || code.includes('engine_start')
  ) {
    return `MATLAB guard 未通过${backendMessage ? `：${backendMessage}` : '。'}`;
  }
  if (code.includes('missing') || status === 'missing_parameters') {
    return `参数缺失${backendMessage ? `：${backendMessage}` : '。'}`;
  }
  if (code.includes('validation') || code.includes('invalid') || status === 'invalid_parameters') {
    return `参数非法${backendMessage ? `：${backendMessage}` : '。'}`;
  }
  if (code.includes('execution') || status === 'failed') {
    return `MATLAB 启动或执行失败${backendMessage ? `：${backendMessage}` : '。'}`;
  }

  const message = typeof error?.message === 'string' ? error.message.trim() : '';
  if (message && message !== '[object Object]') return `请求失败：${message}`;
  return '请求失败，请检查后端连接和功能状态。';
}

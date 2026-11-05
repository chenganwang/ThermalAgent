const BLOCKED_MODEL_STATUSES = new Set([
  'unavailable',
  'preparation_only',
  'planned',
  'experimental',
  'deprecated',
  'blocked',
  'unvalidated',
]);

const BLOCKED_EXECUTION_MODES = new Set(['preparation_only', 'unavailable', 'planned']);

const ASSUMPTION_TRANSLATIONS = Object.freeze({
  'One-dimensional steady conduction.': '采用一维稳态导热假设。',
  'No contact resistance, radiation, convection, or transient storage is included.': '不包含接触热阻、辐射、对流或瞬态蓄热。',
  'This is a controlled demo path, not a production validated model.': '这是受控演示流程，不是经过生产验证的工程模型。',
});

export function collectionFromPayload(payload, keys) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== 'object') return [];
  for (const key of keys) {
    if (Array.isArray(payload[key])) return payload[key];
  }
  return [];
}

export function entityFromPayload(payload, key) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  const nested = payload[key];
  return nested && typeof nested === 'object' && !Array.isArray(nested) ? nested : payload;
}

export function scenarioId(scenario) {
  return String(scenario?.scenario_id || scenario?.id || '');
}

export function scenarioName(scenario) {
  return String(
    scenario?.name_zh
      || scenario?.display_name
      || scenario?.name
      || scenario?.name_en
      || scenarioId(scenario)
      || '未命名场景',
  );
}

export function scenarioDomain(scenario) {
  return String(scenario?.domain || scenario?.category || 'other');
}

export function modelId(model) {
  return String(model?.model_id || model?.id || '');
}

export function modelName(model) {
  return String(model?.name_zh || model?.display_name || model?.name || modelId(model) || '未命名模型');
}

export function modelSolver(model) {
  return String(model?.solver || model?.backend || model?.executor?.solver || '—');
}

export function inputSchemaOf(scenario) {
  return Array.isArray(scenario?.input_schema) ? scenario.input_schema : [];
}

export function outputSchemaOf(scenario) {
  return Array.isArray(scenario?.output_schema) ? scenario.output_schema : [];
}

export function supportedModelIds(scenario) {
  const values = scenario?.supported_models || scenario?.model_ids || [];
  if (!Array.isArray(values)) return [];
  return values.map(value => (typeof value === 'string' ? value : modelId(value))).filter(Boolean);
}

export function initialValuesFromSchema(inputSchema = []) {
  return Object.fromEntries(inputSchema.map(field => {
    const value = field.default ?? field.default_value ?? field.example ?? null;
    if ((field.type === 'array' || field.type === 'object') && value !== null && typeof value !== 'string') {
      return [field.name, JSON.stringify(value, null, 2)];
    }
    return [field.name, value];
  }));
}

function parseJsonField(value, expectedType) {
  if (expectedType === 'array' && Array.isArray(value)) return value;
  if (expectedType === 'object' && value && typeof value === 'object' && !Array.isArray(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return value;
  const parsed = JSON.parse(value);
  if (expectedType === 'array' && !Array.isArray(parsed)) throw new Error('必须是 JSON 数组');
  if (expectedType === 'object' && (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))) {
    throw new Error('必须是 JSON 对象');
  }
  return parsed;
}

export function prepareScenarioParams(inputSchema = [], values = {}) {
  const params = {};
  const errors = {};

  for (const field of inputSchema) {
    const value = values[field.name];
    if (value === null || value === undefined || value === '') continue;
    try {
      if (field.type === 'array' || field.type === 'object') {
        params[field.name] = parseJsonField(value, field.type);
      } else {
        params[field.name] = value;
      }
    } catch (error) {
      errors[field.name] = error.message;
    }
  }

  return { success: Object.keys(errors).length === 0, params, errors };
}

export function planReady(plan) {
  if (!plan || typeof plan !== 'object') return false;
  if (typeof plan.ready === 'boolean') return plan.ready;
  if (plan.status !== 'ready') return false;
  if (typeof plan.executable === 'boolean') return plan.executable;
  return true;
}

export function planExecutionAllowed(plan) {
  if (!plan || typeof plan !== 'object') return false;
  if (plan.feature_enabled === false || plan.solver_guard_passed === false) return false;
  if (['unavailable', 'preparation_only', 'blocked'].includes(String(plan.executor_status || '').toLowerCase())) return false;
  if (typeof plan.execution_allowed === 'boolean') return plan.execution_allowed;
  if (typeof plan.executable === 'boolean') return plan.executable;
  return false;
}

export function missingPlanParameters(plan) {
  if (Array.isArray(plan?.missing_parameters)) return plan.missing_parameters;
  if (Array.isArray(plan?.validation?.missing_fields)) return plan.validation.missing_fields;
  return [];
}

export function normalizedPlanParams(plan) {
  return plan?.normalized_params || plan?.inputs || {};
}

export function canRunScenario({ plan, capabilityEnabled, scenario, model, useMockResponses = false }) {
  if (!capabilityEnabled || useMockResponses || !planReady(plan) || !planExecutionAllowed(plan)) return false;
  if (String(scenario?.status || '').toLowerCase() !== 'available') return false;
  if (String(model?.status || '').toLowerCase() !== 'available') return false;
  if (BLOCKED_EXECUTION_MODES.has(String(model?.execution_mode || '').toLowerCase())) return false;
  if (BLOCKED_MODEL_STATUSES.has(String(model?.status || '').toLowerCase())) return false;
  if (String(model?.registration_type || '').toLowerCase() === 'user_uploaded_unvalidated') return false;
  return true;
}

function finiteNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatDurationMs(value) {
  const duration = finiteNumber(value);
  if (duration === null || duration < 0) return '—';
  if (duration < 1000) return `${Math.round(duration).toLocaleString('zh-CN')} 毫秒`;
  return `${Number((duration / 1000).toFixed(2)).toLocaleString('zh-CN')} 秒`;
}

function displayValue(value, unit) {
  if (value === null || value === undefined) return '—';
  if (Array.isArray(value) || (typeof value === 'object' && value !== null)) return JSON.stringify(value);
  const normalizedUnit = typeof unit === 'string' ? unit.trim() : '';
  return normalizedUnit ? `${value} ${normalizedUnit}` : String(value);
}

function localizeAssumption(value) {
  const assumption = String(value || '').trim();
  if (!assumption) return null;
  if (ASSUMPTION_TRANSLATIONS[assumption]) return ASSUMPTION_TRANSLATIONS[assumption];
  if (/[㐀-鿿]/u.test(assumption)) return assumption;
  return '存在未提供中文说明的附加假设，请在详细数据中核对。';
}

export function buildScenarioResultViewModel(result = {}, outputSchema = []) {
  const scenario = typeof result.scenario === 'object' ? result.scenario : {};
  const model = typeof result.model === 'object' ? result.model : {};
  const evidence = typeof result.evidence === 'object' ? result.evidence : {};
  const outputs = result.outputs && typeof result.outputs === 'object' ? result.outputs : {};
  const units = result.units && typeof result.units === 'object' ? result.units : {};
  const labels = Object.fromEntries(outputSchema.map(field => [field.name, field.label_zh || field.label || field.name]));
  const orderedNames = [
    ...outputSchema.map(field => field.name).filter(name => Object.hasOwn(outputs, name)),
    ...Object.keys(outputs).filter(name => !outputSchema.some(field => field.name === name)),
  ];

  return {
    success: result.success === true,
    status: String(result.status || (result.success ? 'success' : 'failed')),
    scenario_id: String(scenario.scenario_id || result.scenario_id || result.scenario || ''),
    scenario_name: String(scenario.name_zh || scenario.display_name || scenario.name || scenario.scenario_id || result.scenario_id || '—'),
    model_id: String(model.model_id || result.model_id || result.model || ''),
    model_name: String(model.name_zh || model.display_name || model.name || model.model_id || result.model_id || '—'),
    solver: String(result.solver || model.solver || model.backend || result.executor?.solver || result.executor?.executor_id || '—')
      .replace(/^matlab$/i, 'MATLAB'),
    duration_display: formatDurationMs(result.duration_ms),
    evidence_id: String(result.evidence_id || evidence.evidence_id || ''),
    human_review_label: (result.human_validated ?? evidence.human_validated ?? model.human_validated) === true
      ? '已复核'
      : '尚未复核',
    output_items: orderedNames.map(name => ({
      name,
      label: labels[name] || name,
      value: outputs[name],
      unit: units[name] || '',
      display: displayValue(outputs[name], units[name]),
    })),
    assumptions: Array.isArray(result.assumptions)
      ? result.assumptions.map(localizeAssumption).filter(Boolean)
      : [],
    warnings: Array.isArray(result.warnings) ? result.warnings : [],
    formula: Array.isArray(result.formula) ? result.formula : result.formula ? [String(result.formula)] : [],
    detail_json: JSON.stringify(result, null, 2),
  };
}

const DANGEROUS_FIELDS = new Set([
  'command', 'cmd', 'shell', 'powershell', 'sql', 'query_sql', 'query', 'python', 'code', 'script',
  'module_path', 'handler', 'function', 'class', 'import', 'path', 'file_path', 'directory', 'executable', 'url',
]);

export const RISK_META = Object.freeze({
  low: { label: '低', color: 'success' },
  medium: { label: '中', color: 'warning' },
  high: { label: '高', color: 'error' },
  critical: { label: '关键', color: 'error' },
});

export function riskMeta(riskLevel) {
  return RISK_META[riskLevel] || { label: String(riskLevel || '未知'), color: 'default' };
}

export function normalizeActionDescriptor(value = {}) {
  return {
    action_id: String(value.action_id || ''),
    name: String(value.name || value.action_id || '未命名操作'),
    description: String(value.description || ''),
    category: String(value.category || 'unknown'),
    risk_level: String(value.risk_level || 'unknown'),
    read_only: value.read_only === true,
    side_effects: Array.isArray(value.side_effects) ? [...value.side_effects] : [],
    supports_dry_run: value.supports_dry_run === true,
    execution_mode: String(value.execution_mode || 'unknown'),
    required_permission: String(value.required_permission || ''),
    timeout_seconds: Number(value.timeout_seconds || 0),
    concurrency_limit: Number(value.concurrency_limit || 0),
    enabled: value.enabled === true,
    available: value.available === true,
    availability_reason: value.availability_reason ? String(value.availability_reason) : null,
    parameter_schema: value.parameter_schema && typeof value.parameter_schema === 'object'
      ? value.parameter_schema
      : { type: 'object', properties: {}, additionalProperties: false },
    result_schema_version: String(value.result_schema_version || 'unknown'),
  };
}

export function defaultActionParameters(action) {
  const properties = action?.parameter_schema?.properties || {};
  return Object.fromEntries(Object.entries(properties).flatMap(([key, schema]) => (
    Object.hasOwn(schema, 'default') ? [[key, schema.default]] : []
  )));
}

export function buildActionRequest(action, values = {}) {
  const schema = action?.parameter_schema || {};
  const properties = schema.properties || {};
  const required = new Set(schema.required || []);
  const normalized = {};
  for (const [rawKey, rawValue] of Object.entries(values || {})) {
    const key = String(rawKey).trim();
    const normalizedKey = key.toLowerCase().replaceAll('-', '_');
    if (DANGEROUS_FIELDS.has(normalizedKey) || normalizedKey.endsWith('_path')) {
      throw new Error('参数包含禁止字段。');
    }
    if (!Object.hasOwn(properties, key)) {
      if (schema.additionalProperties === false) throw new Error(`未声明参数：${key}`);
      continue;
    }
    if (rawValue === undefined || rawValue === '') continue;
    normalized[key] = normalizeValue(rawValue, properties[key]);
  }
  for (const key of required) {
    if (!Object.hasOwn(normalized, key)) throw new Error(`缺少必填参数：${key}`);
  }
  return { parameters: normalized };
}

function normalizeValue(value, schema = {}) {
  if (Array.isArray(schema.enum) && !schema.enum.includes(value)) throw new Error('参数值不在允许范围内。');
  if (schema.type === 'boolean') {
    if (typeof value !== 'boolean') throw new Error('参数必须是布尔值。');
    return value;
  }
  if (schema.type === 'integer') {
    const number = Number(value);
    if (!Number.isInteger(number)) throw new Error('参数必须是整数。');
    return number;
  }
  if (schema.type === 'number') {
    const number = Number(value);
    if (!Number.isFinite(number)) throw new Error('参数必须是有限数值。');
    return number;
  }
  if (schema.type === 'string') return String(value);
  return value;
}

export function hasActionPermission(permissions, permission) {
  return Array.isArray(permissions) && permissions.includes(permission);
}

export function canDryRunAction(action, permissions) {
  return Boolean(
    action?.enabled
    && action?.available
    && action?.supports_dry_run
    && hasActionPermission(permissions, 'action.dry_run'),
  );
}

export function canInvokeAction(action, dryRun, permissions) {
  return Boolean(
    action?.risk_level === 'low'
    && action?.read_only === true
    && Array.isArray(action?.side_effects)
    && action.side_effects.length === 0
    && action?.execution_mode === 'synchronous'
    && dryRun?.allowed === true
    && hasActionPermission(permissions, action?.required_permission),
  );
}

export function actionResultView(result) {
  if (!result) return null;
  const summary = result.result_summary || {};
  return {
    status: String(result.status || 'failed'),
    durationMs: Number(result.duration_ms || 0),
    invocationId: String(result.invocation_id || ''),
    summary: summary.summary || {},
    metrics: summary.metrics || {},
    details: summary.details || {},
    warnings: Array.isArray(result.warnings) ? result.warnings : [],
  };
}

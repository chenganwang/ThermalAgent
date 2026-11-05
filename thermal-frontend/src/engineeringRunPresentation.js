const RUN_STATUSES = {
  planned: { label: '已建立计划', color: 'blue' },
  running: { label: '执行中', color: 'processing' },
  pending: { label: '待执行', color: 'default' },
  completed: { label: '执行完成', color: 'blue' },
  blocked: { label: '等待补充条件', color: 'warning' },
  failed: { label: '执行失败', color: 'error' },
  incomplete: { label: '记录不完整', color: 'warning' },
};

const STEP_STATUSES = {
  planned: '已规划', pending: '待执行', running: '执行中', completed: '已完成', blocked: '受阻',
  failed: '失败', skipped: '已跳过', incomplete: '未完成',
};

export function engineeringValue(value) {
  if (value === null || value === undefined) return '未提供';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '无有效数值';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value); } catch { return '无法显示'; }
}

export function engineeringRunPresentation(response) {
  const run = response?.metadata?.engineering_run;
  const knownContract = run && ((run.schema_version === '1.0' && run.scope === 'deterministic_calculation') || (run.schema_version === '1.1' && run.scope === 'reference_calculation'));
  if (!knownContract) return null;
  const text = value => typeof value === 'string' ? value : null;
  const strings = values => Array.isArray(values) ? values.filter(value => typeof value === 'string') : [];
  const steps = (Array.isArray(run.steps) ? run.steps : []).filter(step => step && typeof step === 'object')
    .map(step => ({ step_id: text(step.step_id), title: text(step.title), depends_on: strings(step.depends_on), status: text(step.status), error: typeof step.error === 'string' ? step.error : text(step.error?.message) }));
  const variables = (Array.isArray(run.variables) ? run.variables : []).filter(variable => variable && ['input', 'output'].includes(variable.role))
    .map(variable => ({ name: text(variable.name), value: variable.value ?? null, unit: text(variable.unit), role: variable.role, source: text(variable.source), step_id: text(variable.step_id) }));
  const validation = run.validation && typeof run.validation === 'object' ? run.validation : {};
  const checked = validation.status === 'passed' && validation.passed === true;
  const failed = validation.status === 'failed';
  const checks = (Array.isArray(validation.checks) ? validation.checks : []).filter(check => check && typeof check === 'object')
    .map(check => ({ name: text(check.name), status: text(check.status), message: text(check.message) }));
  const issues = (Array.isArray(validation.issues) ? validation.issues : []).filter(issue => issue && typeof issue === 'object')
    .map(issue => ({ code: text(issue.code), field: text(issue.field), message: text(issue.message) }));
  const evidence = (Array.isArray(run.evidence) ? run.evidence : []).filter(item => item && typeof item === 'object')
    .map(item => ({ doc_id: item.doc_id ?? null, chunk_id: item.chunk_id ?? null, title: text(item.title), page_start: item.page_start ?? null, page_end: item.page_end ?? null, type: text(item.type), formula: text(item.formula), source: text(item.source) }));
  const events = (Array.isArray(run.events) ? run.events : []).filter(event => event && typeof event === 'object')
    .map(event => ({ sequence: Number.isInteger(event.sequence) ? event.sequence : null, step_id: text(event.step_id), status: text(event.status), at: text(event.at) }));
  let inputSnapshot = {};
  if (run.input_snapshot && typeof run.input_snapshot === 'object' && !Array.isArray(run.input_snapshot)) {
    try { inputSnapshot = JSON.parse(JSON.stringify(run.input_snapshot)); } catch { /* Invalid non-JSON input cannot be exported as evidence. */ }
  }
  const persistence = run.persistence && typeof run.persistence === 'object' ? {
    enabled: typeof run.persistence.enabled === 'boolean' ? run.persistence.enabled : null,
    saved: typeof run.persistence.saved === 'boolean' ? run.persistence.saved : null,
    run_id: text(run.persistence.run_id), project_id: text(run.persistence.project_id),
    revision: Number.isInteger(run.persistence.revision) ? run.persistence.revision : null,
    report_sha256: text(run.persistence.report_sha256), error_code: text(run.persistence.error_code),
    error_type: text(run.persistence.error_type), message: text(run.persistence.message),
  } : null;
  const verification = run.verification && typeof run.verification === 'object' ? {
    method: text(run.verification.method), nodal_solver_version: text(run.verification.nodal_solver_version),
    passed: run.verification.passed === true,
    ...Object.fromEntries(['cell_count', 'analytic_heat_rate_w', 'heat_absolute_error_w', 'heat_relative_error', 'max_internal_energy_imbalance_w', 'max_internal_energy_relative_error', 'absolute_tolerance_w', 'relative_tolerance']
      .map(key => [key, Number.isFinite(run.verification[key]) ? run.verification[key] : null])),
  } : null;
  const record = {
    schema_version: run.schema_version, scope: run.scope, run_id: text(run.run_id), status: text(run.status),
    tool_name: text(run.tool_name), tool_version: text(run.tool_version), input_fingerprint: text(run.input_fingerprint),
    model_version: text(run.model_version), project_id: text(run.project_id), persistence, verification,
    formula: text(run.formula), problem: { description: text(run.problem?.description), required_parameters: strings(run.problem?.required_parameters), missing_parameters: strings(run.problem?.missing_parameters), assumptions: strings(run.problem?.assumptions) },
    input_snapshot: inputSnapshot, events, created_at: text(run.created_at), finished_at: text(run.finished_at),
    steps, variables, validation: { status: text(validation.status), passed: validation.passed === true, checks, issues, limitations: strings(validation.limitations), schema_version: text(validation.schema_version), validator_version: text(validation.validator_version), validation_method: text(validation.validation_method), checked_quantity_count: Number.isInteger(validation.checked_quantity_count) ? validation.checked_quantity_count : null, energy_balance_checked: typeof validation.energy_balance_checked === 'boolean' ? validation.energy_balance_checked : null, energy_relative_error: Number.isFinite(validation.energy_relative_error) ? validation.energy_relative_error : null },
    evidence, report: { generated: run.report?.generated === true, content_sha256: text(run.report?.content_sha256) }, limitations: strings(run.limitations),
  };
  return {
    record,
    persistence: { failed: persistence?.saved === false && persistence?.enabled !== false, label: persistence?.enabled === true && persistence?.saved === true ? '已保存到工程历史' : persistence?.enabled === false ? '未启用持久保存' : persistence?.saved === false ? '执行记录未完整保存' : '未提供保存状态' },
    status: RUN_STATUSES[run.status] || { label: '状态未确认', color: 'default' },
    steps: steps.map(step => ({ ...step, statusLabel: STEP_STATUSES[step.status] || '状态未确认' })),
    variables: variables.map((variable, index) => ({ ...variable, key: `${variable.role}-${variable.name}-${index}`, display: engineeringValue(variable.value), roleLabel: variable.role === 'input' ? '输入' : '输出' })),
    validation: { label: checked ? '已通过已配置检查' : failed ? '校验未通过' : '校验证据不完整', type: checked ? 'success' : failed ? 'error' : 'warning', checks, issues },
    limitations: [...new Set([...record.limitations, ...record.validation.limitations])],
  };
}

const STATUS = {
  prepared: { label: '待确认执行', color: 'blue' },
  running: { label: '求解中', color: 'processing' },
  completed: { label: '求解完成', color: 'blue' },
  failed: { label: '执行失败', color: 'error' },
  timed_out: { label: '执行超时', color: 'error' },
  interrupted: { label: '执行中断', color: 'warning' },
};

export function fluentJobStatus(status) {
  return STATUS[status] || { label: '状态未知', color: 'default' };
}

export function fluentAvailability(status, useMockResponses = false) {
  if (useMockResponses) return { canPrepare: false, canRun: false, message: '当前为前端离线演示模式。CFD 任务及自动 Mock 需连接实际后端。' };
  if (!status) return { canPrepare: false, canRun: false, message: '尚未取得 CFD 服务状态。' };
  if (status.enabled !== true) return { canPrepare: false, canRun: false, message: 'CFD 接口尚未启用，请在后端配置后刷新。' };
  if (!Array.isArray(status.cases) || status.cases.length === 0) {
    return { canPrepare: false, canRun: false, message: '尚无已注册算例。请先由工程人员配置网格、边界条件和结果监测项。' };
  }
  const mock = status.selected_backend === 'mock';
  const canRun = status.execution_enabled === true && (mock || (status.selected_backend === 'fluent' && status.solver_found === true));
  return {
    canPrepare: true,
    canRun,
    message: mock
      ? canRun ? '当前使用 Mock CFD，可准备任务并确认运行演示流程。' : '当前选择 Mock CFD，但后端尚未允许执行。'
      : canRun
      ? '可准备任务并确认执行；运行后才能确认求解器与许可证实际可用。'
      : '可以准备任务。真实执行仍需后端启用运行权限并找到 Fluent 求解器。',
  };
}

export function prepareFluentInputs(values, status) {
  const errors = [];
  if (!fluentAvailability(status).canPrepare) errors.push('当前无法准备 CFD 任务。');
  if (!status?.cases?.some(item => item.case_id === values.case_id)) errors.push('请选择已注册的算例。');
  const { iterations, processors } = values;
  for (const [name, value, maximum] of [
    ['迭代次数', iterations, status?.limits?.max_iterations],
    ['并行核数', processors, status?.limits?.max_processors],
  ]) {
    if (!Number.isInteger(value) || value < 1) errors.push(`${name}必须为正整数。`);
    else if (Number.isFinite(maximum) && value > maximum) errors.push(`${name}不能超过 ${maximum}。`);
  }
  return { errors, payload: errors.length ? null : { case_id: values.case_id, iterations, processors } };
}

export function canRunFluentJob(job, status, useMockResponses = false) {
  return fluentAvailability(status, useMockResponses).canRun && job?.status === 'prepared'
    && typeof job.input_fingerprint === 'string' && Boolean(job.input_fingerprint)
    && typeof job.case_id === 'string' && Boolean(job.case_id);
}

export function fluentValidation(validation) {
  if (validation?.status === 'passed') return { label: '已通过已配置检查', type: 'success' };
  if (validation?.status === 'failed') return { label: '结果检查未通过', type: 'error' };
  return { label: '验证证据不完整', type: 'warning' };
}

export function fluentError(error) {
  if (error?.name === 'AbortError') return '请求超时或已取消。请刷新任务状态，确认服务器是否已接收任务。';
  if (error?.statusCode === 401 || error?.statusCode === 403) return '服务未授权或执行未启用，请检查后端访问和运行配置。';
  if (error?.statusCode === 404) return 'CFD 接口或任务不存在，请确认已启动支持 CFD 的后端。';
  if (error?.statusCode === 422) return '任务参数不符合服务要求，请检查算例、迭代次数和核数。';
  if (error?.statusCode === 409) return '任务状态或输入已变化，请刷新后重新确认。';
  if (error?.statusCode >= 500) return 'CFD 服务暂时无法处理请求，请检查服务状态后重试。';
  return '无法完成请求，请检查后端连接并刷新任务状态。';
}

export function fluentWarning(code) {
  return ({
    CFD_DISABLED: 'CFD 接口尚未启用。',
    CFD_MOCK_BACKEND: '当前使用 Mock CFD，仅用于演示与流程验证。',
    FLUENT_DISABLED: 'Fluent 接口尚未启用。',
    FLUENT_SOLVER_NOT_FOUND: '未找到 Fluent 求解器，请检查后端安装路径配置。',
    FLUENT_NO_REGISTERED_CASES: '尚无已注册算例。',
    FLUENT_REGISTRY_INVALID: '算例目录配置无效，请由工程人员检查配置。',
  })[code] || '后端报告配置警告，请检查 Fluent 算例和运行配置。';
}

export const CFD_MOCK_WARNING = 'Mock CFD / 演示数据，不能用于真实工程结论';

export function cfdProvenance(record) {
  const result = record?.result;
  const backends = [record?.selected_backend, record?.effective_backend, result?.effective_backend];
  const isMock = record?.is_mock === true || result?.is_mock === true || backends.includes('mock');
  const effectiveBackend = result?.effective_backend || record?.effective_backend || record?.selected_backend || 'unavailable';
  const realResult = !isMock && effectiveBackend === 'fluent' && result?.is_mock === false;
  return {
    isMock,
    effectiveBackend,
    label: isMock ? 'Mock CFD' : effectiveBackend === 'fluent' ? 'ANSYS Fluent' : '后端未确认',
    resultLabel: isMock ? 'Mock CFD 演示输出' : realResult ? '真实 Fluent 输出' : '执行来源未确认',
    warning: isMock ? CFD_MOCK_WARNING : null,
    fallbackReason: result?.fallback_reason || record?.fallback_reason || null,
  };
}

export function publicCfdEnvironment(status) {
  const environment = status?.environment;
  if (!environment || typeof environment !== 'object') return null;
  const safeText = value => typeof value === 'string' ? value.slice(0, 500) : null;
  return {
    schema_version: safeText(environment.schema_version),
    status: safeText(environment.status),
    solver_found: typeof environment.solver_found === 'boolean' ? environment.solver_found : null,
    version: safeText(environment.version),
    license_checked: environment.license_checked === true,
    requested_path_kind: safeText(environment.requested_path_kind),
    resolution_source: safeText(environment.resolution_source),
    checks: (Array.isArray(environment.checks) ? environment.checks : []).map(check => ({
      name: safeText(check?.name), status: safeText(check?.status), code: safeText(check?.code), message: safeText(check?.message),
    })),
  };
}

export function historySeries(history) {
  const points = Array.isArray(history?.points) ? history.points : [];
  return points.filter(point => Array.isArray(point) && point.length >= 2 && Number.isFinite(point[0]) && Number.isFinite(point[1]))
    .map(point => [point[0], point[1]]);
}

export function historyAxis(history) {
  if (history?.axis === 'position_m') return { label: '位置', unit: history.axis_unit || 'm', spatial: true };
  if (!history?.axis || ['iteration', 'iterations'].includes(history.axis)) return { label: '迭代次数', unit: history?.axis_unit || '', spatial: false };
  return { label: history.axis, unit: history.axis_unit || '', spatial: false };
}

export function fluentMetric(value, unit) {
  return Number.isFinite(value) ? `${Number(value.toPrecision(7)).toLocaleString('zh-CN', { maximumFractionDigits: 8 })}${unit ? ` ${unit}` : ''}` : '无有效数值';
}

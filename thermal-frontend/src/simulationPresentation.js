const FIELD_DEFINITIONS = Object.freeze({
  thickness_m: { label: '壁厚', unit: 'm' },
  thermal_conductivity_w_mk: { label: '导热系数', unit: 'W/(m·K)' },
  area_m2: { label: '面积', unit: 'm²' },
  delta_temperature_k: { label: '两侧温差', unit: 'K' },
  temperature_difference_k: { label: '温差', unit: 'K' },
  heat_rate_w: { label: '热流率', unit: 'W' },
  heat_flux_w_m2: { label: '热流密度', unit: 'W/m²' },
  hot_temperature_c: { label: '热侧温度', unit: '℃' },
  cold_temperature_c: { label: '冷侧温度', unit: '℃' },
  thermal_resistance_k_w: { label: '等效热阻', unit: 'K/W' },
});

const RESULT_FIELD_ORDER = [
  'heat_rate_w',
  'heat_flux_w_m2',
  'temperature_difference_k',
  'thermal_resistance_k_w',
];

const GENERATED_OUTPUT_LABELS = Object.freeze({
  heat_flow: '热流率',
  heat_flow_rate: '热流率',
  temperature: '温度',
});

function finiteNumber(value) {
  if (typeof value === 'boolean' || value === '' || value === null) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function formatSimulationNumber(value) {
  const number = finiteNumber(value);
  if (number === null) return '—';
  const normalized = Object.is(number, -0) ? 0 : number;
  return new Intl.NumberFormat('en-US', {
    useGrouping: true,
    maximumFractionDigits: 12,
  }).format(normalized);
}

export function simulationFieldLabel(name) {
  return FIELD_DEFINITIONS[name]?.label || '其他结果';
}

export function formatSimulationField(name, value) {
  const definition = FIELD_DEFINITIONS[name];
  if (!definition) return null;
  if (finiteNumber(value) === null) return null;
  let displayValue = value;
  let unit = definition.unit;
  if (name === 'thickness_m') {
    const number = finiteNumber(value);
    if (number !== null && Math.abs(number) < 1) {
      displayValue = number * 1000;
      unit = 'mm';
    }
  }
  return {
    key: name,
    label: definition.label,
    value,
    unit,
    display: `${formatSimulationNumber(displayValue)} ${unit}`,
  };
}

function generatedOutputFields(result) {
  if (!Array.isArray(result?.outputs)) return [];
  return result.outputs.flatMap((output, index) => {
    if (!output || output.status !== 'ok') return [];
    const series = Array.isArray(output.series) ? output.series : [];
    const last = series.length > 0 ? series[series.length - 1] : null;
    const value = output.value ?? last?.value;
    if (finiteNumber(value) === null) return [];
    const quantity = String(output.quantity || '');
    const unit = String(output.unit || '').trim();
    return [{
      key: `generated-output-${index}`,
      label: GENERATED_OUTPUT_LABELS[quantity] || '模型输出',
      value,
      unit,
      display: `${formatSimulationNumber(value)}${unit ? ` ${unit}` : ''}`,
    }];
  });
}

function generatedValidationEvidence(execution) {
  const critic = execution?.evidence?.result_critic || {};
  const analytical = critic?.analytical_check || {};
  const crossCheck = analytical?.cross_check || {};
  const verdict = String(critic?.verdict || '').toLowerCase();
  const analyticalPassed = analytical?.status === 'PASS' && crossCheck?.passed === true;
  const validationLevel = String(critic?.validation_level || '').toLowerCase();
  const unit = execution?.result?.outputs?.find?.(output => output?.status === 'ok')?.unit || '';
  const withUnit = value => finiteNumber(value) === null ? null : `${formatSimulationNumber(value)}${unit ? ` ${unit}` : ''}`;
  const relative = finiteNumber(crossCheck?.relative_error);
  return {
    criticLabel: verdict === 'pass'
      ? (validationLevel === 'analytical' && analyticalPassed ? '解析校验通过' : '基础检查通过')
      : verdict === 'warning' ? '检查通过（有警告）' : verdict === 'fail' ? '检查未通过' : null,
    criticPassed: verdict === 'pass',
    analyticalStatus: analyticalPassed ? '通过' : analytical?.status === 'FAIL' ? '未通过' : null,
    expectedLabel: withUnit(crossCheck?.expected),
    actualLabel: withUnit(crossCheck?.actual),
    relativeErrorLabel: relative === null ? null : `${formatSimulationNumber(relative * 100)}%`,
    toleranceLabel: withUnit(crossCheck?.tolerance),
  };
}

export function formatSimulationFormula(value) {
  const formula = String(value || '').replace(/\s+/g, '');
  if (/^Q=k\*?A\*?(?:delta_T|ΔT)\/L$/i.test(formula)) return 'Q = kAΔT / L';
  return value ? String(value) : '—';
}

function modelName(plan) {
  if (plan?.selected_model_name) return plan.selected_model_name;
  if ((plan?.selected_model_id || plan?.model_id) === 'plane_wall_steady_v1') return '平壁稳态导热';
  return plan?.selected_model_id || plan?.model_id || '—';
}

function selectionReason(value) {
  const reason = String(value || '');
  if (reason.startsWith('exact_scenario_and_keyword_match')) return '场景与关键词匹配';
  if (reason.startsWith('exact_scenario_match')) return '场景匹配';
  if (reason === 'multiple_compatible_models') return '找到多个候选模型';
  return reason ? '已按模型目录完成匹配' : '—';
}

function missingInputLabel(name) {
  if (name === 'temperature_boundary') return '温度边界（提供两侧温差，或热侧与冷侧温度）';
  return FIELD_DEFINITIONS[name]?.label || '所需参数';
}

function executionBlockLabel(code) {
  const labels = {
    MATLAB_NOT_AVAILABLE: 'MATLAB 当前不可用，计划不会执行。',
    MATLAB_STATUS_CHECK_FAILED: 'MATLAB 状态检查失败，计划不会执行。',
    SIMULATION_INPUTS_INCOMPLETE: '还需要补充参数。',
    GENERATED_MODEL_APPROVAL_REQUIRED: '需管理员审核并启用，当前尚未执行。',
    GENERATED_MODEL_INPUTS_INCOMPLETE: '生成模型仍需补充参数，当前尚未执行。',
  };
  return labels[code] || (code ? '当前计划尚不能执行。' : null);
}

export function buildPlanPresentation(plan, mode, matlab, actionsEnabled = true) {
  const missing = plan?.missing_inputs || plan?.missing_parameters || [];
  const invalid = (plan?.input_errors?.length || 0) > 0 || (plan?.input_conflicts?.length || 0) > 0;
  const active = actionsEnabled && mode?.cancelled !== true && mode?.confirmed !== true && mode?.executed !== true;
  const canConfirm = active && mode?.pending_confirmation === true && mode?.confirm_allowed === true
    && plan?.can_execute_now === true && plan?.execution_allowed === true && missing.length === 0 && !invalid;
  return {
    generated: plan?.generated === true,
    planId: plan?.plan_id || null,
    generatedStatusLabel: ({
      draft: '待编译',
      pending_approval: '待管理员审核',
      approved: '待启用',
      enabled: '已启用',
      disabled: '已禁用',
      execution_failed: '执行失败',
    })[plan?.generated_model_status] || null,
    title: canConfirm ? '仿真计划已就绪' : '仿真计划',
    objective: plan?.objective || plan?.user_goal || '—',
    modelLabel: modelName(plan),
    backendLabel: String(plan?.solver_backend || '—').replace(/^matlab$/i, 'MATLAB'),
    selectionLabel: selectionReason(plan?.selection_reason),
    fields: Object.entries(plan?.inputs || {}).map(([name, value]) => formatSimulationField(name, value)).filter(Boolean),
    missing: missing.map(missingInputLabel),
    parameterStatus: missing.length === 0 && !invalid ? '✓ 完整' : invalid ? '需要修正' : '需要补充',
    candidates: Array.isArray(plan?.candidate_models) ? plan.candidate_models.map(candidate => ({
      id: candidate.model_id,
      label: candidate.display_name || (candidate.model_id === 'plane_wall_steady_v1' ? '平壁稳态导热' : '候选模型'),
    })) : [],
    needsModelSelection: plan?.selection_reason === 'multiple_compatible_models',
    blockLabel: executionBlockLabel(plan?.not_executable_reason || plan?.execution_block_reason),
    invalid,
    matlabUnavailable: plan?.solver_backend === 'matlab' && matlab?.available === false,
    preparationLabel: plan?.execution_allowed === false ? '仅生成仿真计划，尚未执行' : null,
    canConfirm,
    canRevise: active,
    reviseLabel: invalid ? '修正参数' : canConfirm ? '修改计划' : '补充参数',
    canCancel: active,
  };
}

function executionMode(matlab, execution) {
  const backend = String(execution?.solver_backend || execution?.backend || '').toLowerCase();
  const mode = String(matlab?.execution_mode || '').toLowerCase();
  if (execution?.executed !== true) return '仅生成仿真计划，尚未执行';
  if (backend === 'matlab' && matlab?.uses_real_matlab === true) return '真实 MATLAB';
  if (backend === 'matlab' && (mode === 'mock' || matlab?.uses_real_matlab === false)) return '测试 Mock';
  return '已执行';
}

function formatMatlabVersion(value) {
  const version = String(value || '').trim();
  if (!version) return null;
  return /^R/i.test(version) ? `MATLAB ${version}` : `MATLAB R${version}`;
}

export function formatDurationMs(milliseconds) {
  const value = finiteNumber(milliseconds);
  if (value === null || value < 0) return null;
  if (value < 1000) {
    const rounded = Math.round(value * 10) / 10;
    return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(rounded)} ms`;
  }
  const seconds = value / 1000;
  return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(seconds)} s`;
}

function formatDuration(seconds) {
  const value = finiteNumber(seconds);
  return value === null ? null : formatDurationMs(value * 1000);
}

function completedSummary(plan, resultFields) {
  const byKey = Object.fromEntries(resultFields.map(field => [field.key, field.display]));
  const heatRate = byKey.heat_rate_w;
  const heatFlux = byKey.heat_flux_w_m2;
  if ((plan?.selected_model_id || plan?.model_id) === 'plane_wall_steady_v1' && heatRate && heatFlux) {
    return `在给定参数下，该平壁稳态导热模型计算得到热流率为 ${heatRate}，对应热流密度为 ${heatFlux}。\n\n该结果来自一维稳态 Fourier 导热模型，不包含接触热阻、对流换热、辐射或三维边缘效应。`;
  }
  const values = resultFields.map(field => `${field.label}为 ${field.display}`).join('，');
  return values ? `仿真已执行完成，${values}。` : '仿真已执行完成，结果与执行证据如下。';
}

function sourceLocator(source) {
  const parts = [];
  if (source?.section) parts.push(String(source.section));
  else if (source?.chapter) parts.push(String(source.chapter));
  const start = source?.page_start;
  const end = source?.page_end;
  if (start !== undefined && start !== null) {
    parts.push(end !== undefined && end !== null && end !== start ? `第 ${start}–${end} 页` : `第 ${start} 页`);
  }
  return parts.join(' · ');
}

export function buildKnowledgeSourcesPresentation(sources, { relatedToSimulation = false } = {}) {
  const items = Array.isArray(sources) ? sources.map((source, index) => {
    const preview = String(source?.text_preview || source?.snippet || '').replace(/\s+/g, ' ').trim();
    return {
      key: source?.chunk_id ?? source?.chunk_index ?? `${source?.doc_id ?? 'source'}-${source?.page_start ?? 'page'}-${index}`,
      title: String(source?.title || `知识来源 ${index + 1}`),
      locator: sourceLocator(source),
      preview: preview.length > 220 ? `${preview.slice(0, 220)}…` : preview,
    };
  }) : [];
  return {
    title: relatedToSimulation ? '相关知识来源（可选）' : '参考来源',
    items,
  };
}

function buildErrorPresentation(execution) {
  const error = Array.isArray(execution?.errors) ? execution.errors[0] || {} : {};
  const code = String(error.code || 'SIMULATION_EXECUTION_FAILED');
  const known = {
    MATLAB_TIMEOUT: ['MATLAB 求解超时', 'MATLAB 求解在规定时间内未完成。'],
    MATLAB_NOT_AVAILABLE: ['仿真未执行', 'MATLAB 当前不可用，未启动求解器。'],
    SIMULATION_INPUTS_INCOMPLETE: ['还需要补充仿真参数', '当前计划缺少执行所需的输入参数。'],
    SIMULATION_INPUT_CONFLICT: ['参数需要修正', '输入参数之间存在矛盾，请修正后重新确认。'],
    MATLAB_EXECUTION_ERROR: ['MATLAB 执行失败', 'MATLAB 未能完成本次仿真。'],
  };
  const [title, description] = known[code] || ['仿真执行失败', '求解器未能完成本次仿真。'];
  return { title, description, code };
}

export function buildSimulationPresentation(response, { action = null } = {}) {
  const metadata = response?.metadata && typeof response.metadata === 'object' ? response.metadata : {};
  const mode = metadata.simulation_mode || {};
  const plan = metadata.simulation_plan || {};
  const execution = metadata.simulation_execution || {};
  const matlab = metadata.matlab || {};
  const state = String(mode.state || execution.status || (plan.generated ? 'planning' : 'available'));
  const completed = execution.executed === true && (state === 'completed' || execution.status === 'completed');
  const executionErrors = Array.isArray(execution.errors) ? execution.errors : [];
  const blockedAfterAttempt = state === 'blocked' && (
    mode.confirmed === true || execution.status === 'blocked' || executionErrors.length > 0
  );
  const failed = !completed && (
    state === 'failed' || execution.status === 'failed' || blockedAfterAttempt || executionErrors.length > 0
  );
  const cancelled = mode.cancelled === true || state === 'cancelled';
  const executing = !completed && (state === 'executing' || execution.status === 'running');
  const currentAction = action || (/确认执行/.test(String(response?.query || '')) ? 'confirm' : null);
  const statusOnly = currentAction === 'status';
  const showCompleted = completed && !statusOnly;
  const outputs = execution.result || {};
  const fixedResultFields = RESULT_FIELD_ORDER.map(name => formatSimulationField(name, outputs[name])).filter(Boolean);
  const resultFields = fixedResultFields.length > 0 ? fixedResultFields : generatedOutputFields(outputs);
  const generatedValidation = generatedValidationEvidence(execution);
  const version = outputs.model_version || execution.evidence?.model_version || plan.model_version || null;
  const formula = formatSimulationFormula(outputs.formula || execution.evidence?.formula);
  const error = buildErrorPresentation(execution);

  return {
    hasAttachment: Boolean(plan.generated || completed || executing || failed || cancelled),
    state,
    showPlan: Boolean(plan.generated && !completed && !executing && !failed && !cancelled && !statusOnly),
    showExecution: executing && !statusOnly,
    showResult: showCompleted,
    showEvidence: showCompleted,
    showError: failed && !statusOnly,
    showCancelled: cancelled && !statusOnly,
    showStatus: statusOnly,
    statusLabel: ({
      planning: '正在生成计划',
      pending_confirmation: '等待确认',
      executing: '正在执行',
      completed: '已完成',
      failed: '执行失败',
      blocked: '已阻止执行',
      cancelled: '已取消',
    })[state] || '状态已更新',
    summary: showCompleted ? completedSummary(plan, resultFields) : failed ? error.description : null,
    raw: { mode, plan, execution, matlab },
    plan: buildPlanPresentation(plan, mode, matlab),
    execution: {
      backendLabel: String(execution.solver_backend || execution.backend || '求解器').replace(/^matlab$/i, 'MATLAB'),
    },
    result: {
      title: String(execution.solver_backend || execution.backend || '').toLowerCase() === 'matlab'
        ? 'MATLAB 仿真结果'
        : '仿真结果',
      statusLabel: '已完成',
      modelLabel: modelName(plan),
      fields: resultFields,
    },
    evidence: {
      backendLabel: String(execution.solver_backend || execution.backend || '—').replace(/^matlab$/i, 'MATLAB'),
      modeLabel: executionMode(matlab, execution),
      modelLabel: plan.selected_model_id || plan.model_id || outputs.model_id || '—',
      modelVersion: version,
      formula,
      matlabVersion: formatMatlabVersion(matlab.matlab_version || execution.evidence?.engine_release),
      durationLabel: formatDuration(execution.duration_seconds),
      cfdLabel: execution.cfd_executed === true ? 'CFD 已执行' : 'CFD 未执行',
      cfdExecuted: execution.cfd_executed === true,
      ...generatedValidation,
    },
    error,
  };
}

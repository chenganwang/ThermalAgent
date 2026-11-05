export const PARAMETER_LABELS = {
  channel_width: '流道宽度', channel_depth: '流道深度', channel_spacing: '流道间距（肋宽）',
  channel_count: '流道数量', plate_width: '板宽', plate_length: '板长', plate_thickness: '板厚', topology: '拓扑',
};

export const PROVENANCE = {
  fluent_export: { label: 'Fluent 数据（用户声明）', color: 'blue' },
  manual_import: { label: '人工导入数据', color: 'default' },
  synthetic_demo: { label: '合成演示数据 · 非仿真', color: 'orange' },
};

export function provenanceLabel(value) { return PROVENANCE[value]?.label || `未识别来源：${value || '缺失'}`; }

// Values describe a small software demonstration, not manufacturing limits.
export function demoStudyDefinition() {
  const source = 'MVP 软件演示输入；非制造边界，实际范围须由研究者确认';
  return {
    title: 'PEM 阳极单相流道初筛 · 演示', objective: '演示约束、DOE、导入与可比性检查；不评价电解效率',
    side: 'anode', physics_model: 'single_phase', model_version: 'demo-single-phase-v1', fluid: 'water',
    boundary_conditions: { mass_flow_rate: { value: 0.001, unit: 'kg/s' }, temperature: { value: 298.15, unit: 'K' }, outlet_pressure: { value: 101325, unit: 'Pa' } },
    parameter_space: [
      { name: 'channel_width', kind: 'continuous', unit: 'mm', lower: 0.8, upper: 1.2, source },
      { name: 'channel_depth', kind: 'continuous', unit: 'mm', lower: 0.4, upper: 0.8, source },
      { name: 'channel_spacing', kind: 'continuous', unit: 'mm', lower: 0.4, upper: 0.8, source },
      { name: 'channel_count', kind: 'integer', unit: '1', lower: 8, upper: 12, source },
      { name: 'plate_width', kind: 'continuous', unit: 'mm', lower: 30, upper: 30, source },
      { name: 'plate_length', kind: 'continuous', unit: 'mm', lower: 50, upper: 50, source },
      { name: 'plate_thickness', kind: 'continuous', unit: 'mm', lower: 2, upper: 2, source },
      { name: 'topology', kind: 'categorical', unit: '1', choices: ['parallel'], source },
    ],
  };
}

export function prepareStudyDefinition(draft) {
  const definition = structuredClone(draft);
  const errors = [];
  if (!definition.title?.trim()) errors.push('请输入研究名称。');
  if (!definition.objective?.trim()) errors.push('请输入研究目标与验证范围。');
  if (!definition.model_version?.trim()) errors.push('物理模型版本不能为空。');
  if (!definition.fluid?.trim()) errors.push('介质不能为空。');
  for (const parameter of definition.parameter_space || []) {
    const name = PARAMETER_LABELS[parameter.name] || parameter.name;
    if (!parameter.source?.trim()) errors.push(`${name}：请记录参数范围来源。`);
    if (parameter.kind === 'categorical') {
      parameter.choices = (typeof parameter.choices === 'string' ? parameter.choices.split(',') : parameter.choices || []).map(value => String(value).trim()).filter(Boolean);
      if (parameter.choices.length === 0) errors.push(`${name}：至少一个类别。`);
      parameter.unit = '1'; delete parameter.lower; delete parameter.upper;
    } else {
      if (!Number.isFinite(parameter.lower) || !Number.isFinite(parameter.upper)) errors.push(`${name}：上下界必须是有限数值。`);
      else if (parameter.lower > parameter.upper) errors.push(`${name}：下界不能大于上界。`);
      if (parameter.kind === 'integer' && (!Number.isInteger(parameter.lower) || !Number.isInteger(parameter.upper))) errors.push(`${name}：整数变量的上下界必须为整数。`);
      if (!parameter.unit?.trim()) errors.push(`${name}：单位不能为空。`);
      delete parameter.choices;
    }
  }
  for (const name of Object.keys(PARAMETER_LABELS)) if (!(definition.parameter_space || []).some(item => item.name === name)) errors.push(`缺少必需参数：${PARAMETER_LABELS[name]}。`);
  return { definition, errors };
}

export function parseFieldMap(text) {
  const value = JSON.parse(text || '{}');
  if (!value || Array.isArray(value) || typeof value !== 'object' || Object.values(value).some(item => typeof item !== 'string')) throw new Error('字段映射必须是 JSON 对象，映射值必须为字段名字符串。');
  return value;
}

export function prepareImportPayload({ format, content, filename, provenance, fieldMap }) {
  if (!content?.trim()) throw new Error('请读取文件或填入 CSV/JSON 文本。');
  if (!filename?.trim()) throw new Error('请记录文件来源名称。');
  if (!Object.hasOwn(PROVENANCE, provenance)) throw new Error('必须选择明确的数据来源。');
  if (provenance !== 'synthetic_demo' && /synthetic-fixture|synthetic-demo/.test(content)) throw new Error('内容包含明确合成演示标记，请选择 synthetic_demo 来源。');
  return { format, content, filename, provenance, field_map: parseFieldMap(fieldMap) };
}

export function decodeUtf8Import(bytes) {
  try { return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes); }
  catch { throw new Error('仅支持 UTF-8 CSV/JSON 文本，请先将原文件转存为 UTF-8 后再导入。'); }
}

// A fixed observation fixture is intentionally independent of parameter values.
// It exercises import/quality flows; it does not estimate candidate performance.
const DEMO_OBSERVATIONS = [
  { pressure_drop: 125, channel_mass_flows: [0.000098, 0.000102], convergence_status: 'converged' },
  { pressure_drop: 140, channel_mass_flows: [0.000099, 0.000101], convergence_status: 'converged' },
  { pressure_drop: 118, channel_mass_flows: [0.000092, 0.000108], convergence_status: 'unconverged' },
];

export function demoResultRows(study, candidates) {
  const definition = study.definition || study;
  const massFlow = definition.boundary_conditions?.mass_flow_rate;
  if (definition.physics_model !== 'single_phase' || definition.fluid !== 'water' || massFlow?.unit !== 'kg/s' || massFlow?.value !== 0.001) throw new Error('固定演示观测只适用于演示单相 water 工况（0.001 kg/s）；请创建新的演示研究。');
  return candidates.slice(0, 3).map((candidate, index) => {
    const fixed = DEMO_OBSERVATIONS[index];
    const count = candidate.parameters?.channel_count?.value ?? candidate.parameters?.channel_count ?? 10;
    const flows = Array.from({ length: count }, (_, channel) => channel % 2 ? fixed.channel_mass_flows[1] : fixed.channel_mass_flows[0]);
    const sum = flows.reduce((total, value) => total + value, 0);
    return {
      candidate_id: candidate.candidate_id, geometry_version: candidate.geometry_version || candidate.parameter_hash || candidate.candidate_id,
      physics_model: definition.physics_model, model_version: definition.model_version, fluid: definition.fluid, side: definition.side,
      boundary_conditions: structuredClone(definition.boundary_conditions), pressure_drop: fixed.pressure_drop, pressure_drop_unit: 'Pa',
      pressure_drop_definition: { pressure_kind: 'static', inlet_surface: 'inlet', outlet_surface: 'outlet', averaging: 'area_weighted_mean', sign_convention: 'inlet_minus_outlet' },
      inlet_mass_flow: 0.001, inlet_mass_flow_unit: 'kg/s', outlet_mass_flow: 0.001, outlet_mass_flow_unit: 'kg/s',
      channel_mass_flows: flows.map(value => value / sum * 0.001), channel_mass_flows_unit: 'kg/s',
      mesh_cells: 120000, mesh_id: 'synthetic-demo-mesh-v1', mesh_min_orthogonal_quality: 0.25, mesh_max_skewness: 0.6,
      convergence_status: fixed.convergence_status, iterations: 200, residuals: { continuity: index === 2 ? 0.001 : 0.000001 },
      convergence_criteria: { continuity: 0.00001 }, solver_version: 'synthetic-fixture-no-Fluent-solver',
      mass_balance_scope: 'whole_domain_all_boundaries', flow_distribution_basis: 'total_mass_flow', physical_model_details: { flow_model: 'laminar', steady: true },
    };
  });
}

export function formatNumber(value) { return Number.isFinite(value) ? Number(value.toPrecision(6)).toLocaleString('zh-CN') : '—'; }

export function qualityLabel(status) {
  return ({ screened: '软件初筛通过', valid: '软件检查通过', warning: '警告', invalid: '不合格', failed: '失败', pass: '软件检查通过' })[status] || status || '待检查';
}

export function observedChartOption(rows) {
  return {
    aria: { enabled: true }, tooltip: { trigger: 'axis' }, legend: { data: ['压降 / Pa', '流量变异系数 CV'] },
    grid: { left: 65, right: 65, bottom: 80, top: 55 },
    xAxis: { type: 'category', data: rows.map(row => row.candidate_id), axisLabel: { rotate: 20 } },
    yAxis: [{ type: 'value', name: '压降 / Pa' }, { type: 'value', name: 'CV（越低越均匀）' }],
    series: [
      { name: '压降 / Pa', type: 'bar', data: rows.map(row => row.metrics?.pressure_drop_pa ?? row.pressure_drop_pa ?? null) },
      { name: '流量变异系数 CV', type: 'line', yAxisIndex: 1, data: rows.map(row => row.metrics?.flow_uniformity_cv ?? row.metrics?.flow_cv ?? row.flow_uniformity_cv ?? row.flow_cv ?? null) },
    ],
  };
}

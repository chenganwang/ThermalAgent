import { engineeringRunPresentation } from '../engineeringRunPresentation.js';
import { assertResultIdentity } from '../resultIdentity.js';

const OUTPUTS = [
  ['heat_rate', 'Heat Flow / 热流', 'W'],
  ['heat_rate_W', 'Heat Flow / 热流', 'W'],
  ['heat_flow_W', 'Heat Flow / 热流', 'W'],
  ['heat_transfer_W', 'Heat Flow / 热流', 'W'],
  ['pressure_drop_pa', 'Pressure Drop / 压降', 'Pa'],
  ['volume_flow_L_min', 'Volume Flow / 流量', 'L/min'],
  ['equivalent_resistance', 'Thermal Resistance / 热阻', 'K/W'],
  ['R_cond_K_per_W', 'Thermal Resistance / 热阻', 'K/W'],
];
const finite = value => typeof value === 'number' && Number.isFinite(value);
const records = value => Array.isArray(value) ? value.filter(item => item && typeof item === 'object') : [];

export function resultNumber(value) {
  if (!finite(value)) return '未记录';
  if (value !== 0 && Math.abs(value) < 0.01) return value.toPrecision(3);
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value);
}

/** Project recorded contracts only; never infer a result or PASS from prose. */
export function engineeringResult({ task, response } = {}) {
  try { assertResultIdentity({ task, response }); } catch { return null; }
  const payload = response || task?.result;
  const meta = payload?.metadata || {};
  const run = engineeringRunPresentation(payload)?.record;
  const variables = records(task?.variables || run?.variables);
  const measured = meta.calculation?.tool_result || {};
  let primary = null;
  for (const [name, label, unit] of OUTPUTS) {
    const variable = variables.find(item => item.name === name && item.role === 'output' && finite(item.value));
    const value = variable ? variable.value : measured[name];
    if (finite(value)) { primary = { name, label, value, unit: variable?.unit || unit }; break; }
  }
  if (!primary) return null;
  const resistance = ['equivalent_resistance', 'R_cond_K_per_W'].map(name => {
    const variable = variables.find(item => item.name === name && item.role === 'output' && finite(item.value));
    const value = variable ? variable.value : measured[name];
    return finite(value) ? { name, label: 'Total Thermal Resistance / 总热阻', value, unit: variable?.unit || 'K/W' } : null;
  }).find(Boolean);
  const validation = task?.validation || meta.physics_validation || run?.validation || meta.calculation?.raw?.physics_validation;
  const physics = validation?.status === 'passed' && validation.passed === true ? 'pass' : validation?.status === 'failed' ? 'fail' : 'unknown';
  const review = task?.design_review || meta.design_review;
  const checks = records(review?.checks);
  const design = !review ? 'unset' : review.status === 'violated' ? 'fail'
    : review.status === 'passed' && review.passed === true && checks.length > 0 && checks.every(check => check.status === 'passed') ? 'pass' : 'unknown';
  const steps = records(task?.steps);
  const retrieval = steps.find(step => step.step_id === 'retrieval');
  const sources = records(payload?.sources);
  const report = task?.report || meta.report || run?.report;
  const failedEvidence = Boolean(meta.retrieval_error || task?.error || run?.persistence?.saved === false
    || (retrieval && retrieval.status !== 'completed')
    || steps.some(step => step.step_id !== 'design_review' && ['failed', 'incomplete', 'blocked'].includes(step.status)));
  const completeEvidence = !failedEvidence && sources.length > 0 && physics === 'pass' && report?.generated === true
    && (!retrieval || retrieval.status === 'completed') && run?.persistence?.saved === true;
  const evidence = completeEvidence ? 'complete' : 'incomplete';
  const risks = [];
  if (design === 'fail') risks.push('当前计算超出已声明的设计上限，方案尚未达标。');
  if (physics === 'fail') risks.push('物理校验未通过，请先核对输入与计算记录。');
  if (physics === 'unknown') risks.push('物理校验尚未提供完整回执。');
  if (evidence === 'incomplete') risks.push('工程证据尚不完整，请展开记录核对知识来源、校验和保存状态。');
  return { primary, secondary: resistance?.name !== primary.name ? resistance : null, physics, design, evidence, checks, risks, taskId: task?.task_id || meta.engineering_task?.task_id || null, parentTaskId: task?.parent_task_id || meta.engineering_task?.parent_task_id || null };
}

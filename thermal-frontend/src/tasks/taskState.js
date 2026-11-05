import { assertResultIdentity, identityError, RESULT_IDENTITY_ERROR, RESULT_IDENTITY_MESSAGE } from '../resultIdentity.js';

export const TASK_STATUS = {
  queued: '排队中', planned: '已规划', pending: '待执行', running: '执行中', cancelling: '等待取消',
  completed: '已完成', blocked: '等待补充参数', failed: '执行失败', incomplete: '证据不完整',
  cancelled: '已取消', interrupted: '执行中断', skipped: '已跳过',
};
export const TERMINAL_TASK_STATES = new Set(['completed', 'blocked', 'failed', 'incomplete', 'cancelled', 'interrupted']);
export const LIQUID_COOLING_EXAMPLE = '请设计液冷回路：功率1000W，允许温升5K，比热4180J/(kg·K)，密度997kg/m³，动力黏度0.001Pa·s，管径10mm，管长2m。计算质量与体积流量、流速、雷诺数和压降，检查物理约束并生成报告。';
export function taskStatusLabel(status) { return TASK_STATUS[status] || '状态未确认'; }
export function isTerminalTask(task) { return TERMINAL_TASK_STATES.has(task?.status); }
export function canRetryTask(task) { return task?.recoverable === true && isTerminalTask(task) && Number.isInteger(task.revision); }
export function orderedTaskEvents(events) {
  const unique = new Map();
  for (const event of Array.isArray(events) ? events : []) if (event && Number.isInteger(event.sequence) && event.sequence >= 0) unique.set(event.sequence, event);
  return [...unique.values()].sort((a, b) => a.sequence - b.sequence);
}
export function taskDependencyLayout(steps) {
  const records = (Array.isArray(steps) ? steps : []).filter(step => step && typeof step.step_id === 'string');
  const map = new Map(records.map(step => [step.step_id, step]));
  const levels = new Map();
  const visit = (id, seen = new Set()) => {
    if (levels.has(id)) return levels.get(id);
    if (seen.has(id)) return 0;
    const path = new Set([...seen, id]);
    const parents = (map.get(id)?.depends_on || []).filter(parent => map.has(parent));
    const level = Math.min(records.length, parents.length ? Math.max(...parents.map(parent => visit(parent, path))) + 1 : 0);
    levels.set(id, level); return level;
  };
  const rows = new Map();
  const nodes = records.map(step => { const level = visit(step.step_id); const row = rows.get(level) || 0; rows.set(level, row + 1); return { ...step, x: 12 + level * 185, y: 12 + row * 84 }; });
  const byId = new Map(nodes.map(node => [node.step_id, node]));
  const edges = nodes.flatMap(node => (node.depends_on || []).filter(id => byId.has(id)).map(id => ({ from: byId.get(id), to: node })));
  return { nodes, edges, width: Math.max(190, ...nodes.map(node => node.x + 177)), height: Math.max(90, ...nodes.map(node => node.y + 75)) };
}
export function acceptTaskSnapshot(previous, next, expected = {}) {
  if (!next || typeof next.task_id !== 'string' || !Object.hasOwn(TASK_STATUS, next.status) || !Number.isInteger(next.revision)) throw new Error('工程任务响应缺少有效的任务编号、状态或版本；请从任务历史核对。');
  if (previous && next.task_id !== previous.task_id) throw identityError('task_id');
  assertResultIdentity({ ...expected, task: next });
  if (previous) {
    for (const field of ['query', 'request_fingerprint', 'input_fingerprint', 'calculation_fingerprint', 'session_id', 'run_id']) {
      if (previous[field] && next[field] && previous[field] !== next[field]) throw identityError(field);
    }
    if (next.revision < previous.revision) return previous;
  }
  return { ...next, events: orderedTaskEvents(next.events) };
}
export function taskConnectionError(error, taskId) {
  if (error?.code === RESULT_IDENTITY_ERROR) return RESULT_IDENTITY_MESSAGE;
  if (error?.statusCode === 401 || error?.statusCode === 403) return '没有访问工程任务的权限，请检查当前服务身份。';
  if (error?.statusCode === 409) return '任务已变化，请刷新后核对；本次没有重复提交。';
  if (taskId) return '与任务服务的连接已中断，任务可能仍在运行。可按任务编号刷新查看；不会自动重新提交。';
  return '没有收到任务提交回执，无法确认是否已创建。请先检查任务历史，再决定是否重新提交。';
}

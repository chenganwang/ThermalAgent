import { taskStatusLabel } from './taskState.js';

export const HYPER_STATUS = {
  queued: 'IN QUEUE', planned: 'PLAN READY', pending: 'STANDBY', running: 'IN PROGRESS',
  cancelling: 'CANCEL REQUESTED', completed: 'COMPLETED', blocked: 'INPUT REQUIRED',
  failed: 'EXECUTION FAILED', incomplete: 'EVIDENCE INCOMPLETE', cancelled: 'CANCELLED',
  interrupted: 'INTERRUPTED', skipped: 'SKIPPED',
  design_failed: 'DESIGN LIMIT FAILED',
};
export const HYPER_MARK = { completed: '✓', running: '▶', failed: '!', incomplete: '!', blocked: '?', interrupted: '!', cancelled: '×', skipped: '–', design_failed: '×' };

export function hyperMissionState(task, steps = task?.steps || []) {
  const records = Array.isArray(steps) ? steps.filter(step => step && typeof step === 'object') : [];
  const current = records.find(step => step.status === 'running');
  const unresolved = records.some(step => !['completed', 'skipped'].includes(step.status));
  const validation = task?.validation;
  const review = task?.design_review;
  const contradictory = Boolean(unresolved || task?.error
    || (validation && (validation.passed === false || ['failed', 'incomplete', 'unavailable'].includes(validation.status)))
    || (review && (review.passed !== true || review.status !== 'passed')));
  const complete = task?.status === 'completed' && !contradictory;
  const inconsistent = task?.status === 'completed' && contradictory;
  const designFailed = task?.status === 'incomplete' && review?.status === 'violated'
    && validation?.status === 'passed' && validation?.passed === true && !task?.error
    && records.length > 0 && records.every(step => step.step_id === 'design_review' || ['completed', 'skipped'].includes(step.status));
  return {
    current, complete, inconsistent, completed: records.filter(step => step.status === 'completed').length,
    label: inconsistent ? '记录状态需要核对' : designFailed ? '未满足设计指标' : taskStatusLabel(task?.status),
    status: inconsistent ? 'inconsistent' : designFailed ? 'design_failed' : task?.status || 'unknown',
    english: inconsistent ? 'RECORD NEEDS REVIEW' : designFailed ? HYPER_STATUS.design_failed : HYPER_STATUS[task?.status] || 'STATE UNCONFIRMED',
  };
}

export function hyperMissionReference(taskId) {
  return typeof taskId === 'string' && taskId ? taskId.split('_').at(-1).slice(-8).toUpperCase() : 'UNASSIGNED';
}

export function designReviewStatus(status) {
  return { passed: '满足已声明上限', violated: '超出设计上限', unavailable: '缺少计算证据' }[status] || '结果未确认';
}

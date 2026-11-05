import { indexStatusPresentation } from './adminPresentation.js';

export function revisionIndexStatus(value) {
  if (value === 'synced') return { label: '无待同步修订', color: 'default' };
  if (!value || value === 'unknown') return { label: '修订状态未获取', color: 'default' };
  return indexStatusPresentation(value);
}

export function knownCount(value) {
  return Number.isInteger(value) && value >= 0 ? value : null;
}

export function coverageView(data) {
  const active = knownCount(data?.active_chunks);
  const indexed = knownCount(data?.indexed_active_chunks);
  const missing = knownCount(data?.missing_chunks);
  const known = active !== null && indexed !== null && missing !== null && indexed + missing === active && ['gap', 'covered'].includes(data?.status);
  return {
    active, indexed, missing, known,
    percent: known && active > 0 ? Math.min(100, Math.max(0, indexed / active * 100)) : null,
    status: known ? data.status : 'unknown',
    label: !known ? '覆盖状态未获取' : data.status === 'gap' ? '存在检索覆盖缺口' : '片段映射已覆盖',
    description: !known ? '需要成功读取知识库和当前索引映射后才能确定覆盖。'
      : missing > 0 ? `${missing} 个有效片段尚未进入当前索引映射。文档入库不等于已可检索。`
        : data.status === 'gap' ? '当前有效片段已有映射，但索引仍含失效片段映射，需要复核。'
        : '当前有效片段均有索引映射；检索相关性与答案质量仍需单独验证。',
  };
}

const STATUSES = {
  queued: ['等待执行', 'default'], running: ['执行中', 'processing'], completed: ['已完成', 'success'],
  blocked: ['等待补充', 'warning'], failed: ['失败', 'error'], incomplete: ['未完成', 'warning'],
  interrupted: ['已中断', 'warning'], cancelled: ['已取消', 'default'], pending: ['待执行', 'default'],
  skipped: ['已跳过', 'default'], succeeded: ['已完成', 'success'],
};

export function taskStatus(status) {
  const [label, color] = STATUSES[status] || ['状态未知', 'default'];
  return { label, color };
}

export function taskProgress(task) {
  const total = knownCount(task?.step_summary?.total);
  const completed = knownCount(task?.step_summary?.completed);
  if (total === null || completed === null || completed > total) return { text: '步骤未获取', percent: null };
  return { text: `${completed} / ${total} 步骤`, percent: total > 0 ? completed / total * 100 : 0 };
}

export function monitorTotal(data) {
  return data?.store_available === false ? null : knownCount(data?.total);
}

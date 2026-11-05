// This is a presentation of saved execution facts, never an estimated stage.
export function assistantBrief(task, loading = false) {
  const current = task?.steps?.find(step => step.status === 'running');
  const completed = task?.steps?.filter(step => step.status === 'completed').length || 0;
  const total = task?.steps?.length || 0;
  const states = {
    completed: ['COMPLETE', '分析完成，可以查看工程报告。'],
    blocked: ['INPUT REQUIRED', '还缺少必要条件，请补充任务参数。'],
    failed: ['ATTENTION', '执行未完成，请查看保存的异常记录。'],
    incomplete: ['EVIDENCE GAP', '计算记录已保留，部分证据仍需补全。'],
    cancelled: ['CANCELLED', '任务已取消，已完成记录仍可查看。'],
    interrupted: ['INTERRUPTED', '执行已中断，请核对记录后决定是否重试。'],
    queued: ['QUEUED', '任务已受理，正在等待执行。'],
    running: ['IN PROGRESS', current ? `正在执行：${current.title || current.step_id}` : '正在读取任务执行状态。'],
  };
  const [label, message] = states[task?.status] || (task ? ['UNCONFIRMED', '任务状态尚未确认，请从历史记录核对。'] : loading ? ['AWAITING RESPONSE', '正在等待服务响应。'] : ['STANDBY', '准备好了。告诉我目标、参数与约束。']);
  return { label, message, current, completed, total, active: task?.status === 'running' && Boolean(current), id: task?.task_id ? task.task_id.replace(/^task_/, '').slice(-8).toUpperCase() : null };
}

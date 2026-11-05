// Presentation of received execution facts. No timer, inferred progress or tool execution.
const TERMINAL = new Set(['completed', 'failed', 'blocked', 'incomplete', 'cancelled', 'interrupted']);
const BUSY = new Set(['queued', 'planned', 'pending', 'running', 'cancelling']);
const TEXT = {
  idle: ['STANDBY', '下一页，从你开始', '把目标和参数写下来，我们一起把想法变成可复核的设计。'],
  llm: ['RESPONSE WAIT', '等待回复', '正在等待当前请求的服务响应，尚未收到执行阶段回执。'],
  planning: ['MISSION CONTROL', '任务准备', '任务已受理，等待执行步骤更新。'],
  retrieval: ['KNOWLEDGE LINK', '知识检索', '正在检索知识与来源。结论以实际返回的证据为准。'],
  calculation: ['COMPUTE ENGINE', '工程计算', '计算工具正在执行，结果与单位将在返回后展示。'],
  matlab: ['MATLAB RUN', 'MATLAB 执行', '已收到 MATLAB 执行中的状态，等待求解器返回。'],
  validation: ['PHYSICS CHECK', '物理验证', '正在执行已配置的检查，尚未得到验证结论。'],
  warning: ['CHECK REQUIRED', '需要核对', '请核对输入、来源或约束；现有记录仍可查看。'],
  failed: ['MISSION INTERRUPTED', '执行异常', '执行未完成。请查看异常记录，核对后再决定是否重试。'],
  complete: ['MISSION COMPLETE', '任务已完成', '执行记录已保存。查看报告、来源和适用范围后再使用结论。'],
};

function stageFromStep(step) {
  const tool = typeof step?.tool_name === 'string' ? step.tool_name.toLowerCase() : '';
  const id = typeof step?.step_id === 'string' ? step.step_id.toLowerCase() : '';
  if (tool.includes('matlab')) return 'matlab';
  if (tool.includes('validation') || tool.includes('physics') || id === 'validation' || id === 'design_review') return 'validation';
  if (tool.includes('retriev') || id === 'retrieval') return 'retrieval';
  if (tool.includes('calculation') || tool.includes('reference') || /flow|pressure|resistance|conduction|thermal/.test(tool) || /calculation|flow|pressure/.test(id)) return 'calculation';
  if (id === 'report' || tool.includes('report') || tool.includes('llm')) return 'llm';
  return 'planning';
}

export function resolveHyperState({ task, loading = false, pendingMessage, latestMessage, mode } = {}) {
  const pending = pendingMessage && typeof pendingMessage === 'object' ? pendingMessage : null;
  let currentTask = task;
  if (loading && pending) {
    // A new request without its own receipt must never borrow an older task.
    currentTask = pending.taskSnapshot || (pending.taskId && pending.taskId === task?.task_id ? task : null);
  } else if (loading && TERMINAL.has(task?.status)) currentTask = null;
  const status = currentTask?.status;
  const steps = Array.isArray(currentTask?.steps) ? currentTask.steps : [];
  // A failed observation or restored pending message is not a live task update.
  const responseError = !loading && Boolean(latestMessage?.error || latestMessage?.isError || latestMessage?.raw?.error);
  const historicalPending = !loading && latestMessage?.pending === true;
  const current = !responseError && !historicalPending && ['running', 'cancelling'].includes(status) ? steps.find(step => step?.status === 'running') || null : null;
  let state = 'idle', busy = false, detail;
  if (responseError) {
    state = 'failed';
    detail = '当前响应报告异常。保存的快照不代表当前执行状态，请从任务档案核对。';
  } else if (historicalPending) {
    state = 'warning';
    detail = '这是历史等待记录，当前没有活动请求。请从任务档案刷新核对状态。';
  } else if (status === 'failed' || status === 'interrupted') state = 'failed';
  else if (['blocked', 'incomplete', 'cancelled'].includes(status)) {
    state = 'warning';
    detail = status === 'blocked' ? '还缺少必要参数。补全后才能继续工程分析。' : status === 'cancelled' ? '任务已取消，已保存的执行记录仍可查看。' : '部分证据或设计条件尚未满足，请查看任务中的具体说明。';
  } else if (status === 'completed') state = 'complete';
  else if (BUSY.has(status)) {
    busy = true;
    state = current ? stageFromStep(current) : 'planning';
    detail = status === 'cancelling' ? '已请求取消，等待执行边界确认。' : current ? `当前步骤：${current.title || current.step_id || '等待步骤名称'}${current.tool_name ? ` · ${current.tool_name}` : ''}` : status === 'queued' ? '任务正在排队，还没有开始执行计算。' : '等待服务返回当前执行步骤。';
  } else if (currentTask) {
    state = 'warning';
    detail = '任务状态尚未确认，请从任务记录核对。';
  } else if (loading || pending?.pending === true) {
    busy = true;
    const requestMode = pending?.mode || mode;
    const confirmedMatlab = pending?.simulationAction === 'confirm' && pending?.simulationBackend === 'matlab';
    state = confirmedMatlab ? 'matlab' : requestMode === 'task' ? 'planning' : 'llm';
    detail = confirmedMatlab ? '已确认 MATLAB 计划，正在等待本次执行响应。' : requestMode === 'task' ? '正在等待本次任务提交回执，尚未确认执行步骤。' : undefined;
  }
  if (!loading && !busy && !responseError && !historicalPending) {
    const response = latestMessage?.raw, metadata = response?.metadata;
    const run = metadata?.engineering_run, execution = metadata?.simulation_execution;
    const validations = [metadata?.physics_validation, run?.validation, metadata?.calculation?.raw?.physics_validation, metadata?.calculation_result?.physics_validation];
    const critic = execution?.evidence?.result_critic;
    const invalid = validations.some(validation => validation?.passed === false || ['failed', 'incomplete', 'warning', 'blocked'].includes(validation?.status)) || ['fail', 'failed', 'reject', 'warning', 'incomplete'].includes(critic?.verdict) || critic?.analytical_check?.cross_check?.passed === false;
    const failedStep = Array.isArray(run?.steps) && run.steps.some(step => step?.status === 'failed');
    if (latestMessage?.error || latestMessage?.isError || response?.error || execution?.status === 'failed' || run?.status === 'failed' || failedStep || (Array.isArray(execution?.errors) && execution.errors.length > 0)) {
      state = 'failed'; detail = undefined;
    } else if (invalid || ['blocked', 'incomplete', 'cancelled', 'interrupted'].includes(run?.status) || run?.persistence?.status === 'failed') {
      state = 'warning'; detail = '执行记录存在需要核对的输入、证据或校验项，请查看结果中的具体说明。';
    } else if (!['failed', 'warning'].includes(state) && run?.status === 'completed') {
      state = 'complete'; detail = '工程计算记录已返回。请核对报告、来源、单位与适用范围。';
    } else if (!['failed', 'warning'].includes(state) && execution?.status === 'completed' && execution.executed === true && execution.result) {
      state = 'complete';
      const mock = metadata?.matlab?.execution_mode === 'mock' || execution?.evidence?.execution_mode === 'mock' || execution.solver_backend === 'mock';
      detail = mock ? 'Mock 求解已返回。查看结果与校验证据；它不代表真实 CFD 仿真。' : '求解器已返回结果。请在执行证据中核对后端、运行模式和验证范围。';
    }
  }
  const [label, title, fallback] = TEXT[state];
  return { state, busy, label, title, detail: detail || fallback, current, taskId: typeof currentTask?.task_id === 'string' ? currentTask.task_id : null, taskStatus: status || null };
}

export const HYPER_MOTION_KEY = 'thermalagent.hyperMotion.v1';
export function readHyperMotion(storage) {
  try { const selected = storage === undefined ? globalThis.localStorage : storage; return { enabled: selected?.getItem(HYPER_MOTION_KEY) !== 'off', persistent: !!selected }; }
  catch { return { enabled: true, persistent: false }; }
}

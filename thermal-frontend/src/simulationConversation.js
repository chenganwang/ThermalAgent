export function simulationMetadata(response) {
  const metadata = response?.metadata && typeof response.metadata === 'object' ? response.metadata : {};
  return {
    mode: metadata.simulation_mode || {},
    plan: metadata.simulation_plan || {},
    execution: metadata.simulation_execution || {},
    matlab: metadata.matlab || {},
  };
}

export function buildSimulationActionRequest({ action, planId }) {
  const queryByAction = {
    confirm: '确认执行',
    cancel: '取消仿真',
    revise: '修改仿真计划',
    status: '查看仿真状态',
  };
  return {
    query: queryByAction[action] || '查看仿真状态',
    simulationMode: true,
    simulationAction: action,
    simulationPlanId: planId || null,
  };
}

export function buildSimulationRevisionRequest({ query, planId }) {
  const text = String(query || '').trim();
  if (!text) return null;
  return { ...buildSimulationActionRequest({ action: 'revise', planId }), query: text };
}

export function hasSimulationAttachment(response) {
  const { plan, execution } = simulationMetadata(response);
  return Boolean(
    plan.generated
    || execution.executed
    || (Array.isArray(execution.errors) && execution.errors.length > 0)
    || (execution.status && execution.status !== 'not_started'),
  );
}

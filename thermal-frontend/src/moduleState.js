export const MODULE_DEFINITIONS = Object.freeze([
  Object.freeze({ id: 'chat', capabilityKey: null }),
  Object.freeze({ id: 'report', capabilityKey: 'report_generation' }),
  Object.freeze({ id: 'simulation', capabilityKey: 'simulation' }),
]);

export const DEFAULT_MODULE_VISIBILITY = Object.freeze({
  chat: true,
  report: true,
  simulation: true,
});

export const DEFAULT_MODULE_ENABLED = Object.freeze({
  chat: true,
  report: false,
  simulation: false,
});

function booleanField(value, field, fallback) {
  const candidate = value?.[field];
  return typeof candidate === 'boolean' ? candidate : fallback;
}

function unavailableReason(id, capability, error) {
  if (id === 'simulation' && capability?.message === 'Simulation UI requested execution, but backend MATLAB integration guards are still blocking it.') {
    return 'MATLAB 仿真暂不可用，可继续问答、工程计算和 Mock CFD。';
  }
  if (capability?.message) return capability.message;
  if (error) return `后端未连接：${error}`;
  if (id === 'simulation') return 'MATLAB 仿真服务尚未准备完成。';
  if (id === 'report') return '报告生成接口当前不可用。';
  return '后端功能尚未启用。';
}

function resolveStatus(id, capability, { enabled, visible, loading, error }) {
  if (id === 'chat') {
    return { status: 'available', reason: '对话功能可用。' };
  }
  if (!visible) {
    return { status: 'hidden', reason: '管理员已明确隐藏该模块。' };
  }
  if (!capability) {
    if (loading) return { status: 'loading', reason: '正在检查后端功能状态。' };
    return { status: 'backend_unavailable', reason: unavailableReason(id, capability, error) };
  }
  if (enabled) {
    return { status: 'available', reason: capability.message || '后端功能已就绪。' };
  }
  if (id === 'simulation' && capability.ui_enabled_requested === true && capability.backend_guard_passed === false) {
    return { status: 'backend_guard_blocked', reason: unavailableReason(id, capability, error) };
  }
  if (id === 'report' && capability.backend_available === false) {
    return { status: 'backend_unavailable', reason: unavailableReason(id, capability, error) };
  }
  return { status: 'feature_disabled', reason: unavailableReason(id, capability, error) };
}

export function buildModuleStates({
  capabilities = null,
  loading = false,
  error = '',
  useMockResponses = false,
} = {}) {
  return MODULE_DEFINITIONS.map(({ id, capabilityKey }) => {
    const capability = capabilityKey ? capabilities?.[capabilityKey] : null;
    const visible = useMockResponses
      ? true
      : booleanField(capability, 'show_in_frontend', DEFAULT_MODULE_VISIBILITY[id]);
    const enabled = visible && (useMockResponses
      ? true
      : booleanField(capability, 'enabled', DEFAULT_MODULE_ENABLED[id]));
    const statusDetails = useMockResponses
      ? { status: 'mock', reason: '使用本地 Mock 数据。' }
      : resolveStatus(id, capability, { enabled, visible, loading, error });

    return {
      id,
      visible,
      enabled,
      loading: Boolean(loading && id !== 'chat'),
      ...statusDetails,
    };
  });
}

export function moduleStateById(moduleStates, id) {
  return moduleStates.find(moduleState => moduleState.id === id);
}

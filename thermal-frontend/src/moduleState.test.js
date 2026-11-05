import assert from 'node:assert/strict';
import test from 'node:test';

import { notifyCapabilitiesChanged, subscribeCapabilitiesChanged } from './capabilityEvents.js';
import { buildModuleStates, moduleStateById } from './moduleState.js';

function states(options) {
  const result = buildModuleStates(options);
  return Object.fromEntries(result.map(moduleState => [moduleState.id, moduleState]));
}

test('未连接后端时三个模块都显示', () => {
  const result = buildModuleStates({ capabilities: null, loading: false });
  assert.deepEqual(result.filter(item => item.visible).map(item => item.id), ['chat', 'report', 'simulation']);
});

test('未连接后端时报告和仿真禁用', () => {
  const result = states({ capabilities: null, error: 'connection refused' });
  assert.equal(result.chat.enabled, true);
  assert.equal(result.report.enabled, false);
  assert.equal(result.simulation.enabled, false);
  assert.equal(result.report.status, 'backend_unavailable');
});

test('capabilities loading 不清空模块', () => {
  const result = states({ capabilities: null, loading: true });
  assert.equal(result.report.visible, true);
  assert.equal(result.simulation.visible, true);
  assert.equal(result.report.loading, true);
  assert.equal(result.simulation.status, 'loading');
});

test('刷新 loading 保留已知模块状态', () => {
  const result = states({
    loading: true,
    capabilities: {
      report_generation: { show_in_frontend: true, enabled: true },
      simulation: { show_in_frontend: true, enabled: false },
    },
  });
  assert.equal(result.report.visible, true);
  assert.equal(result.report.enabled, true);
  assert.equal(result.simulation.visible, true);
});

test('capabilities 请求失败时保留三个模块', () => {
  const result = buildModuleStates({ capabilities: null, error: 'network error' });
  assert.deepEqual(result.filter(item => item.visible).map(item => item.id), ['chat', 'report', 'simulation']);
});

test('缺失 show_in_frontend 使用安全可见 fallback', () => {
  const result = states({ capabilities: { report_generation: { enabled: false }, simulation: {} } });
  assert.equal(result.report.visible, true);
  assert.equal(result.simulation.visible, true);
});

test('show_in_frontend=true enabled=false 时显示但禁用', () => {
  const result = states({ capabilities: { report_generation: { show_in_frontend: true, enabled: false } } });
  assert.equal(result.report.visible, true);
  assert.equal(result.report.enabled, false);
});

test('show_in_frontend=false 时隐藏', () => {
  const result = states({ capabilities: { simulation: { show_in_frontend: false, enabled: true } } });
  assert.equal(result.simulation.visible, false);
  assert.equal(result.simulation.enabled, false);
});

test('enabled 不决定 visibility', () => {
  const result = states({ capabilities: { simulation: { enabled: true } } });
  assert.equal(result.simulation.visible, true);
  assert.equal(result.simulation.enabled, true);
});

test('读取 simulation 和 report_generation 正确层级', () => {
  const result = states({
    capabilities: {
      report: { show_in_frontend: false, enabled: false },
      report_generation: { show_in_frontend: true, enabled: true },
      simulation: { show_in_frontend: true, enabled: false },
    },
  });
  assert.equal(result.report.enabled, true);
  assert.equal(result.simulation.enabled, false);
});

test('管理员 PATCH visible=true 后模块立即可见', () => {
  const before = states({ capabilities: { simulation: { show_in_frontend: false, enabled: false } } });
  const after = states({ capabilities: { simulation: { show_in_frontend: true, enabled: false } } });
  assert.equal(before.simulation.visible, false);
  assert.equal(after.simulation.visible, true);
});

test('管理员 PATCH/reset 成功事件会触发 capabilities 刷新', () => {
  const target = new EventTarget();
  let refreshCount = 0;
  const unsubscribe = subscribeCapabilitiesChanged(() => { refreshCount += 1; }, target);
  assert.equal(notifyCapabilitiesChanged(target), true);
  assert.equal(refreshCount, 1);
  unsubscribe();
  notifyCapabilitiesChanged(target);
  assert.equal(refreshCount, 1);
});

test('管理员 PATCH visible=false 后模块隐藏', () => {
  const result = states({ capabilities: { report_generation: { show_in_frontend: false, enabled: false } } });
  assert.equal(result.report.visible, false);
});

test('reset 后恢复默认可见且默认禁用', () => {
  const result = states({ capabilities: null });
  assert.equal(result.report.visible, true);
  assert.equal(result.report.enabled, false);
  assert.equal(result.simulation.visible, true);
  assert.equal(result.simulation.enabled, false);
});

test('backend guard false 时仿真不可点击并报告原因', () => {
  const result = states({
    capabilities: {
      simulation: {
        show_in_frontend: true,
        enabled: false,
        ui_enabled_requested: true,
        backend_guard_passed: false,
      },
    },
  });
  assert.equal(result.simulation.enabled, false);
  assert.equal(result.simulation.status, 'backend_guard_blocked');
});

test('report backend unavailable 时报告不可点击', () => {
  const result = states({
    capabilities: {
      report_generation: { show_in_frontend: true, enabled: false, backend_available: false },
    },
  });
  assert.equal(result.report.enabled, false);
  assert.equal(result.report.status, 'backend_unavailable');
});

test('对话模块始终存在且可用', () => {
  const result = buildModuleStates({
    capabilities: {
      report_generation: { show_in_frontend: false, enabled: false },
      simulation: { show_in_frontend: false, enabled: false },
    },
  });
  const chat = moduleStateById(result, 'chat');
  assert.equal(chat.visible, true);
  assert.equal(chat.enabled, true);
});

test('known MATLAB guard message uses readable guidance without enabling the module or hiding other errors', () => {
  const original = { show_in_frontend: true, enabled: false, ui_enabled_requested: true, backend_guard_passed: false, message: 'Simulation UI requested execution, but backend MATLAB integration guards are still blocking it.' };
  const mapped = states({ capabilities: { simulation: original } }).simulation;
  assert.equal(mapped.enabled, false);
  assert.equal(mapped.status, 'backend_guard_blocked');
  assert.equal(mapped.reason, 'MATLAB 仿真暂不可用，可继续问答、工程计算和 Mock CFD。');
  assert.match(original.message, /^Simulation UI/);
  const unknown = states({ capabilities: { simulation: { ...original, message: 'Unrecognized model validation error' } } }).simulation;
  assert.equal(unknown.reason, 'Unrecognized model validation error');
});

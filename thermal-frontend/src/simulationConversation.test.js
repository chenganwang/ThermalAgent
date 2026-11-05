import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

import {
  buildSimulationActionRequest,
  buildSimulationRevisionRequest,
  hasSimulationAttachment,
  simulationMetadata,
} from './simulationConversation.js';
import { buildKnowledgeSourcesPresentation, buildSimulationPresentation } from './simulationPresentation.js';


const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: SimulationMessageAttachments } = await vite.ssrLoadModule('/src/SimulationMessageAttachments.jsx');
const { default: SimulationModeToggle } = await vite.ssrLoadModule('/src/SimulationModeToggle.jsx');
const { default: SimulationPlanCard } = await vite.ssrLoadModule('/src/SimulationPlanCard.jsx');
const { default: KnowledgeSourcesDisclosure } = await vite.ssrLoadModule('/src/KnowledgeSourcesDisclosure.jsx');
after(() => vite.close());


test('completed message renders result and execution evidence without repeating its preserved plan', () => {
  const response = {
    query: '确认执行',
    metadata: {
      simulation_mode: { enabled: true, state: 'completed', confirmed: true, executed: true },
      simulation_plan: {
        generated: true,
        plan_id: 'sim-result',
        selected_model_id: 'plane_wall_steady_v1',
        selected_model_name: '平壁稳态导热',
        model_version: '1.0.0',
        inputs: {
          thickness_m: 0.005,
          thermal_conductivity_w_mk: 16,
          area_m2: 0.002,
          delta_temperature_k: 60,
        },
      },
      matlab: { uses_real_matlab: true, execution_mode: 'real', matlab_version: '2025a' },
      simulation_execution: {
        executed: true,
        status: 'completed',
        solver_backend: 'matlab',
        duration_seconds: 0.045,
        result: {
          temperature_difference_k: 60,
          heat_rate_w: 384,
          heat_flux_w_m2: 192000,
          formula: 'Q=k*A*delta_T/L',
          model_id: 'plane_wall_steady_v1',
          model_version: '1.0.0',
        },
        evidence: { model_version: '1.0.0' },
        errors: [],
        cfd_executed: false,
      },
    },
  };

  const view = buildSimulationPresentation(response, { action: 'confirm' });
  assert.equal(view.showPlan, false);
  assert.equal(view.showResult, true);
  assert.equal(view.showEvidence, true);
  assert.equal(view.result.fields.find(field => field.key === 'heat_rate_w').display, '384 W');
  assert.equal(view.result.fields.find(field => field.key === 'heat_flux_w_m2').display, '192,000 W/m²');
  assert.equal(view.evidence.modeLabel, '真实 MATLAB');
  assert.equal(view.evidence.cfdLabel, 'CFD 未执行');

  const html = renderToStaticMarkup(
    React.createElement(SimulationMessageAttachments, { response, eventAction: 'confirm' }),
  );
  assert.equal((html.match(/data-testid="simulation-plan-card"/g) || []).length, 0);
  assert.equal((html.match(/data-testid="simulation-result-card"/g) || []).length, 1);
  assert.equal((html.match(/data-testid="execution-evidence-card"/g) || []).length, 1);
  assert.match(html, /热流率/);
  assert.match(html, /384 W/);
  assert.match(html, /热流密度/);
  assert.match(html, /192,000 W\/m²/);
  assert.match(html, /真实 MATLAB/);
  assert.match(html, /CFD 未执行/);
  assert.doesNotMatch(html, /thermal_conductivity_w_mk|heat_flux_w_m2|delta_temperature_k|\{&#x27;heat_rate_w&#x27;:/);
});

test('generated-model result renders bounded logical outputs and independent validation evidence', () => {
  const response = {
    query: '确认执行',
    metadata: {
      simulation_mode: { enabled: true, state: 'completed', confirmed: true, executed: true },
      simulation_plan: {
        generated: true,
        plan_id: 'sim-generated-result',
        model_source: 'generated',
        selected_model_id: 'generated_thermal_model',
      },
      matlab: { uses_real_matlab: true, execution_mode: 'real', matlab_version: '2025a' },
      simulation_execution: {
        executed: true,
        status: 'completed',
        solver_backend: 'matlab',
        result: {
          model_id: 'generated_thermal_model',
          solver_status: 'completed',
          outputs: [{
            logical_output_id: 'wall_heat_flow',
            quantity: 'heat_flow_rate',
            value: 384,
            unit: 'W',
            status: 'ok',
          }],
        },
        evidence: {
          result_critic: {
            verdict: 'pass',
            validation_level: 'analytical',
            analytical_check: {
              status: 'PASS',
              cross_check: { expected: 384, actual: 384, absolute_error: 0, relative_error: 0, tolerance: 0.384, passed: true },
            },
          },
          workspace_variable: 'tao_should_not_render',
        },
        errors: [],
        cfd_executed: false,
      },
    },
  };

  const view = buildSimulationPresentation(response, { action: 'confirm' });
  assert.equal(view.result.fields[0].display, '384 W');
  assert.equal(view.evidence.criticLabel, '解析校验通过');
  assert.equal(view.evidence.analyticalStatus, '通过');
  assert.equal(view.evidence.expectedLabel, '384 W');
  assert.equal(view.evidence.actualLabel, '384 W');
  assert.equal(view.evidence.relativeErrorLabel, '0%');

  const html = renderToStaticMarkup(
    React.createElement(SimulationMessageAttachments, { response, eventAction: 'confirm' }),
  );
  assert.match(html, /热流率/);
  assert.match(html, /384 W/);
  assert.match(html, /Result Critic/);
  assert.match(html, /解析校验通过/);
  assert.match(html, /解析期望值/);
  assert.match(html, /相对误差/);
  assert.doesNotMatch(html, /wall_heat_flow|tao_should_not_render|workspace_variable|logical_output_id/);
});

test('generated draft remains a visible plan while it waits for compile and Admin approval', () => {
  const response = {
    metadata: {
      simulation_mode: { enabled: true, state: 'blocked', confirmed: false, errors: [] },
      simulation_plan: {
        generated: true,
        plan_id: 'sim-generated-draft',
        model_source: 'generated',
        selected_model_id: 'generated_thermal_model',
        generated_model_status: 'draft',
        selection_reason: 'no_catalog_match:generated_model_candidate',
        solver_backend: 'matlab',
        execution_allowed: false,
        execution_block_reason: 'GENERATED_MODEL_APPROVAL_REQUIRED',
        missing_inputs: [],
      },
      simulation_execution: { executed: false, status: 'not_started', errors: [] },
    },
  };
  const view = buildSimulationPresentation(response);
  assert.equal(view.showPlan, true);
  assert.equal(view.showError, false);
  assert.equal(view.plan.generatedStatusLabel, '待编译');
  const html = renderToStaticMarkup(React.createElement(SimulationMessageAttachments, { response }));
  assert.match(html, /待编译/);
  assert.match(html, /需管理员审核并启用/);
  assert.doesNotMatch(html, /仿真执行失败/);
});

test('plan presentation uses one Chinese label and engineering-unit mapping without internal identifiers', () => {
  const response = {
    metadata: {
      simulation_mode: { enabled: true, state: 'pending_confirmation', pending_confirmation: true, confirm_allowed: true },
      simulation_plan: {
        generated: true,
        plan_id: 'sim-plan-format',
        objective: '评估平壁稳态导热',
        selected_model_id: 'plane_wall_steady_v1',
        selected_model_name: '平壁稳态导热',
        selection_reason: 'exact_scenario_and_keyword_match:plane_wall_steady_conduction',
        solver_backend: 'matlab',
        inputs: {
          thickness_m: 0.005,
          thermal_conductivity_w_mk: 16,
          area_m2: 0.002,
          delta_temperature_k: 60,
        },
        missing_inputs: [],
        execution_allowed: true,
        can_execute_now: true,
      },
      matlab: { available: true },
      simulation_execution: { executed: false, status: 'not_started', errors: [] },
    },
  };
  const html = renderToStaticMarkup(
    React.createElement(SimulationMessageAttachments, { response, onAction: () => {} }),
  );
  assert.match(html, /壁厚/);
  assert.match(html, /5 mm/);
  assert.match(html, /导热系数/);
  assert.match(html, /16 W\/\(m·K\)/);
  assert.match(html, /面积/);
  assert.match(html, /0.002 m²/);
  assert.match(html, /两侧温差/);
  assert.match(html, /60 K/);
  assert.match(html, /场景与关键词匹配/);
  assert.equal((html.match(/data-testid="simulation-plan-card"/g) || []).length, 1);
  assert.equal((html.match(/data-testid="simulation-result-card"/g) || []).length, 0);
  assert.doesNotMatch(html, /thickness_m|thermal_conductivity_w_mk|area_m2|delta_temperature_k|exact_scenario_and_keyword_match/);
});

test('completed presentation replaces raw result dict and keeps knowledge sources optional and separate', () => {
  const response = {
    answer: "仿真已执行完成。结果：{'heat_rate_w': 384, 'heat_flux_w_m2': 192000}",
    metadata: {
      simulation_mode: { enabled: true, state: 'completed', confirmed: true, executed: true },
      simulation_plan: { generated: true, selected_model_id: 'plane_wall_steady_v1', selected_model_name: '平壁稳态导热' },
      simulation_execution: {
        executed: true,
        status: 'completed',
        solver_backend: 'matlab',
        result: { heat_rate_w: 384, heat_flux_w_m2: 192000 },
        errors: [],
        cfd_executed: false,
      },
      matlab: { uses_real_matlab: true },
    },
  };
  const view = buildSimulationPresentation(response, { action: 'confirm' });
  assert.match(view.summary, /热流率为 384 W/);
  assert.match(view.summary, /热流密度为 192,000 W\/m²/);
  assert.doesNotMatch(view.summary, /\{|heat_rate_w|heat_flux_w_m2/);

  const sources = buildKnowledgeSourcesPresentation([
    { title: 'Heat Transfer Handbook', section: 'Steady conduction', page_start: 12, text_preview: 'x'.repeat(400) },
  ], { relatedToSimulation: true });
  assert.equal(sources.title, '相关知识来源（可选）');
  assert.equal(sources.items.length, 1);
  assert.equal(sources.items[0].locator, 'Steady conduction · 第 12 页');
  assert.ok(sources.items[0].preview.length <= 221);
  assert.notEqual(sources.title, '执行证据');
});

test('execution badges and CFD state distinguish real, mock, preparation-only, and executed CFD', () => {
  function response({ executed = true, usesReal = false, executionMode = 'mock', cfd = false } = {}) {
    return {
      metadata: {
        simulation_mode: { enabled: true, state: executed ? 'completed' : 'pending_confirmation' },
        simulation_plan: { generated: true, selected_model_id: 'plane_wall_steady_v1' },
        simulation_execution: {
          executed,
          status: executed ? 'completed' : 'not_started',
          solver_backend: 'matlab',
          result: executed ? { heat_rate_w: 384 } : {},
          cfd_executed: cfd,
          errors: [],
        },
        matlab: { uses_real_matlab: usesReal, execution_mode: executionMode },
      },
    };
  }
  assert.equal(buildSimulationPresentation(response({ usesReal: true, executionMode: 'real' })).evidence.modeLabel, '真实 MATLAB');
  assert.equal(buildSimulationPresentation(response()).evidence.modeLabel, '测试 Mock');
  assert.equal(buildSimulationPresentation(response({ executed: false })).evidence.modeLabel, '仅生成仿真计划，尚未执行');
  assert.equal(buildSimulationPresentation(response({ cfd: false })).evidence.cfdLabel, 'CFD 未执行');
  assert.equal(buildSimulationPresentation(response({ cfd: true })).evidence.cfdLabel, 'CFD 已执行');
  const durationResponse = response({ usesReal: true, executionMode: 'real' });
  durationResponse.metadata.simulation_execution.duration_seconds = 0.033325299998978;
  assert.equal(buildSimulationPresentation(durationResponse).evidence.durationLabel, '33.3 ms');
});

test('failed attachment explains known error in Chinese and keeps its code secondary', () => {
  const response = {
    metadata: {
      simulation_mode: { enabled: true, state: 'failed' },
      simulation_plan: { generated: true, selected_model_id: 'plane_wall_steady_v1' },
      simulation_execution: {
        executed: false,
        status: 'failed',
        errors: [{ code: 'MATLAB_TIMEOUT', message: 'MATLAB future timed out.' }],
      },
    },
  };
  const html = renderToStaticMarkup(React.createElement(SimulationMessageAttachments, { response, eventAction: 'confirm' }));
  assert.match(html, /MATLAB 求解超时/);
  assert.match(html, /MATLAB 求解在规定时间内未完成/);
  assert.match(html, /错误代码：MATLAB_TIMEOUT/);
  assert.equal((html.match(/data-testid="simulation-plan-card"/g) || []).length, 0);
});

test('status message uses a compact status attachment instead of copying the current plan', () => {
  const response = {
    metadata: {
      simulation_mode: { enabled: true, state: 'pending_confirmation', pending_confirmation: true },
      simulation_plan: { generated: true, plan_id: 'sim-status', selected_model_id: 'plane_wall_steady_v1' },
      simulation_execution: { executed: false, status: 'not_started', errors: [] },
    },
  };
  const html = renderToStaticMarkup(
    React.createElement(SimulationMessageAttachments, { response, eventAction: 'status' }),
  );
  assert.match(html, /等待确认/);
  assert.equal((html.match(/data-testid="simulation-status"/g) || []).length, 1);
  assert.equal((html.match(/data-testid="simulation-plan-card"/g) || []).length, 0);
});

test('conversation history keeps one old plan and adds one result without a copied execution plan', () => {
  const planResponse = {
    metadata: {
      simulation_mode: { enabled: true, state: 'pending_confirmation', pending_confirmation: true, confirm_allowed: true },
      simulation_plan: { generated: true, plan_id: 'sim-history', can_execute_now: true, execution_allowed: true, missing_inputs: [] },
      simulation_execution: { executed: false, status: 'not_started', errors: [] },
    },
  };
  const resultResponse = {
    metadata: {
      simulation_mode: { enabled: true, state: 'completed', confirmed: true, executed: true },
      simulation_plan: { generated: true, plan_id: 'sim-history', selected_model_id: 'plane_wall_steady_v1' },
      simulation_execution: { executed: true, status: 'completed', result: { heat_rate_w: 384 }, errors: [], cfd_executed: false },
    },
  };
  const html = renderToStaticMarkup(React.createElement(
    React.Fragment,
    null,
    React.createElement(SimulationMessageAttachments, { response: planResponse, actionsEnabled: false }),
    React.createElement(SimulationMessageAttachments, { response: resultResponse, eventAction: 'confirm' }),
  ));
  assert.equal((html.match(/data-testid="simulation-plan-card"/g) || []).length, 1);
  assert.equal((html.match(/data-testid="simulation-result-card"/g) || []).length, 1);
  assert.equal((html.match(/data-testid="execution-evidence-card"/g) || []).length, 1);
});

test('known simulation errors use human titles while internal codes remain secondary', () => {
  for (const [code, title] of [
    ['SIMULATION_INPUTS_INCOMPLETE', '还需要补充仿真参数'],
    ['MATLAB_TIMEOUT', 'MATLAB 求解超时'],
    ['MATLAB_EXECUTION_ERROR', 'MATLAB 执行失败'],
  ]) {
    const response = {
      metadata: {
        simulation_mode: { enabled: true, state: 'failed' },
        simulation_plan: { generated: true },
        simulation_execution: { executed: false, status: 'failed', errors: [{ code, message: 'internal' }] },
      },
    };
    const html = renderToStaticMarkup(React.createElement(SimulationMessageAttachments, { response, eventAction: 'confirm' }));
    assert.match(html, new RegExp(title));
    assert.match(html, new RegExp(`错误代码：${code}`));
  }
});

test('simulation knowledge sources stay collapsed and are never labeled as execution evidence', () => {
  const html = renderToStaticMarkup(React.createElement(KnowledgeSourcesDisclosure, {
    sources: [{ title: 'Conduction reference', page_start: 8, text_preview: 'Related background.' }],
    relatedToSimulation: true,
  }));
  assert.match(html, /<details/);
  assert.doesNotMatch(html, /<details[^>]* open/);
  assert.match(html, /相关知识来源（可选）/);
  assert.doesNotMatch(html, /仿真依据|执行证据/);
});


test('仿真开关是独立 capability switch，点击只改变 enabled', () => {
  const changes = [];
  const element = SimulationModeToggle({ enabled: false, available: true, onChange: value => changes.push(value) });
  assert.equal(element.props.role, 'switch');
  assert.equal(element.props['aria-checked'], false);
  element.props.onClick();
  assert.deepEqual(changes, [true]);

  const enabledHtml = renderToStaticMarkup(
    React.createElement(SimulationModeToggle, { enabled: true, available: true, onChange: () => {} }),
  );
  assert.match(enabledHtml, /aria-checked="true"/);
  assert.match(enabledHtml, /仿真/);
  assert.doesNotMatch(enabledHtml, /场景仿真/);
});

test('计划卡、确认和取消都作为 assistant message attachment 渲染', () => {
  const response = {
    metadata: {
      simulation_mode: { enabled: true, state: 'pending_confirmation', pending_confirmation: true, confirm_allowed: true },
      simulation_plan: {
        generated: true,
        plan_id: 'sim-1',
        objective: '评估平壁稳态导热',
        selected_model_id: 'plane_wall_steady_v1',
        selected_model_name: '平壁稳态导热',
        selection_reason: 'exact_scenario_match',
        candidate_models: [{ model_id: 'plane_wall_steady_v1', display_name: '平壁稳态导热' }],
        solver_backend: 'matlab',
        inputs: { thickness_m: 0.05 },
        missing_inputs: [],
        execution_allowed: true,
        can_execute_now: true,
      },
      matlab: { available: true },
      simulation_execution: { executed: false, status: 'not_started', errors: [] },
    },
  };
  assert.equal(hasSimulationAttachment(response), true);
  assert.equal(simulationMetadata(response).plan.selected_model_id, 'plane_wall_steady_v1');
  const html = renderToStaticMarkup(
    React.createElement(SimulationMessageAttachments, { response, onAction: () => {} }),
  );
  assert.match(html, /仿真计划已就绪/);
  assert.match(html, /plane_wall_steady_v1|平壁稳态导热/);
  assert.match(html, /确认执行/);
  assert.match(html, /修改计划/);
  assert.match(html, /取\s*消/);
});

function buttons(element) {
  if (!React.isValidElement(element)) return [];
  const children = React.Children.toArray(element.props.children);
  return [element, ...children.flatMap(buttons)].filter(child => typeof child.props.onClick === 'function');
}

test('incomplete/conflict plans cannot confirm even with stale readiness flags; supplement uses revise', () => {
  for (const invalid of [
    { missing_inputs: ['temperature_boundary'], can_execute_now: false },
    { missing_inputs: ['temperature_boundary'], can_execute_now: true },
    { input_errors: [{ code: 'SIMULATION_INPUT_CONFLICT' }], can_execute_now: true },
  ]) {
    const actions = [];
    const element = SimulationPlanCard({
      plan: { generated: true, plan_id: 'needs-input', execution_allowed: true, ...invalid },
      mode: { pending_confirmation: true, confirm_allowed: true },
      onAction: (...args) => actions.push(args),
    });
    const html = renderToStaticMarkup(element);
    assert.doesNotMatch(html, /确认执行/);
    assert.match(html, /补充参数|修正参数/);
    const supplement = buttons(element).find(button => /补充参数|修正参数/.test(button.props.children));
    supplement.props.onClick();
    buttons(element).find(button => button.props.children === '取消').props.onClick();
    assert.deepEqual(actions, [['revise', 'needs-input'], ['cancel', 'needs-input']]);
  }
});

test('ready confirm targets the displayed plan; completed plans cannot execute again', () => {
  const actions = [];
  const plan = { generated: true, plan_id: 'ready', can_execute_now: true, execution_allowed: true, missing_inputs: [], inputs: { delta_temperature_k: 60 } };
  const mode = { pending_confirmation: true, confirm_allowed: true };
  const element = SimulationPlanCard({ plan, mode, onAction: (...args) => actions.push(args) });
  buttons(element).find(button => button.props.children === '确认执行').props.onClick();
  assert.deepEqual(actions, [['confirm', 'ready']]);
  assert.match(renderToStaticMarkup(element), /60 K/);
  const completed = renderToStaticMarkup(React.createElement(SimulationPlanCard, { plan, mode: { ...mode, confirmed: true, executed: true } }));
  assert.doesNotMatch(completed, /确认执行/);
  const historical = renderToStaticMarkup(React.createElement(SimulationPlanCard, { plan, mode, actionsEnabled: false }));
  assert.doesNotMatch(historical, /确认执行|修改计划|补充参数/);
});

test('confirm/cancel action contract 保留 simulation mode 和 plan id', () => {
  assert.deepEqual(buildSimulationActionRequest({ action: 'confirm', planId: 'sim-1' }), {
    query: '确认执行',
    simulationMode: true,
    simulationAction: 'confirm',
    simulationPlanId: 'sim-1',
  });
  assert.deepEqual(buildSimulationActionRequest({ action: 'cancel', planId: 'sim-1' }), {
    query: '取消仿真',
    simulationMode: true,
    simulationAction: 'cancel',
    simulationPlanId: 'sim-1',
  });
});

test('chat supplement sends the actual text with revise and the current plan id', () => {
  assert.equal(buildSimulationRevisionRequest({ query: ' ', planId: 'sim-1' }), null);
  assert.deepEqual(buildSimulationRevisionRequest({ query: ' 温差就是60K ', planId: 'sim-1' }), {
    query: '温差就是60K', simulationMode: true, simulationAction: 'revise', simulationPlanId: 'sim-1',
  });
});

test('结果和失败卡明确区分真实执行、未执行与 CFD', () => {
  const success = {
    metadata: {
      simulation_plan: { generated: true, plan_id: 'sim-2', selected_model_id: 'plane_wall_steady_v1' },
      simulation_mode: { enabled: true, state: 'completed' },
      simulation_execution: {
        executed: true,
        status: 'completed',
        solver_backend: 'matlab',
        result: { heat_rate_w: 1920 },
        errors: [],
        cfd_executed: false,
      },
    },
  };
  const successHtml = renderToStaticMarkup(React.createElement(SimulationMessageAttachments, { response: success }));
  assert.match(successHtml, /仿真结果/);
  assert.match(successHtml, /1,920 W/);
  assert.match(successHtml, /CFD 未执行/);

  const failed = {
    metadata: {
      simulation_plan: { generated: true, plan_id: 'sim-3', selected_model_id: 'plane_wall_steady_v1' },
      simulation_mode: { enabled: true, state: 'failed' },
      simulation_execution: {
        executed: false,
        status: 'failed',
        errors: [{ code: 'MATLAB_NOT_AVAILABLE', message: 'MATLAB Engine is not ready.' }],
      },
    },
  };
  const failedHtml = renderToStaticMarkup(React.createElement(SimulationMessageAttachments, { response: failed }));
  assert.match(failedHtml, /仿真未执行/);
  assert.match(failedHtml, /MATLAB_NOT_AVAILABLE/);
});

import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { readFileSync } from 'node:fs';
import { hyperMissionState, hyperMissionReference } from './hyperMissionState.js';

const fixture = JSON.parse(readFileSync(new URL('./taskResponse.fixture.json', import.meta.url), 'utf8'));
const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: TaskProgressCard } = await vite.ssrLoadModule('/src/tasks/TaskProgressCard.jsx');
const { ThemeContext } = await vite.ssrLoadModule('/src/theme/useAppTheme.js');
after(() => vite.close());
const renderTask = (task, themeId = 'hyper', extra = {}) => renderToStaticMarkup(React.createElement(ThemeContext.Provider,
  { value: { themeId } }, React.createElement(TaskProgressCard, { task, ...extra })));

test('Hyper has its own mission branch and keeps the existing technical records', () => {
  const html = renderTask(fixture.finished, 'hyper', { onOpen: () => {} });
  for (const marker of ['hyper-mission-board', 'MISSION JOURNAL', 'CHAPTERS', 'DEPENDENCY MAP', '中间变量与单位', '真实事件时间线', '输入与输出', '已通过已配置物理检查', '查看详情']) assert.ok(html.includes(marker), marker);
  assert.match(html, /liquid_flow_rate_required/);
  assert.match(html, /liquid_pressure_drop_estimate/);
  assert.match(html, /EVIDENCE INCOMPLETE/);
  assert.match(html, /根据流量计算管路压降/);
  assert.match(html, /REQUIRES/);
  assert.match(html, new RegExp(fixture.finished.task_id));
  assert.doesNotMatch(html, /hyper-mission-complete|100%/);
});

test('Engineering and cel retain their own markup with no Hyper decorations', () => {
  const engineering = renderTask(fixture.finished, 'engineering');
  const cel = renderTask(fixture.finished, 'cel');
  assert.match(engineering, /工程任务执行记录/);
  assert.match(engineering, /任务依赖图/);
  assert.match(cel, /data-testid="mission-board"/);
  assert.match(cel, /EVIDENCE INCOMPLETE/);
  for (const html of [engineering, cel]) assert.doesNotMatch(html, /ta-hyper-|MISSION JOURNAL|CHAPTERS/);
});

test('only a recorded running step becomes the active objective and tool call', () => {
  const running = { ...fixture.queued, status: 'running', steps: fixture.queued.steps.map(step => ({ ...step, status: step.step_id === 'flow' ? 'running' : 'pending' })) };
  const html = renderTask(running);
  assert.match(html, /CURRENT CHAPTER/);
  assert.match(html, /TOOL CALL · liquid_flow_rate_required/);
  assert.match(html, /aria-current="step"/);
  assert.match(html, /aria-pressed="true"/);
  assert.equal((html.match(/aria-current="step"/g) || []).length, 1);
  assert.equal(hyperMissionState(running).current.step_id, 'flow');
  assert.doesNotMatch(html, /hyper-mission-complete/);
});

test('terminal exceptions, pending states and unknown status cannot receive a completion stamp', () => {
  for (const status of ['queued', 'planned', 'pending', 'running', 'blocked', 'failed', 'incomplete', 'cancelled', 'interrupted', 'unknown']) {
    const task = { ...fixture.queued, status };
    const html = renderTask(task);
    assert.match(html, /aria-label="已完成 0\/6 个已声明步骤"/);
    assert.doesNotMatch(html, /hyper-mission-complete|CURRENT CHAPTER|✓/);
    assert.equal(hyperMissionState(task).complete, false);
  }
});

test('completion requires actual task completion and consistent step/check records', () => {
  const complete = { ...fixture.finished, status: 'completed', steps: fixture.finished.steps.map(step => ({ ...step, status: 'completed' })) };
  assert.equal(hyperMissionState(complete).complete, true);
  assert.match(renderTask(complete), /data-testid="hyper-mission-complete"/);
  assert.equal(hyperMissionState({ ...complete, status: 'running' }).complete, false);
  for (const patch of [
    { steps: [{ step_id: 'evidence', status: 'incomplete' }] },
    { steps: [{ step_id: 'tool', status: 'pending' }] },
    { validation: { status: 'failed', passed: false } },
    { design_review: { status: 'violated', passed: false, checks: [] } },
    { error: { code: 'EXECUTION_FAILED', message: 'Actual recorded failure' } },
  ]) {
    const task = { ...complete, ...patch };
    assert.equal(hyperMissionState(task).complete, false);
    assert.match(renderTask(task), /RECORD NEEDS REVIEW/);
    assert.doesNotMatch(renderTask(task), /hyper-mission-complete/);
  }
});

test('design limits display actual backend numbers, units, source and unavailable evidence without inferred values', () => {
  const task = { ...fixture.finished, design_review: {
    status: 'unavailable', passed: false, reviewer_version: 'explicit-design-limits-v1', limitations: ['Only explicit limits.'],
    checks: [
      { criterion: 'max_pressure_drop_pa', label: '管路压降', actual: 4812.75, maximum: 3000, unit: 'Pa', status: 'violated', source: 'recorded_tool_output' },
      { criterion: 'max_heat_rate_abs_w', label: '传热量', actual: null, maximum: 120, unit: 'W', status: 'unavailable', source: 'not_recorded' },
    ],
  } };
  const html = renderTask(task);
  for (const marker of ['hyper-design-review', '4812.75', '3000', 'Pa', '120', 'recorded_tool_output', 'not_recorded', '缺少计算证据', '超出设计上限', '未提供', 'explicit-design-limits-v1', 'Only explicit limits.']) assert.ok(html.includes(marker), marker);
  assert.doesNotMatch(html, /hyper-mission-complete/);
  assert.doesNotMatch(renderTask(fixture.finished), /hyper-design-review/);
});

test('empty plans remain visibly empty and identifiers do not invent tasks', () => {
  const html = renderTask({ task_id: '', status: 'queued', steps: [], events: [] });
  assert.match(html, /等待服务记录计划/);
  assert.match(html, /UNASSIGNED/);
  assert.match(html, /已完成 0\/0 个已声明步骤/);
  assert.doesNotMatch(html, /DECLARED TOOL|TOOL CALL|hyper-mission-complete/);
  assert.equal(hyperMissionReference('task_abcdef1234567890'), '34567890');
});

test('compact task cards keep dependency names and the real event record', () => {
  const html = renderTask(fixture.finished, 'hyper', { compact: true });
  assert.match(html, /任务手记/);
  assert.match(html, /REQUIRES/);
  assert.match(html, /真实事件时间线/);
  assert.doesNotMatch(html, /DEPENDENCY MAP/);
});

test('journal keeps declared tool versions visible even in the compact rail', () => {
  const html = renderTask(fixture.queued, 'hyper', { compact: true });
  assert.match(html, /ELYSIAN ATELIER/);
  assert.match(html, /DECLARED TOOL/);
  assert.match(html, /thermal-tools-v2.1/);
  assert.doesNotMatch(html, /TOOL CALL/);
  assert.match(renderTask({ ...fixture.queued, steps: [{ step_id: 'tool', title: '计算', status: 'pending', tool_name: 'declared_solver' }] }), /版本 · 未声明/);
});

test('journal outcome explains incomplete evidence without announcing report readiness', () => {
  const html = renderTask(fixture.finished);
  assert.match(html, /仍有待补全的篇章/);
  assert.match(html, /部分证据尚不完整/);
  assert.doesNotMatch(html, /MISSION COMPLETE|REPORT READY|这一页，已经写就/);
  const complete = { ...fixture.finished, status: 'completed', steps: fixture.finished.steps.map(step => ({ ...step, status: 'completed' })) };
  const completeHtml = renderTask(complete);
  assert.match(completeHtml, /MISSION COMPLETE/);
  assert.match(completeHtml, /这一页，已经写就/);
  assert.doesNotMatch(completeHtml, /仍有待补全的篇章/);
});

test('Hyper animation selectors respect both saved reduced motion and the OS preference', () => {
  const css = readFileSync(new URL('./hyperMission.css', import.meta.url), 'utf8');
  assert.match(css, /:root\[data-theme="hyper"\]:not\(\[data-hyper-motion="reduced"\]\)/);
  assert.match(css, /@media\(prefers-reduced-motion:no-preference\)/);
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)/);
  assert.doesNotMatch(css, /data-theme="(?:cel|engineering)"/);
});

test('a design-only failure is not mislabeled as missing physical or retrieval evidence', () => {
  const task = { ...fixture.finished, status: 'incomplete', validation: { status: 'passed', passed: true },
    steps: [...fixture.finished.steps.map(step => ({ ...step, status: 'completed' })), { step_id: 'design_review', status: 'incomplete' }],
    design_review: { status: 'violated', passed: false, checks: [{ metric: 'heat_rate', actual: 166.1129, maximum: 100, unit: 'W', status: 'violated' }] },
  };
  assert.equal(hyperMissionState(task).status, 'design_failed');
  const html = renderTask(task, 'hyper', { compact: true });
  assert.match(html, /DESIGN LIMIT FAILED/); assert.match(html, /计算已完成，设计指标未通过/);
  assert.doesNotMatch(html, /EVIDENCE INCOMPLETE|MISSION COMPLETE/);
  assert.match(html, /<details class="ta-hyper-chapters">/);
  task.steps[0].status = 'incomplete';
  assert.equal(hyperMissionState(task).status, 'incomplete');
});

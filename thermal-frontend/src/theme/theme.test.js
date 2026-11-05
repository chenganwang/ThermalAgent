import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { readFileSync } from 'node:fs';
import { antThemeConfig, DEFAULT_THEME, normalizeThemeId, readThemePreference, saveThemePreference, THEMES, THEME_STORAGE_KEY } from './themeRegistry.js';
import { assistantBrief } from '../workspace/animePresentation.js';

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: ThemeSwitcher } = await vite.ssrLoadModule('/src/theme/ThemeSwitcher.jsx');
const { ThemeContext } = await vite.ssrLoadModule('/src/theme/useAppTheme.js');
const { default: HistoryChart } = await vite.ssrLoadModule('/src/HistoryChart.jsx');
const { default: WelcomePanel } = await vite.ssrLoadModule('/src/workspace/WelcomePanel.jsx');
const { AnimeTaskBar } = await vite.ssrLoadModule('/src/workspace/AnimeWorkspace.jsx');
after(() => vite.close());
function luminance(hex) { const channels = hex.replace('#', '').match(/../g).map(value => parseInt(value, 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4); return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722; }
function contrast(a, b) { const levels = [luminance(a), luminance(b)].sort((x, y) => y - x); return (levels[0] + .05) / (levels[1] + .05); }

test('unknown and stale theme preferences fall back without making arbitrary CSS selectors', () => {
  for (const value of [null, undefined, 'night', '__proto__', 'cel"] body {display:none}']) assert.equal(normalizeThemeId(value), DEFAULT_THEME);
  assert.equal(normalizeThemeId('cel'), 'cel');
});
test('theme choice persists through its own key and storage failure remains recoverable', () => {
  const saved = new Map();
  const storage = { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) };
  assert.equal(saveThemePreference('cel', storage), true);
  assert.equal(saved.get(THEME_STORAGE_KEY), 'cel');
  assert.deepEqual(readThemePreference(storage), { themeId: 'cel', storageAvailable: true });
  const denied = { getItem: () => { throw Error('disabled'); }, setItem: () => { throw Error('disabled'); } };
  assert.equal(saveThemePreference('cel', denied), false);
  assert.deepEqual(readThemePreference(denied), { themeId: DEFAULT_THEME, storageAvailable: false });
});
test('all registered themes supply accessible text and visible chart lines on their surfaces', () => {
  for (const selected of Object.values(THEMES)) {
    for (const color of [selected.tokens.text, selected.tokens.textMuted, selected.tokens.primary]) assert.ok(contrast(color, selected.tokens.surface) >= 4.5, `${selected.id}: ${color}`);
    assert.ok(contrast('#ffffff', selected.tokens.primary) >= 4.5);
    assert.ok(contrast(selected.chart.primary, selected.chart.background) >= 3);
    assert.equal(antThemeConfig(selected.id).token.colorText, selected.tokens.text);
    assert.equal(antThemeConfig(selected.id).token.colorBgContainer, selected.tokens.surface);
  }
});

test('three stable theme IDs persist and Hyper has an independent launch layout', () => {
  assert.deepEqual(Object.keys(THEMES), ['engineering', 'cel', 'hyper']);
  let saved;
  const storage = { setItem: (_, value) => { saved = value; }, getItem: () => saved };
  for (const themeId of Object.keys(THEMES)) {
    assert.equal(saveThemePreference(themeId, storage), true);
    assert.equal(readThemePreference(storage).themeId, themeId);
  }
  const html = renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId: 'hyper' } }, React.createElement(WelcomePanel, { onExample: () => {} })));
  assert.match(html, /hyper-welcome/);
  assert.match(html, /ELYSIAN ATELIER/);
  assert.doesNotMatch(html, /anime-welcome|ta-welcome-heading/);
  const switcher = renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId: 'hyper', setThemeId: () => {}, storageAvailable: true } }, React.createElement(ThemeSwitcher)));
  for (const id of Object.keys(THEMES)) assert.match(switcher, new RegExp(`data-testid="theme-${id}"`));
  assert.match(switcher, /减少动态效果/);
});
test('switcher identifies the chosen theme and announces unavailable persistence', () => {
  const html = renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId: 'cel', setThemeId: () => {}, storageAvailable: false } }, React.createElement(ThemeSwitcher)));
  assert.match(html, /界面主题/);
  assert.match(html, /aria-pressed="true"[^>]*title="赛璐璐/);
  assert.match(html, /浏览器未允许保存/);
});
test('chart receives concrete theme colors and preserves its spatial axis and measured values', () => {
  const history = { name: 'temperature', unit: 'K', axis: 'position_m', axis_unit: 'm', points: [[0, 350], [.01, 290]] };
  for (const selected of Object.values(THEMES)) {
    const html = renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { chart: selected.chart } }, React.createElement(HistoryChart, { history, isMock: false })));
    assert.ok(html.includes(`stroke="${selected.chart.primary}"`));
    assert.match(html, /位置 \(m\)/);
    assert.match(html, /350/);
    assert.doesNotMatch(html, /Mock 演示/);
  }
});
test('cel theme declares structural illustration rules and system reduced-motion handling', () => {
  const css = readFileSync(new URL('../workspace/workspace.css', import.meta.url), 'utf8');
  const themeCss = readFileSync(new URL('./theme.css', import.meta.url), 'utf8');
  assert.match(css, /data-theme="cel"[^\n]*ta-example-grid[^\n]*border-radius/);
  assert.match(css, /ta-engineer-mark[^\n]*animation/);
  assert.match(themeCss, /prefers-reduced-motion:reduce/);
  assert.match(themeCss, /animation-iteration-count:1!important/);
  assert.match(css, /ta-skip-link[^\n]*clip-path:inset\(50%\)/);
  assert.match(css, /ta-skip-link:focus-visible[^\n]*clip-path:none/);
  assert.match(css, /data-theme="cel"[^\n]*ta-mark-professional[^\n]*display:none/);
  assert.match(css, /data-theme="cel"[^\n]*ta-mark-character[^\n]*display:initial/);
});

test('anime workspace supplies its own research layout while engineering retains its original welcome', () => {
  const render = themeId => renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId } }, React.createElement(WelcomePanel, { onExample: () => {} })));
  const engineering = render('engineering');
  const anime = render('cel');
  assert.match(engineering, /ta-welcome-heading/);
  assert.doesNotMatch(engineering, /anime-welcome|RESEARCH DECK|CONCEPT SKETCH/);
  assert.match(anime, /anime-welcome/);
  assert.match(anime, /液冷模块概念设定图，非仿真结果/);
  assert.match(anime, /liquid-cooling-example/);
  assert.match(anime, /KNOWLEDGE ARCHIVE/);
  assert.doesNotMatch(anime, /ta-welcome-heading/);
});

test('navigator represents actual steps and separates absent, waiting, blocked and unknown states', () => {
  assert.equal(assistantBrief(null).label, 'STANDBY');
  assert.equal(assistantBrief(null, true).label, 'AWAITING RESPONSE');
  const task = { task_id: 'task_abcd12345678', status: 'running', steps: [{ status: 'completed' }, { status: 'running', step_id: 'flow', title: '计算流量', tool_name: 'flow_sizing' }, { status: 'pending' }] };
  const running = assistantBrief(task);
  assert.equal(running.message, '正在执行：计算流量');
  assert.equal(running.completed, 1);
  assert.equal(running.total, 3);
  assert.equal(running.id, '12345678');
  assert.equal(running.current.tool_name, 'flow_sizing');
  assert.equal(running.active, true);
  assert.equal(assistantBrief({ status: 'running', steps: [] }).active, false);
  for (const status of ['blocked', 'failed', 'cancelled', 'interrupted', 'future_status']) {
    const result = assistantBrief({ ...task, status, steps: [] });
    assert.equal(result.active, false);
    assert.doesNotMatch(result.message, /分析完成|验证通过/);
  }
});

test('task status bar does not invent a tool call or completion for pending requests', () => {
  const idle = renderToStaticMarkup(React.createElement(AnimeTaskBar, { loading: true }));
  assert.match(idle, /AWAITING RESPONSE/);
  assert.doesNotMatch(idle, /tool-signal|步骤|COMPLETE/);
  const task = { task_id: 'task_12345678', status: 'running', steps: [{ step_id: 'validation', title: '物理验证', status: 'running', tool_name: 'physics_validator' }] };
  const running = renderToStaticMarkup(React.createElement(AnimeTaskBar, { task }));
  assert.match(running, /physics_validator/);
  assert.match(running, /0\/1 步骤/);
  assert.match(running, /data-active="true"/);
});

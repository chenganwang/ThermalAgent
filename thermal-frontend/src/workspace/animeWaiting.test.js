import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: AnimeWaiting } = await vite.ssrLoadModule('/src/workspace/AnimeWaiting.jsx');
after(() => vite.close());

function withStorage(storage, action) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get: () => storage });
  try { return action(); }
  finally { if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor); else delete globalThis.localStorage; }
}
const renderWaiting = props => renderToStaticMarkup(React.createElement(AnimeWaiting, props));

test('inactive waiting companion renders no animation, service message or controls', () => {
  assert.equal(withStorage({ getItem: () => null }, () => renderWaiting({ active: false, message: '未发生的响应' })), '');
});

test('first active waiting companion displays original decoration and supplied service text', () => {
  const keys = [];
  const html = withStorage({ getItem: key => { keys.push(key); return null; } }, () => renderWaiting({ active: true, message: '等待当前请求的服务响应。' }));
  assert.deepEqual(keys, ['thermalagent.animeWaiting.v1']);
  assert.match(html, /anime-waiting-art/);
  assert.match(html, /导航员研读中/);
  assert.match(html, /等待当前请求的服务响应/);
  assert.match(html, /aria-label="关闭等待动画"/);
  assert.doesNotMatch(html, /计算完成|验证通过|100%|任务已完成/);
});

test('persisted animation opt-out preserves actual service text and a restore control', () => {
  const html = withStorage({ getItem: () => 'off' }, () => renderWaiting({ active: true, message: '任务正在排队。' }));
  assert.match(html, /data-animation="off"/);
  assert.match(html, /任务正在排队/);
  assert.match(html, /aria-label="启用等待动画"/);
  assert.doesNotMatch(html, /anime-waiting-art|<svg|导航员研读中/);
});

test('unavailable storage remains safe and does not reinterpret service messages as markup', () => {
  const html = withStorage({ getItem: () => { throw Error('storage disabled'); } }, () => renderWaiting({ active: true, message: '<script>fake()</script>' }));
  assert.match(html, /无法保存动画偏好/);
  assert.match(html, /关闭等待动画/);
  assert.match(html, /&lt;script&gt;fake\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

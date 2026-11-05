import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: MarkdownContent } = await vite.ssrLoadModule('/src/MarkdownContent.jsx');
after(() => vite.close());
const render = content => renderToStaticMarkup(React.createElement(MarkdownContent, null, content));

test('engineering report parameter and result tables render as semantic HTML tables', () => {
  const html = render('## 输入参数\n\n| 参数 | 数值 | 单位 |\n| --- | ---: | --- |\n| 厚度 | 0.005 | m |\n| 导热系数 | 10 | W/(m·K) |\n\n## 计算结果\n\n| 结果 | 数值 | 单位 |\n| --- | ---: | --- |\n| 热阻 | 0.25 | K/W |');
  assert.equal((html.match(/<table>/g) || []).length, 2);
  assert.match(html, /<th>参数<\/th>/);
  assert.match(html, /<td>厚度<\/td>/);
  assert.match(html, /<td>W\/\(m·K\)<\/td>/);
  assert.match(html, /<td>热阻<\/td>/);
  assert.match(html, /<td>K\/W<\/td>/);
  assert.doesNotMatch(html, /\| 参数 \||\| 热阻 \|/);
});

test('table cells preserve inline formatting and escaped pipes without splitting values', () => {
  const html = render('| 参数 | 说明 |\n| --- | --- |\n| **热阻** | `R=L/(k*A)` |\n| 边界 | 入口\\|出口 |');
  assert.match(html, /<strong>热阻<\/strong>/);
  assert.match(html, /<code>R=L\/\(k\*A\)<\/code>/);
  assert.match(html, /<td>入口\|出口<\/td>/);
  assert.equal((html.match(/<td>/g) || []).length, 4);
});

test('ordinary pipes and fenced table source retain their original Markdown meaning', () => {
  const html = render('入口 | 出口\n\n```text\n| 参数 | 单位 |\n| --- | --- |\n| 厚度 | m |\n```');
  assert.doesNotMatch(html, /<table>/);
  assert.match(html, /<p>入口 \| 出口<\/p>/);
  assert.match(html, /<pre><code class="language-text">\| 参数 \| 单位 \|/);
});

test('GFM does not enable raw HTML or executable Markdown links in report content', () => {
  const html = render('<script>alert(1)</script>\n\n| 内容 |\n| --- |\n| <img src=x onerror=alert(1)> |\n| [unsafe](javascript:alert%281%29) |');
  assert.match(html, /<table>/);
  assert.doesNotMatch(html, /<script|<img|href="javascript:/i);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /&lt;img/);
});

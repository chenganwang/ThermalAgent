import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { activePendingMessage } from './activeRequest.js';

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: ConversationMessages } = await vite.ssrLoadModule('/src/workspace/ConversationMessages.jsx');
const { ThemeContext } = await vite.ssrLoadModule('/src/theme/useAppTheme.js');
after(() => vite.close());
const old = { id: 'old', role: 'bot', pending: true, mode: 'chat', content: '' };
const current = { ...old, id: 'current' };

test('pending identity follows the current request and visible conversation only', () => {
  assert.equal(activePendingMessage([old, current], 'current', true), current);
  assert.equal(activePendingMessage([old], 'current', true), null);
  assert.equal(activePendingMessage([current], 'current', false), null);
  assert.equal(activePendingMessage([{ ...current, pending: false }], 'current', true), null);
  assert.equal(activePendingMessage([old], null, true), null);
});

test('a new request never revives restored waiting messages in any theme', () => {
  for (const themeId of ['engineering', 'cel', 'hyper']) {
    const html = renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId } }, React.createElement(ConversationMessages, { messages: [old, current], loading: true, activePendingId: 'current' })));
    assert.equal((html.match(/这是尚未完成的历史请求/g) || []).length, 1, themeId);
    if (themeId === 'hyper') assert.equal((html.match(/少女祈祷中……/g) || []).length, 1);
    const other = renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId } }, React.createElement(ConversationMessages, { messages: [old], loading: true, activePendingId: 'current' })));
    assert.match(other, /这是尚未完成的历史请求/);
    assert.doesNotMatch(other, /少女祈祷中|ant-spin|anime-waiting/);
  }
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { CONVERSATION_STORAGE_KEY, isActiveConversationReply, loadConversations, normalizeConversations, saveConversations } from './conversationStorage.js';
import { assertResultIdentity, captureResultIdentity, guardMessageIdentity, replaceOwnedReply, RESULT_IDENTITY_ERROR } from './resultIdentity.js';

test('invalid persisted JSON shapes cannot crash the conversation list or composer', () => {
  for (const value of [null, {}, 'text', 1, [null, false, {}, { id: 2 }]]) {
    assert.deepEqual(normalizeConversations(value), []);
  }
  assert.deepEqual(loadConversations({ getItem: () => '{broken' }), []);
  const [conversation] = normalizeConversations([{ id: 'old', title: {}, mode: 'simulation', messages: [null, {}, { role: 'bot', raw: { answer: 'kept' } }] }]);
  assert.equal(conversation.title, '历史对话');
  assert.equal(conversation.mode, 'chat');
  assert.deepEqual(conversation.messages, [{ role: 'bot', raw: { answer: 'kept' } }]);
});

test('storage migration keeps existing key and reports quota/access failures', () => {
  let written;
  const conversations = [{ id: 'old', title: '旧对话', mode: 'report', messages: [] }];
  assert.equal(saveConversations(conversations, { setItem: (key, value) => { written = { key, value }; } }), true);
  assert.equal(written.key, CONVERSATION_STORAGE_KEY);
  assert.equal(loadConversations({ getItem: () => written.value })[0].title, '旧对话');
  assert.equal(saveConversations(conversations, { setItem: () => { throw Error('quota'); } }), false);
});

test('a late reply cannot overwrite a newly selected or deleted conversation', () => {
  assert.equal(isActiveConversationReply('first', 'first'), true);
  assert.equal(isActiveConversationReply('second', 'first'), false);
  assert.equal(isActiveConversationReply(null, 'first'), false);
});

test('request slots reject delayed, cross-conversation and duplicate reply deliveries while preserving newer messages', async () => {
  const owner = { conversationId: 'conv-a', requestId: 'req-a', pendingMessageId: 'pending-a' };
  const pending = { id: owner.pendingMessageId, role: 'bot', pending: true, ...owner };
  const newer = { id: 'new-user', role: 'user', content: '另一个问题' };
  const messages = [pending, newer];
  const reply = { id: 'done-a', role: 'bot', requestId: 'req-a', conversationId: 'conv-a', content: '当前结果' };
  const [wrong, valid] = await Promise.all([
    Promise.resolve({ ...reply, requestId: 'old-request', content: '过期结果' }), Promise.resolve(reply),
  ]);
  assert.equal(replaceOwnedReply(messages, wrong, owner), messages);
  assert.equal(replaceOwnedReply(messages, { ...reply, conversationId: 'conv-b' }, owner), messages);
  const completed = replaceOwnedReply(messages, valid, owner);
  assert.equal(completed[0].content, '当前结果'); assert.equal(completed[1], newer);
  assert.equal(replaceOwnedReply(completed, { ...reply, content: '重复旧结果' }, owner), completed);
  assert.deepEqual(replaceOwnedReply([], reply, owner), []);
});

test('persisted crossed task and conversation identities are quarantined instead of rendering old numbers', () => {
  const invalid = [
    { conversationId: 'other' },
    { taskId: 'expected', taskSnapshot: { task_id: 'wrong' } },
    { requestId: 'new', resultIdentity: { requestId: 'old' } },
    { raw: { session_id: 'other' } },
    { raw: { metadata: { engineering_run: { run_id: 'current', persistence: { run_id: 'old' } } } } },
  ];
  for (const patch of invalid) {
    const [conversation] = normalizeConversations([{ id: 'conv', messages: [{ role: 'bot', content: '错误旧热流166.11W', sources: [{ title: 'stale' }], ...patch }] }]);
    const message = conversation.messages[0];
    assert.equal(message.identityError, RESULT_IDENTITY_ERROR); assert.equal(message.taskSnapshot, null);
    assert.deepEqual(message.sources, []); assert.doesNotMatch(message.content, /166.11/);
    assert.match(message.content, /已阻止展示/);
  }
});

test('request, input, calculation and run fingerprints are independent and explicit conflicts fail closed', () => {
  const task = { task_id: 'task-new', scope: 'bounded_reference_conduction', session_id: 'conv', request_fingerprint: 'request', input_fingerprint: 'input', calculation_fingerprint: 'calculation', run_id: 'run',
    result: { session_id: 'conv', metadata: { engineering_task: { task_id: 'task-new', input_fingerprint: 'input', request_fingerprint: 'request' }, engineering_run: { run_id: 'run', input_fingerprint: 'input', calculation_fingerprint: 'calculation' } } } };
  const binding = captureResultIdentity({ task, requestId: 'req', sessionId: 'conv' });
  assert.equal(binding.runId, 'run'); assert.equal(binding.inputFingerprint, 'input');
  for (const field of ['taskId', 'sessionId', 'requestFingerprint', 'inputFingerprint', 'calculationFingerprint', 'runId']) {
    assert.throws(() => assertResultIdentity({ ...binding, [field]: 'old', task }), error => error.code === RESULT_IDENTITY_ERROR);
  }
  const message = { role: 'bot', taskId: task.task_id, taskSnapshot: task, requestId: 'req', conversationId: 'conv', resultIdentity: binding, raw: task.result };
  assert.equal(guardMessageIdentity(message, 'conv'), message);
  const legacy = { role: 'bot', content: '旧版正常问答', raw: { answer: '历史文字' } };
  assert.equal(guardMessageIdentity(legacy, 'conv'), legacy);
});

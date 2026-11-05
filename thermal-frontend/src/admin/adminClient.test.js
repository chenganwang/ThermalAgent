import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { AdminApiError, getAdminModules, getAdminSession, updateAdminConfig } from './api/adminClient.js';

test('Viewer Token 只进入请求头，不进入 URL', async () => {
  const previousFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'req-test' },
      json: async () => ({ success: true, request_id: 'req-test', data: { identity: { role: 'viewer' } } }),
    };
  };
  try {
    const session = await getAdminSession('memory-only-secret');
    await getAdminModules('memory-only-secret', { status: 'unknown' });
    assert.equal(session.identity.role, 'viewer');
  } finally {
    globalThis.fetch = previousFetch;
  }
  assert.equal(calls.length, 2);
  for (const call of calls) {
    assert.equal(call.options.headers['X-Admin-Token'], 'memory-only-secret');
    assert.equal(call.url.includes('memory-only-secret'), false);
  }
});

test('本地开发会话可由后端建立且请求不伪造管理员请求头', async () => {
  const previousFetch = globalThis.fetch;
  let call;
  globalThis.fetch = async (url, options) => {
    call = { url: String(url), options };
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'req-local' },
      json: async () => ({
        success: true,
        request_id: 'req-local',
        data: { identity: { role: 'administrator', auth_mode: 'local_development' } },
      }),
    };
  };
  try {
    const session = await getAdminSession(null);
    assert.equal(session.identity.auth_mode, 'local_development');
  } finally {
    globalThis.fetch = previousFetch;
  }
  assert.equal(call.options.headers['X-Admin-Token'], undefined);
});

test('Admin envelope 错误保留稳定 code 但不拼接请求头', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 401,
    headers: { get: () => 'req-auth' },
    json: async () => ({ success: false, request_id: 'req-auth', error: { code: 'AUTH_INVALID', message: 'invalid' } }),
  });
  try {
    await assert.rejects(
      () => getAdminSession('not-returned'),
      error => error instanceof AdminApiError && error.code === 'AUTH_INVALID' && !error.message.includes('not-returned'),
    );
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test('Admin 鉴权实现不使用浏览器持久化或 console', async () => {
  const authSource = await readFile(new URL('./auth/AdminAuthContext.jsx', import.meta.url), 'utf8');
  const clientSource = await readFile(new URL('./api/adminClient.js', import.meta.url), 'utf8');
  for (const forbidden of ['localStorage', 'sessionStorage', 'indexedDB']) {
    assert.equal(authSource.includes(forbidden), false);
    assert.equal(clientSource.includes(forbidden), false);
  }
  assert.equal(clientSource.includes('console.'), false);
});

test('配置写凭据只进入独立 header，不进入 URL 或 body', async () => {
  const previousFetch = globalThis.fetch;
  let call;
  globalThis.fetch = async (url, options) => {
    call = { url: String(url), options };
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'req-config' },
      json: async () => ({ success: true, request_id: 'req-config', data: { dry_run: true, side_effects: [] } }),
    };
  };
  try {
    await updateAdminConfig('viewer-memory-token', 'write-memory-token', {
      changes: { report_visible: false },
      expected_version: 1,
      reason: 'test',
      dry_run: true,
    });
  } finally {
    globalThis.fetch = previousFetch;
  }
  assert.equal(call.options.headers['X-Admin-Token'], 'viewer-memory-token');
  assert.equal(call.options.headers['X-Admin-Config-Token'], 'write-memory-token');
  assert.equal(call.url.includes('write-memory-token'), false);
  assert.equal(call.options.body.includes('write-memory-token'), false);
});

test('缺少独立写凭据时客户端拒绝 Config PATCH', async () => {
  assert.throws(
    () => updateAdminConfig('viewer-memory-token', '', {
      changes: { report_visible: false }, expected_version: 1, reason: 'test', dry_run: true,
    }),
    error => error instanceof AdminApiError && error.code === 'ADMIN_CONFIG_WRITE_AUTH_REQUIRED',
  );
});

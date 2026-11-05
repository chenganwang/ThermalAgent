import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  documentStatusPresentation,
  indexStatusPresentation,
  jobStatusPresentation,
  modelStatusPresentation,
  normalizeChunk,
  normalizeDocument,
  normalizeModel,
  candidateParticipationPresentation,
  qualityPresentation,
} from './presentation/adminPresentation.js';
import {
  applyPageReparsePreview,
  buildKnowledgeIndexCandidate,
  editDocumentChunk,
  editStagedChunk,
  excludeStagedChunk,
  enableSimulationModel,
  releaseKnowledgeIndexCandidate,
  restoreDocumentChunk,
  restoreDocumentOriginalChunk,
  restoreStagedChunk,
  includeStagedChunk,
  retryAdminJob,
  uploadKnowledgeDocument,
  withdrawKnowledgeStaging,
  validateKnowledgeIndexCandidate,
} from './api/adminClient.js';


test('Admin V1 presentation does not expose raw paths or internal metadata', () => {
  const document = normalizeDocument({
    document_id: 9,
    title: 'Cooling guide',
    filename: 'guide.pdf',
    local_path: 'F:\\secret\\guide.pdf',
    storage_path: '/srv/private/guide.pdf',
    chunks: 12,
    status: 'active',
  });
  assert.equal(document.filename, 'guide.pdf');
  assert.equal('local_path' in document, false);
  assert.equal('storage_path' in document, false);
  assert.equal(documentStatusPresentation(document.status).label, '已入库');
});

test('Original file presentation follows the canonical backend capability contract', () => {
  const available = normalizeDocument({
    document_id: 11,
    original_available: false,
    original_file: {
      available: true,
      open_supported: true,
      download_supported: true,
      state: 'available',
      reason: null,
    },
  });
  assert.equal(available.originalAvailable, true);
  assert.equal(available.originalOpenSupported, true);
  assert.equal(available.originalDownloadSupported, true);
  assert.equal(available.originalFileState, 'available');

  const integrityError = normalizeDocument({
    document_id: 12,
    original_file: {
      available: false,
      open_supported: false,
      download_supported: false,
      state: 'integrity_error',
      reason: 'integrity_error',
    },
  });
  assert.equal(integrityError.originalAvailable, false);
  assert.equal(integrityError.originalFileMessage, '原文件校验失败。');
});

test('Document detail enables each original-file action from backend capabilities and explains failures', () => {
  const source = readFileSync(new URL('./pages/KnowledgeDocumentPage.jsx', import.meta.url), 'utf8');
  assert.match(source, /disabled=\{!detail\?\.originalOpenSupported\}/);
  assert.match(source, /disabled=\{!detail\?\.originalDownloadSupported\}/);
  assert.match(source, /detail\.originalFileMessage/);
});

test('Model and job states have honest Chinese presentation', () => {
  assert.equal(modelStatusPresentation('pending_approval').label, '待审核');
  assert.equal(modelStatusPresentation('preparation_only').label, '仅登记，不可执行');
  assert.equal(modelStatusPresentation('validation_failed').color, 'error');
  assert.equal(jobStatusPresentation('queued').label, '等待中');
  assert.equal(jobStatusPresentation('running').label, '执行中');
  assert.equal(jobStatusPresentation('succeeded').label, '已完成');
  assert.equal(jobStatusPresentation('failed').color, 'error');
  const model = normalizeModel({ model_id: 'solver_v2', version: '2.0.0', status: 'preparation_only', execution_allowed: false, allowlist: false });
  assert.equal(model.executionLabel, '不可执行');
  assert.equal(model.allowlistLabel, '未授权');
});

test('Admin access and navigation use product language without frontend self-promotion', () => {
  const guard = readFileSync(new URL('./auth/AuthGuard.jsx', import.meta.url), 'utf8');
  const auth = readFileSync(new URL('./auth/AdminAuthContext.jsx', import.meta.url), 'utf8');
  const layout = readFileSync(new URL('./layouts/AdminLayout.jsx', import.meta.url), 'utf8');
  for (const label of ['管理控制台', '系统概览', '知识库', '仿真模型', '任务记录', '操作记录', '系统']) {
    assert.equal(`${guard}\n${layout}`.includes(label), true, `missing product label: ${label}`);
  }
  for (const forbidden of ['Viewer Token', 'Workflow Credential', 'AdminIdentity', 'React 内存', 'localStorage', 'sessionStorage', 'Control Center', "label: 'Jobs'", "label: 'System'"]) {
    assert.equal(`${guard}\n${layout}`.includes(forbidden), false, `visible implementation term: ${forbidden}`);
  }
  assert.equal(auth.includes('location.hostname'), false);
});

test('System technical fields require an explicitly collapsed advanced diagnostics disclosure', () => {
  const source = readFileSync(new URL('./pages/SystemPage.jsx', import.meta.url), 'utf8');
  assert.match(source, /查看高级诊断/);
  assert.match(source, /JsonPreview/);
  assert.doesNotMatch(source, /System Diagnostics|Required\/Optional|危险运维入口未开放/);
});

test('Primary knowledge and model workflows use administrator-facing steps', () => {
  const knowledge = readFileSync(new URL('./pages/KnowledgePage.jsx', import.meta.url), 'utf8');
  const models = readFileSync(new URL('./pages/SimulationModelsPage.jsx', import.meta.url), 'utf8');
  for (const label of ['1 上传文件', '2 检查内容', '3 预览切分', '4 确认入库', '5 完成']) {
    assert.equal(knowledge.includes(label), true, `missing knowledge step: ${label}`);
  }
  for (const forbidden of ['canonical writer', 'readback', '生产索引', '上传到 Staging', 'Canonical Manifest (JSON)', 'dispatcher allowlist']) {
    assert.equal(`${knowledge}\n${models}`.includes(forbidden), false, `visible technical workflow term: ${forbidden}`);
  }
  assert.equal(models.includes("title: '执行权限'"), true);
  assert.equal(models.includes("title: '测试状态'"), true);
});

test('Knowledge multipart upload keeps both credentials in headers only', async () => {
  const previousFetch = globalThis.fetch;
  let call;
  globalThis.fetch = async (url, options) => {
    call = { url: String(url), options };
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'request-admin-v1' },
      json: async () => ({ success: true, request_id: 'request-admin-v1', data: { staging_id: 'docstage-1', status: 'uploaded' } }),
    };
  };
  try {
    const form = new FormData();
    form.append('file', new Blob(['safe'], { type: 'application/pdf' }), 'guide.pdf');
    await uploadKnowledgeDocument('viewer-secret', 'workflow-secret', form);
  } finally {
    globalThis.fetch = previousFetch;
  }
  assert.equal(call.options.headers['X-Admin-Token'], 'viewer-secret');
  assert.equal(call.options.headers['X-Admin-Workflow-Token'], 'workflow-secret');
  assert.equal(call.url.includes('workflow-secret'), false);
  assert.equal(call.options.body instanceof FormData, true);
  assert.equal('Content-Type' in call.options.headers, false);
});

test('Model enable and safe job retry use fixed workflow routes', async () => {
  const previousFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'request-admin-v1' },
      json: async () => ({ success: true, request_id: 'request-admin-v1', data: {} }),
    };
  };
  try {
    await enableSimulationModel('viewer-secret', 'workflow-secret', 'asset-a1');
    await retryAdminJob('viewer-secret', 'workflow-secret', 'job-0123456789abcdef0123456789abcdef');
  } finally {
    globalThis.fetch = previousFetch;
  }
  assert.equal(calls[0].url.endsWith('/simulation-models/asset-a1/enable'), true);
  assert.equal(calls[1].url.endsWith('/jobs/job-0123456789abcdef0123456789abcdef/retry'), true);
  assert.equal(calls.every(call => call.options.headers['X-Admin-Workflow-Token'] === 'workflow-secret'), true);
});

test('Content fragment drawer exposes server-side keyword search', () => {
  const source = readFileSync(new URL('./pages/KnowledgePage.jsx', import.meta.url), 'utf8');
  assert.match(source, /aria-label="搜索待处理文件内容片段"/);
  assert.match(source, /getStagedChunks\(token, item\.stagingId, \{ query:/);
});

test('Knowledge correction presentation maps quality and index state without exposing raw metadata', () => {
  assert.equal(qualityPresentation('normal').label, '正常');
  assert.equal(qualityPresentation('needs_review').label, '建议复核');
  assert.equal(qualityPresentation('suspected_parse_error').label, '疑似解析异常');
  assert.equal(indexStatusPresentation('synced').label, '索引已同步');
  assert.equal(indexStatusPresentation('stale').label, '索引待更新');
  assert.equal(indexStatusPresentation('candidate').label, '候选索引已生成');
  assert.equal(indexStatusPresentation('release_failed').label, '发布未生效');
  const chunk = normalizeChunk({
    chunk_id: 17,
    chunk_index: 2,
    text: 'corrected text',
    raw_text: 'parser text',
    effective_text: 'corrected text',
    version: 3,
    quality: { state: 'needs_review', issues: [{ code: 'too_short' }] },
    index_status: 'stale',
    metadata: { storage_path: 'F:\\private\\source.pdf' },
  });
  assert.equal(chunk.rawText, 'parser text');
  assert.equal(chunk.effectiveText, 'corrected text');
  assert.equal(chunk.version, 3);
  assert.equal(chunk.qualityState, 'needs_review');
  assert.equal(chunk.indexStatus, 'stale');
  assert.equal('metadata' in chunk, false);
});

test('Knowledge correction API client uses fixed workflow routes and credentials', async () => {
  const previousFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'request-knowledge-correction' },
      json: async () => ({ success: true, request_id: 'request-knowledge-correction', data: {} }),
    };
  };
  try {
    await editStagedChunk('reader', 'writer', 'docstage-abc', 2, { effective_text: 'new', reason: 'fix', base_version: 0, idempotency_key: 'edit-1' });
    await restoreStagedChunk('reader', 'writer', 'docstage-abc', 2, { reason: 'restore', base_version: 1, idempotency_key: 'restore-1' });
    await editDocumentChunk('reader', 'writer', 8, 42, { effective_text: 'new', reason: 'fix', base_version: 0, idempotency_key: 'edit-2' });
    await restoreDocumentChunk('reader', 'writer', 8, 42, { revision_id: 'chunk-rev-a', reason: 'restore', base_version: 1, idempotency_key: 'restore-2' });
    await restoreDocumentOriginalChunk('reader', 'writer', 8, 42, { reason: 'restore original', base_version: 2, idempotency_key: 'restore-original-2' });
    await applyPageReparsePreview('reader', 'writer', 'reparse-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'apply-1');
    await buildKnowledgeIndexCandidate('reader', 'writer');
    await validateKnowledgeIndexCandidate('reader', 'writer', 'indexcand-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
    await releaseKnowledgeIndexCandidate('reader', 'writer', 'indexcand-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
  } finally {
    globalThis.fetch = previousFetch;
  }
  const suffixes = calls.map(call => call.url.replace(/^.*\/admin\/api\/v1/, ''));
  assert.deepEqual(suffixes, [
    '/knowledge/staging/docstage-abc/chunks/2',
    '/knowledge/staging/docstage-abc/chunks/2/restore',
    '/knowledge/documents/8/chunks/42',
    '/knowledge/documents/8/chunks/42/restore',
    '/knowledge/documents/8/chunks/42/restore-original',
    '/knowledge/reparse-previews/reparse-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/apply',
    '/knowledge/index-sync/candidates',
    '/knowledge/index-sync/candidates/indexcand-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/validate',
    '/knowledge/index-sync/candidates/indexcand-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/release',
  ]);
  assert.equal(calls.every(call => call.options.headers['X-Admin-Workflow-Token'] === 'writer'), true);
});

test('Knowledge pages expose edit, restore, reparse and controlled index actions', () => {
  const staging = readFileSync(new URL('./pages/KnowledgePage.jsx', import.meta.url), 'utf8');
  const persisted = readFileSync(new URL('./pages/KnowledgeDocumentPage.jsx', import.meta.url), 'utf8');
  for (const label of ['编辑片段', '恢复解析文本', '质量状态']) assert.equal(staging.includes(label), true, `missing staged action: ${label}`);
  for (const label of ['修订片段', '修订历史', '重新解析本页', '生成候选索引', '索引待更新']) assert.equal(persisted.includes(label), true, `missing persisted action: ${label}`);
  assert.match(persisted, /rowKey="chunkId"/, 'normalized chunk rows need a stable React key');
});

test('Staged candidate presentation keeps exclusion separate from text editing', () => {
  const excluded = normalizeChunk({
    chunk_index: 4,
    raw_text: 'parser output',
    effective_text: 'reviewed output',
    edit_state: 'edited',
    participation_state: 'excluded',
  });
  assert.equal(excluded.participationState, 'excluded');
  assert.equal(excluded.included, false);
  assert.equal(excluded.effectiveText, 'reviewed output');
  assert.equal(candidateParticipationPresentation(excluded.participationState).label, '已排除');
  assert.equal(candidateParticipationPresentation('included').label, '参与入库');
});

test('Staging lifecycle API client uses fixed workflow routes', async () => {
  const previousFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'request-staging-lifecycle' },
      json: async () => ({ success: true, request_id: 'request-staging-lifecycle', data: {} }),
    };
  };
  try {
    await excludeStagedChunk('reader', 'writer', 'docstage-abc', 2, { reason: 'exclude', idempotency_key: 'exclude-2' });
    await includeStagedChunk('reader', 'writer', 'docstage-abc', 2, { reason: 'restore', idempotency_key: 'include-2' });
    await withdrawKnowledgeStaging('reader', 'writer', 'docstage-abc', { reason: 'withdraw', idempotency_key: 'withdraw-1' });
  } finally {
    globalThis.fetch = previousFetch;
  }
  assert.deepEqual(calls.map(call => call.url.replace(/^.*\/admin\/api\/v1/, '')), [
    '/knowledge/staging/docstage-abc/chunks/2/exclude',
    '/knowledge/staging/docstage-abc/chunks/2/include',
    '/knowledge/staging/docstage-abc/withdraw',
  ]);
  assert.equal(calls.every(call => call.options.headers['X-Admin-Workflow-Token'] === 'writer'), true);
});

test('Knowledge staging UI exposes lifecycle confirmations and effective counts in product language', () => {
  const source = readFileSync(new URL('./pages/KnowledgePage.jsx', import.meta.url), 'utf8');
  for (const label of ['从本次入库中移除', '恢复片段', '撤回文件', '总片段', '参与入库', '已排除', '建议复核', '疑似解析异常']) {
    assert.equal(source.includes(label), true, `missing staging lifecycle label: ${label}`);
  }
  assert.match(source, /确认从本次入库中移除此片段？/);
  assert.match(source, /该操作不会修改原始文件，可以在确认入库前恢复。/);
  assert.match(source, /确认撤回该待入库文件？/);
  assert.match(source, /撤回后将清理本次上传产生的预览和修改，不会影响已经入库的知识。/);
  for (const forbidden of ['excluded=true', 'candidate_state', 'writer_count']) assert.equal(source.includes(forbidden), false);
});

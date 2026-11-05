import { API_BASE_URL } from '../../api/client.js';

const ADMIN_PREFIX = '/admin/api/v1';
const DEFAULT_TIMEOUT_MS = 10_000;

export class AdminApiError extends Error {
  constructor(message, { statusCode = null, code = null, requestId = null, payload = null } = {}) {
    super(message || '管理请求失败。');
    this.name = 'AdminApiError';
    this.statusCode = statusCode;
    this.code = code;
    this.requestId = requestId;
    this.payload = payload;
  }
}

function requestId() {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `admin-ui-${random}`;
}

function apiUrl(path) {
  return `${API_BASE_URL}${ADMIN_PREFIX}${path.startsWith('/') ? path : `/${path}`}`;
}

async function adminRequest(path, {
  token,
  writeToken,
  workflowToken,
  method = 'GET',
  body,
  formData,
  timeoutMs = DEFAULT_TIMEOUT_MS,
} = {}) {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(apiUrl(path), {
      method,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(typeof token === 'string' && token.trim() ? { 'X-Admin-Token': token.trim() } : {}),
        'X-Request-ID': requestId(),
        ...(typeof writeToken === 'string' && writeToken.trim() ? { 'X-Admin-Config-Token': writeToken.trim() } : {}),
        ...(typeof workflowToken === 'string' && workflowToken.trim() ? { 'X-Admin-Workflow-Token': workflowToken.trim() } : {}),
        ...(body === undefined || formData ? {} : { 'Content-Type': 'application/json' }),
      },
      ...(formData ? { body: formData } : body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || payload?.success !== true) {
      const error = payload?.error || {};
      throw new AdminApiError(error.message || `HTTP ${response.status}`, {
        statusCode: response.status,
        code: error.code || null,
        requestId: payload?.request_id || response.headers.get('X-Request-ID'),
        payload,
      });
    }
    return payload.data;
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new AdminApiError('管理请求超时。', { code: 'CLIENT_TIMEOUT' });
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

function requireWorkflowToken(workflowToken) {
  if (workflowToken !== true && (typeof workflowToken !== 'string' || !workflowToken.trim())) {
    throw new AdminApiError('Workflow write credential is required.', {
      statusCode: 401,
      code: 'ADMIN_WORKFLOW_WRITE_AUTH_REQUIRED',
    });
  }
}

export function getAdminSession(token) {
  return adminRequest('/session', { token });
}

export function getAdminOverview(token) {
  return adminRequest('/overview', { token });
}

export function getKnowledgeCoverage(token) {
  return adminRequest('/knowledge/coverage', { token });
}

export function getAgentTasks(token, filters = {}) {
  return adminRequest(`/agent-tasks${queryString(filters)}`, { token });
}

export function getAgentTask(token, taskId) {
  return adminRequest(`/agent-tasks/${encodeURIComponent(taskId)}`, { token });
}

export function getAdminModules(token, filters = {}) {
  const search = new URLSearchParams();
  if (filters.category) search.set('category', filters.category);
  if (filters.status) search.set('status', filters.status);
  const suffix = search.toString();
  return adminRequest(`/modules${suffix ? `?${suffix}` : ''}`, { token });
}

export function getAdminModule(token, moduleId) {
  return adminRequest(`/modules/${encodeURIComponent(moduleId)}`, { token });
}

export function checkAdminModule(token, moduleId) {
  return adminRequest(`/modules/${encodeURIComponent(moduleId)}/check`, { token, method: 'POST' });
}

export function checkAllAdminModules(token) {
  return adminRequest('/modules/check-all', { token, method: 'POST' });
}

export function getAdminAudit(token, { limit = 50, cursor = null } = {}) {
  const search = new URLSearchParams({ limit: String(limit) });
  if (cursor) search.set('cursor', cursor);
  return adminRequest(`/audit?${search}`, { token });
}

export function getAdminAuditEvent(token, auditId) {
  return adminRequest(`/audit/${encodeURIComponent(auditId)}`, { token });
}

export function getAdminConfig(token) {
  return adminRequest('/config', { token });
}

export function getAdminConfigSchema(token) {
  return adminRequest('/config/schema', { token });
}

export function getAdminConfigHistory(token, { limit = 50, cursor = null } = {}) {
  const search = new URLSearchParams({ limit: String(limit) });
  if (cursor) search.set('cursor', cursor);
  return adminRequest(`/config/history?${search}`, { token });
}

export function updateAdminConfig(token, writeToken, payload) {
  if (writeToken !== true && (typeof writeToken !== 'string' || !writeToken.trim())) {
    throw new AdminApiError('Config write credential is required.', {
      statusCode: 401,
      code: 'ADMIN_CONFIG_WRITE_AUTH_REQUIRED',
    });
  }
  return adminRequest('/config', { token, writeToken, method: 'PATCH', body: payload });
}

export function rollbackAdminConfig(token, writeToken, payload) {
  if (writeToken !== true && (typeof writeToken !== 'string' || !writeToken.trim())) {
    throw new AdminApiError('Config write credential is required.', {
      statusCode: 401,
      code: 'ADMIN_CONFIG_WRITE_AUTH_REQUIRED',
    });
  }
  return adminRequest('/config/rollback', { token, writeToken, method: 'POST', body: payload });
}

export function getAdminActions(token, filters = {}) {
  const search = new URLSearchParams();
  if (filters.category) search.set('category', filters.category);
  if (filters.riskLevel) search.set('risk_level', filters.riskLevel);
  if (typeof filters.enabled === 'boolean') search.set('enabled', String(filters.enabled));
  if (typeof filters.available === 'boolean') search.set('available', String(filters.available));
  const suffix = search.toString();
  return adminRequest(`/actions${suffix ? `?${suffix}` : ''}`, { token });
}

export function getAdminAction(token, actionId) {
  return adminRequest(`/actions/${encodeURIComponent(actionId)}`, { token });
}

export function dryRunAdminAction(token, actionId, parameters = {}) {
  return adminRequest(`/actions/${encodeURIComponent(actionId)}/dry-run`, {
    token,
    method: 'POST',
    body: { parameters },
  });
}

export function invokeAdminAction(token, actionId, parameters = {}) {
  return adminRequest(`/actions/${encodeURIComponent(actionId)}/invoke`, {
    token,
    method: 'POST',
    body: { parameters },
  });
}

export function getAdminDashboard(token) {
  return adminRequest('/dashboard', { token });
}

export function getKnowledgeStaging(token) {
  return adminRequest('/knowledge/staging', { token });
}

export function uploadKnowledgeDocument(token, workflowToken, formData) {
  requireWorkflowToken(workflowToken);
  return adminRequest('/knowledge/staging/upload', { token, workflowToken, method: 'POST', formData });
}

export function preflightKnowledgeDocument(token, workflowToken, stagingId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/staging/${encodeURIComponent(stagingId)}/preflight`, { token, workflowToken, method: 'POST' });
}

export function dryRunKnowledgeDocument(token, workflowToken, stagingId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/staging/${encodeURIComponent(stagingId)}/dry-run`, { token, workflowToken, method: 'POST' });
}

export function commitKnowledgeDocument(token, workflowToken, stagingId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/staging/${encodeURIComponent(stagingId)}/commit`, { token, workflowToken, method: 'POST' });
}

export function getStagedChunks(token, stagingId, filters = {}) {
  const search = queryString(filters);
  return adminRequest(`/knowledge/staging/${encodeURIComponent(stagingId)}/chunks${search}`, { token });
}

export function getStagedChunk(token, stagingId, chunkIndex) {
  return adminRequest(`/knowledge/staging/${encodeURIComponent(stagingId)}/chunks/${encodeURIComponent(chunkIndex)}`, { token });
}

export function editStagedChunk(token, workflowToken, stagingId, chunkIndex, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/staging/${encodeURIComponent(stagingId)}/chunks/${encodeURIComponent(chunkIndex)}`, {
    token, workflowToken, method: 'PUT', body: payload,
  });
}

export function restoreStagedChunk(token, workflowToken, stagingId, chunkIndex, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/staging/${encodeURIComponent(stagingId)}/chunks/${encodeURIComponent(chunkIndex)}/restore`, {
    token, workflowToken, method: 'POST', body: payload,
  });
}

export function excludeStagedChunk(token, workflowToken, stagingId, chunkIndex, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/staging/${encodeURIComponent(stagingId)}/chunks/${encodeURIComponent(chunkIndex)}/exclude`, {
    token, workflowToken, method: 'POST', body: payload,
  });
}

export function includeStagedChunk(token, workflowToken, stagingId, chunkIndex, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/staging/${encodeURIComponent(stagingId)}/chunks/${encodeURIComponent(chunkIndex)}/include`, {
    token, workflowToken, method: 'POST', body: payload,
  });
}

export function withdrawKnowledgeStaging(token, workflowToken, stagingId, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/staging/${encodeURIComponent(stagingId)}/withdraw`, {
    token, workflowToken, method: 'POST', body: payload,
  });
}

export function getKnowledgeDocuments(token, filters = {}) {
  return adminRequest(`/knowledge/documents${queryString(filters)}`, { token });
}

export function getKnowledgeDocument(token, documentId) {
  return adminRequest(`/knowledge/documents/${encodeURIComponent(documentId)}`, { token });
}

export function getDocumentChunks(token, documentId, filters = {}) {
  return adminRequest(`/knowledge/documents/${encodeURIComponent(documentId)}/chunks${queryString(filters)}`, { token });
}

export function getDocumentChunk(token, documentId, chunkId) {
  return adminRequest(`/knowledge/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`, { token });
}

export function editDocumentChunk(token, workflowToken, documentId, chunkId, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`, {
    token, workflowToken, method: 'PUT', body: payload,
  });
}

export function restoreDocumentChunk(token, workflowToken, documentId, chunkId, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}/restore`, {
    token, workflowToken, method: 'POST', body: payload,
  });
}

export function restoreDocumentOriginalChunk(token, workflowToken, documentId, chunkId, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}/restore-original`, {
    token, workflowToken, method: 'POST', body: payload,
  });
}

export function createPageReparsePreview(token, workflowToken, documentId, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/documents/${encodeURIComponent(documentId)}/reparse-previews`, {
    token, workflowToken, method: 'POST', body: payload, timeoutMs: 30_000,
  });
}

export function getPageReparsePreview(token, previewId) {
  return adminRequest(`/knowledge/reparse-previews/${encodeURIComponent(previewId)}`, { token });
}

export function applyPageReparsePreview(token, workflowToken, previewId, idempotencyKey) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/reparse-previews/${encodeURIComponent(previewId)}/apply`, {
    token, workflowToken, method: 'POST', body: { idempotency_key: idempotencyKey },
  });
}

export function getKnowledgeIndexSync(token) {
  return adminRequest('/knowledge/index-sync', { token });
}

export function buildKnowledgeIndexCandidate(token, workflowToken) {
  requireWorkflowToken(workflowToken);
  return adminRequest('/knowledge/index-sync/candidates', { token, workflowToken, method: 'POST', timeoutMs: 120_000 });
}

export function validateKnowledgeIndexCandidate(token, workflowToken, candidateId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/index-sync/candidates/${encodeURIComponent(candidateId)}/validate`, {
    token, workflowToken, method: 'POST', timeoutMs: 60_000,
  });
}

export function releaseKnowledgeIndexCandidate(token, workflowToken, candidateId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/knowledge/index-sync/candidates/${encodeURIComponent(candidateId)}/release`, {
    token, workflowToken, method: 'POST', timeoutMs: 60_000,
  });
}

export function documentContentUrl(documentId, { download = false } = {}) {
  const suffix = download ? '?download=true' : '';
  return apiUrl(`/knowledge/documents/${encodeURIComponent(documentId)}/content${suffix}`);
}

export async function fetchDocumentContent(token, documentId, { download = false } = {}) {
  const response = await fetch(documentContentUrl(documentId, { download }), {
    headers: {
      Accept: '*/*',
      ...(typeof token === 'string' && token.trim() ? { 'X-Admin-Token': token.trim() } : {}),
      'X-Request-ID': requestId(),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new AdminApiError(payload?.error?.message || `HTTP ${response.status}`, {
      statusCode: response.status,
      code: payload?.error?.code || null,
      requestId: payload?.request_id || response.headers.get('X-Request-ID'),
      payload,
    });
  }
  return {
    blob: await response.blob(),
    disposition: response.headers.get('Content-Disposition') || '',
  };
}

export function getKnowledgeUnits(token, filters = {}) {
  return adminRequest(`/knowledge/units${queryString(filters)}`, { token });
}

export function getSimulationModels(token, filters = {}) {
  return adminRequest(`/simulation-models${queryString(filters)}`, { token });
}

export function getGeneratedModels(token, filters = {}) {
  return adminRequest(`/generated-models${queryString(filters)}`, { token });
}

export function getGeneratedModel(token, generationId) {
  return adminRequest(`/generated-models/${encodeURIComponent(generationId)}`, { token });
}

export function compileGeneratedModel(token, workflowToken, generationId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/generated-models/${encodeURIComponent(generationId)}/compile`, {
    token, workflowToken, method: 'POST', timeoutMs: 120_000,
  });
}

export function approveGeneratedModel(token, workflowToken, generationId, reason) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/generated-models/${encodeURIComponent(generationId)}/approve`, {
    token, workflowToken, method: 'POST', body: { reason },
  });
}

export function rejectGeneratedModel(token, workflowToken, generationId, reason) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/generated-models/${encodeURIComponent(generationId)}/reject`, {
    token, workflowToken, method: 'POST', body: { reason },
  });
}

export function enableGeneratedModel(token, workflowToken, generationId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/generated-models/${encodeURIComponent(generationId)}/enable`, {
    token, workflowToken, method: 'POST',
  });
}

export function disableGeneratedModel(token, workflowToken, generationId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/generated-models/${encodeURIComponent(generationId)}/disable`, {
    token, workflowToken, method: 'POST',
  });
}

export function updateGeneratedModelMetadata(token, workflowToken, generationId, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/generated-models/${encodeURIComponent(generationId)}/metadata`, {
    token, workflowToken, method: 'PATCH', body: payload,
  });
}

export function createGeneratedModelRevision(token, workflowToken, generationId, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/generated-models/${encodeURIComponent(generationId)}/revisions`, {
    token, workflowToken, method: 'POST', body: payload,
  });
}

export function promoteGeneratedModel(token, workflowToken, generationId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/generated-models/${encodeURIComponent(generationId)}/promote`, {
    token, workflowToken, method: 'POST',
  });
}

export function deleteGeneratedModel(token, workflowToken, generationId, reason) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/generated-models/${encodeURIComponent(generationId)}`, {
    token, workflowToken, method: 'DELETE', body: { reason },
  });
}

export function previewGeneratedModelGc(token) {
  return adminRequest('/generated-models-gc/preview', { token });
}

export function uploadSimulationModel(token, workflowToken, formData) {
  requireWorkflowToken(workflowToken);
  return adminRequest('/simulation-models/upload', { token, workflowToken, method: 'POST', formData, timeoutMs: 30_000 });
}

export function getSimulationModel(token, assetId, { includeCode = false } = {}) {
  const suffix = includeCode ? '?include_code=true' : '';
  return adminRequest(`/simulation-models/${encodeURIComponent(assetId)}${suffix}`, { token });
}

export function approveSimulationModel(token, workflowToken, assetId, payload) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/simulation-models/${encodeURIComponent(assetId)}/approve`, { token, workflowToken, method: 'POST', body: payload });
}

export function rejectSimulationModel(token, workflowToken, assetId, reason) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/simulation-models/${encodeURIComponent(assetId)}/reject`, { token, workflowToken, method: 'POST', body: { reason } });
}

export function enableSimulationModel(token, workflowToken, assetId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/simulation-models/${encodeURIComponent(assetId)}/enable`, { token, workflowToken, method: 'POST' });
}

export function disableSimulationModel(token, workflowToken, assetId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/simulation-models/${encodeURIComponent(assetId)}/disable`, { token, workflowToken, method: 'POST' });
}

export function smokeSimulationModel(token, workflowToken, assetId, realResourceOptIn = false) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/simulation-models/${encodeURIComponent(assetId)}/smoke`, { token, workflowToken, method: 'POST', body: { real_resource_opt_in: realResourceOptIn } });
}

export function getAdminJobs(token, filters = {}) {
  return adminRequest(`/jobs${queryString(filters)}`, { token });
}

export function getAdminJob(token, jobId) {
  return adminRequest(`/jobs/${encodeURIComponent(jobId)}`, { token });
}

export function retryAdminJob(token, workflowToken, jobId) {
  requireWorkflowToken(workflowToken);
  return adminRequest(`/jobs/${encodeURIComponent(jobId)}/retry`, { token, workflowToken, method: 'POST' });
}

export function getWorkflowAudit(token, filters = {}) {
  return adminRequest(`/workflow-audit${queryString(filters)}`, { token });
}

export function getAdminSystem(token) {
  return adminRequest('/system', { token });
}

function queryString(filters = {}) {
  const search = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  });
  const value = search.toString();
  return value ? `?${value}` : '';
}

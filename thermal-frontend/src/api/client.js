import { notifyCapabilitiesChanged } from '../capabilityEvents.js';

const DEFAULT_API_BASE_URL = '/api';
export const DEFAULT_REQUEST_TIMEOUT_MS = 15_000;
export const AGENT_REQUEST_TIMEOUT_MS = 180_000;

export const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/+$/, '');
export const USE_MOCK_RESPONSES = import.meta.env?.VITE_USE_MOCK_RESPONSES === 'true';

export function buildApiUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
}

async function fetchJson(path, options = {}, asBlob = false) {
  const isMultipart = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const response = await fetch(buildApiUrl(path), {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body && !isMultipart ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });

  if (response.ok && asBlob) return response.blob();

  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const detail = typeof payload === 'object' && payload !== null ? payload.detail ?? payload.message : payload;
    const structuredDetail = detail && typeof detail === 'object' ? detail : null;
    const message = typeof detail === 'string'
      ? detail
      : structuredDetail?.error?.message
        || structuredDetail?.message
        || structuredDetail?.error?.code
        || structuredDetail?.status
        || `HTTP ${response.status}`;
    throw new ApiError(message, { statusCode: response.status, payload });
  }

  return payload;
}

// A deadline covers both response headers and body consumption. Stopping this
// wait never retries a POST or claims that a backend operation was cancelled.
async function requestJson(path, options = {}, asBlob = false) {
  const { signal, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, ...requestOptions } = options;
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason instanceof Error ? signal.reason : new DOMException('Stopped waiting for the response', 'AbortError'));
  if (signal?.aborted) { abort(); throw controller.signal.reason; }
  signal?.addEventListener('abort', abort, { once: true });
  const deadline = Number.isFinite(timeoutMs) && timeoutMs > 0 ? Math.min(timeoutMs, 300_000) : DEFAULT_REQUEST_TIMEOUT_MS;
  const timer = globalThis.setTimeout(() => controller.abort(new DOMException('后端响应等待超时；后台操作可能仍在运行，请先核对任务或仿真记录。', 'TimeoutError')), deadline);
  try {
    const result = await fetchJson(path, { ...requestOptions, signal: controller.signal }, asBlob);
    if (controller.signal.aborted) throw controller.signal.reason;
    return result;
  } catch (error) {
    if (controller.signal.aborted) throw controller.signal.reason;
    throw error;
  } finally {
    globalThis.clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

export function requestFailureMessage(error) {
  if (error?.name === 'TimeoutError') return '后端响应等待超时。后台操作可能仍在运行；请先核对任务或仿真记录，不会自动重新提交。';
  if (error?.name === 'AbortError') return '已停止等待本次响应。后台操作可能仍在运行；请先核对任务或仿真记录，不会自动重新提交。';
  return `后端请求失败：${error?.message || '未知错误'}`;
}

export class ApiError extends Error {
  constructor(message, { statusCode, payload } = {}) {
    super(message || `HTTP ${statusCode || 'error'}`);
    this.name = 'ApiError';
    this.statusCode = statusCode || null;
    this.payload = payload ?? null;
    this.detail = payload && typeof payload === 'object' ? payload.detail ?? null : null;
  }
}

export function getCapabilities(options = {}) {
  return requestJson('/capabilities', options);
}

export function answerAgent({
  query,
  sessionId = 'frontend-session',
  topK = 5,
  requestedOutputs = [],
  analysisReportMode = false,
  uploadedModelFileId = null,
  uploadedModelFilename = null,
  simulationMode = false,
  simulationAction = null,
  simulationPlanId = null,
} = {}, options = {}) {
  return requestJson('/agent/answer', {
    timeoutMs: AGENT_REQUEST_TIMEOUT_MS,
    ...options,
    method: 'POST',
    body: JSON.stringify({
      query,
      session_id: sessionId,
      top_k: topK,
      requested_outputs: requestedOutputs,
      analysis_report_mode: analysisReportMode,
      uploaded_model_file_id: uploadedModelFileId,
      uploaded_model_filename: uploadedModelFilename,
      simulation_mode: Boolean(simulationMode),
      simulation_action: simulationAction,
      simulation_plan_id: simulationPlanId,
    }),
  });
}

export function exportAgentReport({
  query,
  sessionId = 'frontend-session',
  topK = 5,
  requestedOutputs = ['report'],
  uploadedModelFilename = null,
  title = null,
} = {}, options = {}) {
  return requestJson('/agent/analyze/export', {
    timeoutMs: AGENT_REQUEST_TIMEOUT_MS,
    ...options,
    method: 'POST',
    body: JSON.stringify({
      query,
      session_id: sessionId,
      top_k: topK,
      export_report: true,
      export_format: 'md',
      requested_outputs: requestedOutputs,
      uploaded_model_filename: uploadedModelFilename,
      title,
    }),
  });
}

export function getReportStatus(options = {}) {
  return requestJson('/report/status', options);
}

export function getSimulationStatus(options = {}) {
  return requestJson('/simulation/status', options);
}

export function getMatlabStatus(options = {}) {
  return requestJson('/simulation/matlab/status', options);
}

export function runMatlabDemo({ demoName = 'basic_numeric', params = {} } = {}, options = {}) {
  return requestJson('/simulation/matlab/demo', {
    timeoutMs: AGENT_REQUEST_TIMEOUT_MS,
    ...options,
    method: 'POST',
    body: JSON.stringify({
      demo_name: demoName,
      params,
    }),
  });
}

function withQuery(path, query = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value));
  }
  const suffix = search.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export function getSimulationCatalog() {
  return requestJson('/simulation/catalog');
}

export function getSimulationScenarios({ domain, solver, status } = {}) {
  return requestJson(withQuery('/simulation/scenarios', { domain, solver, status }));
}

export function getSimulationScenario(scenarioId) {
  return requestJson(`/simulation/scenarios/${encodeURIComponent(scenarioId)}`);
}

export function getSimulationModels({ scenarioId, solver, status } = {}) {
  return requestJson(withQuery('/simulation/models', {
    scenario_id: scenarioId,
    solver,
    status,
  }));
}

export function getSimulationModel(modelId) {
  return requestJson(`/simulation/models/${encodeURIComponent(modelId)}`);
}

export function planSimulationScenario({ scenarioId, modelId, params = {} } = {}) {
  return requestJson('/simulation/plan', {
    method: 'POST',
    body: JSON.stringify({
      scenario_id: scenarioId,
      model_id: modelId,
      params,
    }),
  });
}

export function runSimulationScenario({ scenarioId, modelId, params = {} } = {}, options = {}) {
  return requestJson('/simulation/run', {
    timeoutMs: AGENT_REQUEST_TIMEOUT_MS,
    ...options,
    method: 'POST',
    body: JSON.stringify({
      scenario_id: scenarioId,
      model_id: modelId,
      params,
    }),
  });
}

export function uploadSimulationModelAsset(file) {
  const formData = new FormData();
  formData.append('file', file);
  return requestJson('/simulation/model-assets/upload', {
    method: 'POST',
    body: formData,
  });
}

export function getSimulationModelAssets() {
  return requestJson('/simulation/model-assets');
}

export function getSimulationModelAsset(assetId) {
  return requestJson(`/simulation/model-assets/${encodeURIComponent(assetId)}`);
}

export function submitSimulationModelAssetReview(assetId) {
  return requestJson(`/simulation/model-assets/${encodeURIComponent(assetId)}/submit-review`, {
    method: 'POST',
  });
}

function adminHeaders(adminToken) {
  return { 'X-Admin-Token': adminToken };
}

export function getAdminFeatureFlags(adminToken) {
  return requestJson('/admin/feature-flags', {
    headers: adminHeaders(adminToken),
  });
}

export function updateAdminFeatureFlags(adminToken, featureFlags) {
  return requestJson('/admin/feature-flags', {
    method: 'PATCH',
    headers: adminHeaders(adminToken),
    body: JSON.stringify(featureFlags),
  }).then(payload => {
    notifyCapabilitiesChanged();
    return payload;
  });
}

export function resetAdminFeatureFlags(adminToken) {
  return requestJson('/admin/feature-flags/reset', {
    method: 'POST',
    headers: adminHeaders(adminToken),
  }).then(payload => {
    notifyCapabilitiesChanged();
    return payload;
  });
}

// CFD submission returns immediately; a bounded HTTP timeout does not cancel a solver job.
async function boundedRequest(path, options = {}, asBlob = false) {
  return requestJson(path, options, asBlob);
}

function cfdRequest(path, options = {}) {
  return boundedRequest(`/simulation/cfd${path}`, options);
}

export function getCfdStatus(options = {}) {
  return cfdRequest('/status', options);
}

export function getCfdJobs(options = {}) {
  return cfdRequest('/jobs', options);
}

export function getCfdJob(jobId, options = {}) {
  return cfdRequest(`/jobs/${encodeURIComponent(jobId)}`, options);
}

export function prepareCfdJob({ case_id, iterations, processors }, options = {}) {
  return cfdRequest('/jobs', { ...options, method: 'POST', body: JSON.stringify({ case_id, iterations, processors }) });
}

export function runCfdJob(jobId, inputFingerprint, options = {}) {
  return cfdRequest(`/jobs/${encodeURIComponent(jobId)}/run`, {
    ...options,
    method: 'POST',
    body: JSON.stringify({ confirmed: true, input_fingerprint: inputFingerprint }),
  });
}

export function getCfdJobReport(jobId, options = {}) {
  return cfdRequest(`/jobs/${encodeURIComponent(jobId)}/report`, options);
}

export function getEngineeringProjects(options = {}) {
  return boundedRequest('/engineering/projects', options);
}

export function createEngineeringProject({ title, description = '' }, options = {}) {
  return boundedRequest('/engineering/projects', { ...options, method: 'POST', body: JSON.stringify({ title, description }) });
}

export function getEngineeringRuns({ projectId = 'local', limit = 30, offset = 0 } = {}, options = {}) {
  return boundedRequest(withQuery('/engineering/runs', { project_id: projectId, limit, offset }), options);
}

export function getEngineeringRun(runId, options = {}) {
  return boundedRequest(`/engineering/runs/${encodeURIComponent(runId)}`, options);
}

export function compareEngineeringRuns(runIds, options = {}) {
  return boundedRequest('/engineering/runs/compare', { ...options, method: 'POST', body: JSON.stringify({ run_ids: runIds }) });
}

export function resumeEngineeringRun(runId, revision, options = {}) {
  return boundedRequest(`/engineering/runs/${encodeURIComponent(runId)}/resume`, { ...options, method: 'POST', body: JSON.stringify({ expected_revision: revision, confirmed: true }) });
}

export function getEngineeringArtifact(runId, artifactId, options = {}) {
  return boundedRequest(`/engineering/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`, options, true);
}

export function solveReferenceWall(inputs, projectId = 'local', options = {}) {
  return boundedRequest('/engineering/reference/solve', { ...options, method: 'POST', body: JSON.stringify({ inputs, project_id: projectId }) });
}

export function submitEngineeringTask({ query, sessionId = 'frontend-session', uploadedModelFilename = null, requestedOutputs = ['report'] } = {}, options = {}) {
  return boundedRequest('/engineering/tasks', { ...options, method: 'POST', body: JSON.stringify({ query, session_id: sessionId, uploaded_model_filename: uploadedModelFilename, requested_outputs: requestedOutputs, analysis_report_mode: requestedOutputs.includes('report'), simulation_mode: false }) });
}
export function getEngineeringTasks({ limit = 20, offset = 0 } = {}, options = {}) {
  return boundedRequest(withQuery('/engineering/tasks', { limit, offset }), options);
}
export function getEngineeringTask(taskId, options = {}) {
  return boundedRequest(`/engineering/tasks/${encodeURIComponent(taskId)}`, options);
}
export function continueEngineeringTask({ query, sessionId, currentTaskId = null, currentContextKind = 'other' }, options = {}) {
  return boundedRequest('/engineering/tasks/continue', {
    ...options,
    method: 'POST',
    body: JSON.stringify({ query, session_id: sessionId, current_task_id: currentTaskId, current_context_kind: currentContextKind }),
  });
}
export function retryEngineeringTask(taskId, { revision, query } = {}, options = {}) {
  return boundedRequest(`/engineering/tasks/${encodeURIComponent(taskId)}/retry`, { ...options, method: 'POST', body: JSON.stringify({ expected_revision: revision, confirmed: true, ...(typeof query === 'string' && query.trim() ? { query: query.trim() } : {}) }) });
}
export function cancelEngineeringTask(taskId, revision, options = {}) {
  return boundedRequest(`/engineering/tasks/${encodeURIComponent(taskId)}/cancel`, { ...options, method: 'POST', body: JSON.stringify({ expected_revision: revision }) });
}

// PEM pre-screening always reaches the backend, including in offline chat mode.
export function getPemCatalog(options = {}) { return boundedRequest('/pem/catalog', options); }
export function getPemStudies(options = {}) { return boundedRequest('/pem/studies', options); }
export function createPemStudy(definition, options = {}) {
  return boundedRequest('/pem/studies', { ...options, method: 'POST', body: JSON.stringify(definition) });
}
export function getPemStudy(studyId, options = {}) { return boundedRequest(`/pem/studies/${encodeURIComponent(studyId)}`, options); }
export function generatePemDoe(studyId, { samples, seed }, options = {}) {
  return boundedRequest(`/pem/studies/${encodeURIComponent(studyId)}/doe`, { ...options, method: 'POST', body: JSON.stringify({ samples, seed }) });
}
export function getPemCandidates(studyId, options = {}) { return boundedRequest(`/pem/studies/${encodeURIComponent(studyId)}/candidates`, options); }
export function exportPemCandidates(studyId, format, options = {}) {
  if (!['csv', 'json'].includes(format)) throw new Error('候选导出仅支持 CSV 或 JSON。');
  return boundedRequest(`/pem/studies/${encodeURIComponent(studyId)}/candidates?format=${format}`, options, true);
}
export function importPemResults(studyId, payload, options = {}) {
  return boundedRequest(`/pem/studies/${encodeURIComponent(studyId)}/imports`, { ...options, method: 'POST', body: JSON.stringify(payload) });
}
export function getPemResults(studyId, options = {}) { return boundedRequest(`/pem/studies/${encodeURIComponent(studyId)}/results`, options); }
export function comparePemResults(studyId, resultIds = [], options = {}) {
  return boundedRequest(`/pem/studies/${encodeURIComponent(studyId)}/compare`, { ...options, method: 'POST', body: JSON.stringify(resultIds.length ? { result_ids: resultIds } : {}) });
}
export function exportPemReport(studyId, options = {}) { return boundedRequest(`/pem/studies/${encodeURIComponent(studyId)}/report?format=markdown`, options, true); }
export function downloadPemImportSource(studyId, importId, options = {}) { return boundedRequest(`/pem/studies/${encodeURIComponent(studyId)}/imports/${encodeURIComponent(importId)}/source`, options, true); }

const DOCUMENT_STATUS = Object.freeze({
  uploaded: { label: '已上传', color: 'default' },
  preflight_passed: { label: '预检通过', color: 'processing' },
  preflight_failed: { label: '预检失败', color: 'error' },
  dry_run_ready: { label: '预览就绪', color: 'warning' },
  withdrawn: { label: '已撤回', color: 'default' },
  ingested: { label: '已入库', color: 'success' },
  active: { label: '已入库', color: 'success' },
  inactive: { label: '已停用', color: 'default' },
});

const MODEL_STATUS = Object.freeze({
  uploaded: { label: '已上传', color: 'default' },
  validation_failed: { label: '安全检查未通过', color: 'error' },
  draft: { label: '待补充或待编译', color: 'default' },
  compiled: { label: '已编译', color: 'processing' },
  pending_approval: { label: '待审核', color: 'warning' },
  approved_file_only: { label: '文件已批准', color: 'processing' },
  preparation_only: { label: '仅登记，不可执行', color: 'blue' },
  approved: { label: '已批准，待启用', color: 'processing' },
  enabled: { label: '已启用', color: 'success' },
  execution_failed: { label: '执行失败', color: 'error' },
  disabled: { label: '已禁用', color: 'default' },
  rejected: { label: '已拒绝', color: 'error' },
});

const JOB_STATUS = Object.freeze({
  queued: { label: '等待中', color: 'default' },
  running: { label: '执行中', color: 'processing' },
  succeeded: { label: '已完成', color: 'success' },
  failed: { label: '失败', color: 'error' },
  cancelled: { label: '已取消', color: 'default' },
});

const QUALITY_STATUS = Object.freeze({
  normal: { label: '正常', color: 'success' },
  needs_review: { label: '建议复核', color: 'warning' },
  suspected_parse_error: { label: '疑似解析异常', color: 'error' },
});

const INDEX_STATUS = Object.freeze({
  synced: { label: '索引已同步', color: 'success' },
  stale: { label: '索引待更新', color: 'warning' },
  building: { label: '正在生成候选索引', color: 'processing' },
  candidate: { label: '候选索引已生成', color: 'blue' },
  candidate_ready: { label: '候选索引已生成', color: 'blue' },
  ready_to_release: { label: '候选索引已验证', color: 'processing' },
  releasing: { label: '正在发布', color: 'processing' },
  release_failed: { label: '发布未生效', color: 'error' },
  validation_failed: { label: '候选索引验证失败', color: 'error' },
});

const CANDIDATE_PARTICIPATION = Object.freeze({
  included: { label: '参与入库', color: 'processing' },
  excluded: { label: '已排除', color: 'default' },
});

function status(meta, value) {
  return meta[value] || { label: String(value || '未知'), color: 'default' };
}

export function documentStatusPresentation(value) {
  return status(DOCUMENT_STATUS, value);
}

export function modelStatusPresentation(value) {
  return status(MODEL_STATUS, value);
}

export function jobStatusPresentation(value) {
  return status(JOB_STATUS, value);
}

export function qualityPresentation(value) {
  return status(QUALITY_STATUS, value);
}

export function indexStatusPresentation(value) {
  return status(INDEX_STATUS, value);
}

export function candidateParticipationPresentation(value) {
  return status(CANDIDATE_PARTICIPATION, value);
}

export function normalizeDocument(raw = {}) {
  const original = raw.original_file && typeof raw.original_file === 'object'
    ? raw.original_file
    : { available: raw.original_available === true };
  const originalState = original.state || (original.available === true ? 'available' : 'unavailable');
  const originalMessages = {
    unavailable: '原文件当前不可用。',
    integrity_error: '原文件校验失败。',
    ambiguous: '原文件存在多个匹配项，暂时无法打开。',
  };
  return {
    documentId: raw.document_id ?? null,
    stagingId: raw.staging_id ?? null,
    title: raw.title || raw.filename || '未命名文档',
    filename: raw.filename || '',
    sourceType: raw.source_type || raw.extension || 'unknown',
    mimeType: raw.mime_type || '',
    pages: raw.pages ?? raw.preflight?.page_count ?? null,
    chunks: raw.chunks ?? raw.chunk_count ?? raw.preflight?.estimated_chunk_count ?? 0,
    status: raw.status || 'unknown',
    sha256: raw.sha256 || '',
    duplicate: raw.duplicate === true,
    duplicateOf: raw.duplicate_of ?? null,
    parser: raw.parser || raw.preflight?.parser || null,
    securityScan: raw.security_scan || raw.preflight?.security_scan || 'not_configured',
    originalAvailable: original.available === true,
    originalOpenSupported: original.open_supported === true || (raw.original_file == null && raw.original_available === true),
    originalDownloadSupported: original.download_supported === true || (raw.original_file == null && raw.original_available === true),
    originalFileState: originalState,
    originalFileMessage: originalMessages[originalState] || '',
    createdAt: raw.created_at || raw.uploaded_at || null,
    updatedAt: raw.updated_at || null,
    indexRelease: raw.commit_receipt?.index_release || null,
    quality: raw.content_quality || null,
    indexStatus: raw.index_status?.state || raw.index_status || 'synced',
    totalChunks: Number(raw.total_chunks ?? raw.preflight?.estimated_chunk_count ?? raw.chunks ?? raw.chunk_count ?? 0),
    includedChunks: Number(raw.included_chunks ?? raw.total_chunks ?? raw.preflight?.estimated_chunk_count ?? raw.chunks ?? raw.chunk_count ?? 0),
    excludedChunks: Number(raw.excluded_chunks ?? 0),
    reviewRecommendedChunks: Number(raw.review_recommended_chunks ?? 0),
    suspectedParseErrorChunks: Number(raw.suspected_parse_error_chunks ?? 0),
    reparse: raw.reparse || { available: false, strategies: [] },
    raw,
  };
}

export function normalizeChunk(raw = {}) {
  const effectiveText = raw.effective_text ?? raw.text ?? '';
  const rawText = raw.raw_text ?? effectiveText;
  const quality = raw.quality && typeof raw.quality === 'object' ? raw.quality : {};
  return {
    chunkId: raw.chunk_id ?? null,
    chunkIndex: raw.chunk_index ?? 0,
    pageStart: raw.page_start ?? null,
    pageEnd: raw.page_end ?? null,
    section: raw.section || raw.section_path || '',
    preview: raw.preview || String(effectiveText).replace(/\s+/g, ' ').slice(0, 320),
    length: raw.length ?? String(effectiveText).length,
    rawText: String(rawText),
    effectiveText: String(effectiveText),
    editState: raw.edit_state || (rawText === effectiveText ? 'clean' : 'edited'),
    version: Number(raw.version || 0),
    revisions: Array.isArray(raw.revisions) ? raw.revisions : [],
    qualityState: quality.state || 'normal',
    qualityIssues: Array.isArray(quality.issues) ? quality.issues : [],
    participationState: raw.participation_state === 'excluded' ? 'excluded' : 'included',
    included: raw.participation_state !== 'excluded' && raw.included !== false,
    indexStatus: raw.index_status || 'synced',
    active: raw.active !== false,
  };
}

export function normalizeModel(raw = {}) {
  const smokeValue = String(raw.smoke || raw.smoke_status || 'not_available');
  return {
    assetId: raw.asset_id || '',
    modelId: raw.model_id || '',
    version: raw.version || '',
    displayName: raw.display_name || raw.filename || raw.model_id || '未命名模型',
    backend: raw.backend || 'unknown',
    status: raw.status || 'unknown',
    sha256: raw.sha256 || '',
    allowlist: raw.allowlist === true,
    executionAllowed: raw.execution_allowed === true,
    allowlistLabel: raw.allowlist === true ? '已授权' : '未授权',
    executionLabel: raw.execution_allowed === true ? '可执行' : '不可执行',
    smoke: smokeValue,
    smokeLabel: ({ passed: '已通过', succeeded: '已通过', failed: '未通过', pending: '待测试', not_available: '尚未测试' })[smokeValue] || '尚未测试',
    updatedAt: raw.updated_at || raw.uploaded_at || null,
    raw,
  };
}

export function normalizeGeneratedModel(raw = {}) {
  const summary = raw.model_summary && typeof raw.model_summary === 'object' ? raw.model_summary : {};
  const origin = raw.origin || 'llm_generated';
  const retention = raw.retention || (origin === 'admin_uploaded' ? 'resident' : 'ephemeral');
  return {
    generationId: raw.generation_id || '',
    displayName: raw.display_name || summary.model_id || '未命名生成模型',
    description: raw.description || raw.model_description || '',
    modelDescription: raw.model_description || '',
    origin,
    originLabel: origin === 'admin_uploaded' ? '管理员上传' : 'LLM 生成',
    retention,
    retentionLabel: retention === 'resident' ? '常驻' : '临时',
    revision: Number(raw.revision || 0),
    metadataRevision: Number(raw.metadata_revision || 1),
    status: raw.status || 'draft',
    requirement: raw.requirement_summary || '',
    modelId: summary.model_id || '',
    domain: summary.domain || '',
    componentCount: Number(summary.component_count || 0),
    connectionCount: Number(summary.connection_count || 0),
    componentTypes: Array.isArray(summary.component_types) ? summary.component_types : [],
    components: Array.isArray(summary.components) ? summary.components : [],
    topology: Array.isArray(summary.topology) ? summary.topology : [],
    requestedOutputs: Array.isArray(summary.requested_outputs) ? summary.requested_outputs : [],
    missingParameters: Array.isArray(raw.missing_parameters) ? raw.missing_parameters : [],
    validationPassed: raw.validation_report?.valid === true,
    artifactId: raw.artifact_id || null,
    executionEligible: raw.execution_eligible === true,
    lastUsedAt: raw.last_used_at || null,
    lastExecutedAt: raw.last_execution_at || raw.last_executed_at || null,
    lastActivityAt: raw.last_activity_at || null,
    useCount: Number(raw.use_count || 0),
    expiresAt: raw.expires_at || null,
    updatedAt: raw.updated_at || null,
    raw,
  };
}

const JOB_TYPES = Object.freeze({
  document_preflight: '文档内容检查',
  document_dry_run: '文档切分预览',
  document_commit: '文档入库',
  document_ingestion: '文档入库',
  model_validation: '模型校验',
  model_smoke: '模型测试',
  generated_model_compile: '生成模型编译',
  generated_model_smoke: '生成模型测试',
  generated_model_instrumentation: '生成模型输出装配',
  generated_model_execution: '生成模型执行',
  generated_result_critique: '生成结果校验',
  page_reparse: '单页重新解析',
  index_candidate_build: '生成候选索引',
  index_validation: '候选索引验证',
  index_release: '候选索引发布',
});

const AUDIT_ACTIONS = Object.freeze({
  UPLOAD_DOCUMENT: '上传文档',
  COMMIT_DOCUMENT: '确认文档入库',
  CANCEL_INGESTION: '取消文档入库',
  UPLOAD_MODEL: '上传模型版本',
  APPROVE_MODEL: '批准模型',
  REJECT_MODEL: '拒绝模型',
  ENABLE_MODEL: '启用模型',
  DISABLE_MODEL: '禁用模型',
  ROLLBACK_MODEL: '切换模型版本',
  RUN_MODEL_SMOKE: '测试模型',
  COMPILE_GENERATED_MODEL: '编译生成模型',
  INSTRUMENT_GENERATED_MODEL: '装配生成模型输出',
  EXECUTE_GENERATED_MODEL: '执行生成模型',
  CRITIQUE_GENERATED_RESULT: '校验生成结果',
  APPROVE_GENERATED_MODEL: '批准生成模型',
  REJECT_GENERATED_MODEL: '拒绝生成模型',
  ENABLE_GENERATED_MODEL: '启用生成模型',
  DISABLE_GENERATED_MODEL: '禁用生成模型',
  EDIT_STAGED_CHUNK: '编辑待入库片段',
  RESTORE_STAGED_CHUNK: '恢复待入库解析文本',
  EXCLUDE_STAGED_CHUNK: '排除待入库片段',
  WITHDRAW_STAGED_DOCUMENT: '撤回待入库文件',
  EDIT_KNOWLEDGE_CHUNK: '修订已入库片段',
  RESTORE_KNOWLEDGE_CHUNK: '恢复历史修订',
  RESTORE_KNOWLEDGE_CHUNK_ORIGINAL: '恢复原始解析文本',
  REPARSE_PAGE_REQUEST: '生成单页重新解析预览',
  APPLY_REPARSE_RESULT: '应用单页重新解析结果',
  BUILD_INDEX_CANDIDATE: '生成候选索引',
  VALIDATE_INDEX_CANDIDATE: '验证候选索引',
  RELEASE_INDEX: '发布候选索引',
});

export function jobTypePresentation(value) {
  return JOB_TYPES[value] || '管理任务';
}

export function auditActionPresentation(value) {
  return AUDIT_ACTIONS[value] || '管理操作';
}

export function systemComponentSummary(item = {}) {
  const statusValue = String(item.status || '').toLowerCase();
  if (statusValue === 'healthy' || statusValue === 'ready') return '运行正常';
  if (statusValue === 'disabled') return '未启用';
  if (statusValue === 'degraded') return '部分功能暂不可用';
  if (statusValue === 'unhealthy' || statusValue === 'unavailable' || statusValue === 'not_ready') return '暂不可用';
  return '状态暂不可用';
}

const SYSTEM_COMPONENTS = Object.freeze({
  backend: '核心服务',
  mysql: '数据库',
  faiss: '向量检索',
  bm25: '关键词检索',
  retrieval: '知识检索',
  agent: '智能助手',
  tool_registry: '计算工具',
  simulation_service: '仿真服务',
  matlab: 'MATLAB',
  scenario_catalog: '仿真场景',
  model_registry: '仿真模型',
  executor_registry: '仿真执行',
  report_service: '报告服务',
  model_assets: '模型文件',
  evidence_storage: '仿真记录',
  runtime_storage: '运行存储',
});

export function systemComponentName(item = {}) {
  return SYSTEM_COMPONENTS[item.module_id] || '系统组件';
}

export function formatBytes(value) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 ** 2).toFixed(1)} MB`;
}

export function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}

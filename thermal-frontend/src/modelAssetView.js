export const DEFAULT_MAX_MODEL_FILE_SIZE_MB = 100;

export function normalizeModelAssetList(payload = {}) {
  const assets = Array.isArray(payload) ? payload : Array.isArray(payload.assets) ? payload.assets : [];
  return {
    assets,
    upload_enabled: payload?.upload_enabled === true,
    max_file_size_mb: Number.isFinite(Number(payload?.max_file_size_mb))
      ? Number(payload.max_file_size_mb)
      : DEFAULT_MAX_MODEL_FILE_SIZE_MB,
    allowed_extensions: Array.isArray(payload?.allowed_extensions)
      ? payload.allowed_extensions.map(value => String(value).toLowerCase())
      : [],
  };
}

export function validateModelAssetFile(file, limits) {
  if (!file) return '请先选择模型文件。';
  const maxMb = Number(limits?.max_file_size_mb) || DEFAULT_MAX_MODEL_FILE_SIZE_MB;
  if (Number(file.size) > maxMb * 1024 * 1024) return `文件不得超过 ${maxMb} MB。`;
  const allowed = Array.isArray(limits?.allowed_extensions) ? limits.allowed_extensions : [];
  if (allowed.length > 0) {
    const filename = String(file.name || '').toLowerCase();
    const normalized = allowed.map(value => String(value).toLowerCase().replace(/^\./, ''));
    if (!normalized.some(extension => filename.endsWith(`.${extension}`))) {
      return `仅允许上传：${allowed.join('、')}`;
    }
  }
  return '';
}

export function modelAssetId(asset) {
  return String(asset?.asset_id || asset?.model_asset_id || asset?.id || '');
}

export function modelAssetName(asset) {
  return String(asset?.original_filename || asset?.display_name || asset?.filename || modelAssetId(asset) || '未命名文件');
}

export function publicModelAssetView(asset = {}) {
  const executionAllowed = asset.execution_allowed === true;
  const status = String(asset.status || asset.review_status || '—');
  const operatorResult = ({
    approved: '已批准',
    registered: '已登记',
    rejected: '已驳回',
    blocked: '已阻断',
    pending_review: '待 operator 复核',
  })[status.toLowerCase()] || '—';
  return {
    asset_id: modelAssetId(asset),
    name: modelAssetName(asset),
    status,
    sha256: String(asset.sha256 || asset.hash || '—'),
    size_bytes: Number.isFinite(Number(asset.size_bytes ?? asset.file_size_bytes))
      ? Number(asset.size_bytes ?? asset.file_size_bytes)
      : null,
    mime_type: String(asset.mime_type || asset.content_type || '—'),
    asset_type: String(asset.asset_type || '—'),
    extension: String(asset.extension || '—'),
    uploaded_at: asset.uploaded_at || asset.created_at || null,
    scenario_id: String(asset.scenario_id || '—'),
    execution_allowed: executionAllowed,
    operator_result: String(asset.operator_result || asset.review_result || operatorResult),
    operator_notes: String(asset.operator_notes || '—'),
    rejection_reason: String(asset.rejection_reason || '—'),
    security_scan_status: String(asset.security_scan_status || '—'),
    human_validated: asset.human_validated === true,
    proposed_model_id: String(asset.proposed_model_id || '—'),
    registered_model_id: String(asset.registered_model_id || '—'),
  };
}

export function modelAssetCanSubmitReview(asset = {}) {
  const status = String(asset.status || asset.review_status || '').toLowerCase();
  return ['quarantined', 'uploaded', 'user_uploaded_unvalidated', 'unvalidated', 'draft'].includes(status);
}

export function formatFileSize(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return '—';
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${Number((value / 1024).toFixed(2))} KB`;
  return `${Number((value / 1024 ** 2).toFixed(2))} MB`;
}

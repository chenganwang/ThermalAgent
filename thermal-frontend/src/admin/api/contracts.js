export const HEALTH_META = Object.freeze({
  healthy: { label: '正常', color: 'success' },
  ready: { label: '正常', color: 'success' },
  degraded: { label: '部分功能受限', color: 'warning' },
  unhealthy: { label: '不可用', color: 'error' },
  not_ready: { label: '不可用', color: 'error' },
  disabled: { label: '未启用', color: 'default' },
  unavailable: { label: '暂不可用', color: 'error' },
  unknown: { label: '状态未知', color: 'warning' },
  checking: { label: '检查中', color: 'processing' },
});

export function healthMeta(status) {
  return HEALTH_META[status] || { label: String(status || '未知'), color: 'default' };
}

export function booleanState(value) {
  if (value === true) return '是';
  if (value === false) return '否';
  return '未检查';
}

export function formatObservedAt(value) {
  if (!value) return '未检查';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleString();
}

export function adminErrorMessage(error) {
  if (!error) return '';
  if (error.code === 'ADMIN_CONFIG_VERSION_CONFLICT') return '配置版本已变化，请刷新后重新 dry-run。';
  if (error.code === 'ADMIN_CONFIG_WRITE_AUTH_REQUIRED' || error.code === 'ADMIN_CONFIG_WRITE_AUTH_INVALID') {
    return '配置写凭据无效或未提供，请重新获取写权限。';
  }
  if (error.code === 'ADMIN_CONFIG_WRITE_DISABLED') return '配置修改当前不可用。';
  if (error.code === 'ADMIN_CONFIG_WRITE_TOKEN_CONFLICT') return '当前凭据不能执行此操作。';
  if (error.code === 'ADMIN_ACTION_PARAMETER_FORBIDDEN') return 'Action 参数包含禁止字段，未执行任何 handler。';
  if (error.code === 'ADMIN_ACTION_PARAMETER_INVALID') return 'Action 参数不符合受控 Schema。';
  if (error.code === 'ADMIN_ACTION_CONCURRENCY_LIMIT') return '该安全检查已达到并发上限，请稍后重试。';
  if (error.code === 'ADMIN_ACTION_TIMEOUT') return '安全检查超时，请稍后重试。';
  if (error.code === 'ADMIN_ACTION_PERMISSION_DENIED') return '当前身份没有执行该风险级别 Action 的权限。';
  if (error.code === 'ADMIN_ACTION_UNAVAILABLE' || error.code === 'ADMIN_ACTION_DISABLED') return '该 Action 当前不可用或未开放。';
  if (error.code === 'ADMIN_ACTION_EXECUTION_FAILED') return '安全检查执行失败，请稍后重试。';
  if (error.code === 'ADMIN_WORKFLOW_WRITE_AUTH_REQUIRED' || error.code === 'ADMIN_WORKFLOW_WRITE_AUTH_INVALID') return '你没有执行此操作的权限。';
  if (error.code === 'ADMIN_WORKFLOW_WRITE_DISABLED') return '管理操作当前不可用。';
  if (error.code === 'DOCUMENT_DUPLICATE') return '该文件内容已存在；重复判断基于 SHA-256。';
  if (error.code === 'DOCUMENT_NOT_READY') return '请先完成预检和 Dry-run。';
  if (error.code === 'DOCUMENT_QUALITY_GATE_FAILED') return '文档文本提取未通过现有 ingestion 质量门禁。';
  if (error.code === 'MODEL_MANIFEST_INVALID') return '模型 Manifest 不符合 canonical contract。';
  if (error.code === 'MODEL_VERSION_CONFLICT') return '该模型版本已存在；请上传新的版本号。';
  if (error.code === 'MODEL_SMOKE_REQUIRES_INFRASTRUCTURE') return '上传模型尚未获得执行认证，不能进入 MATLAB dispatcher。';
  if (error.code === 'DATABASE_UNAVAILABLE') return '知识库暂时不可用，其他管理功能仍可继续使用。';
  if (error.statusCode === 401) return '管理员凭据无效或已失效，请重新输入。';
  if (error.statusCode === 403) return '你没有执行此操作的权限。';
  if (error.statusCode === 404 && error.code === 'ADMIN_API_DISABLED') return '管理控制台当前不可用。请使用已启用管理功能的 ThermalAgent 实例。';
  if (error.statusCode === 429) return '请求过于频繁，请稍后重试。';
  if (error.statusCode === 503) return '相关功能暂不可用，请稍后重试。';
  if (error.statusCode >= 500) return '操作失败，请稍后重试。';
  return error.message || '操作失败，请稍后重试。';
}

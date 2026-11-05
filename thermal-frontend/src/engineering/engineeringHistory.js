export function runStatus(status) {
  return ({ completed: '已完成', blocked: '等待补充', failed: '失败', incomplete: '未完成', running: '运行中', pending: '待执行', planned: '已规划', skipped: '已跳过' })[status] || '状态未知';
}

export function canResumeRun(run) {
  return run?.recoverable === true && run?.active === false && !run?.resumed_by && run?.status !== 'completed' && Number.isInteger(run?.revision) && run.revision >= 1 && Boolean(run?.run_id);
}

export function historyError(error) {
  if (error?.name === 'AbortError') return '请求等待已结束。后台操作可能仍在完成，请刷新历史确认结果后再操作。';
  if (error?.statusCode === 404) return '记录或工程历史接口不可用，请刷新；旧版后端需要加载工程历史模块。';
  if (error?.statusCode === 409) return '记录已变化或不可恢复，请刷新后核对当前状态。';
  if (error?.statusCode === 401 || error?.statusCode === 403) return '当前请求没有访问工程记录的权限。';
  return error?.message || '工程历史请求失败，请检查后端服务。';
}

export function referenceInputs(values) {
  const fields = [['area', '面积'], ['thickness', '厚度'], ['conductivity', '导热系数'], ['left', '左边界绝对温度'], ['right', '右边界绝对温度']];
  const invalid = fields.filter(([key]) => typeof values[key] !== 'number' || !Number.isFinite(values[key]) || values[key] <= 0);
  if (invalid.length) return { errors: invalid.map(([, label]) => `${label}必须为有限正数。`), inputs: null };
  return { errors: [], inputs: { area_m2: values.area, left_temperature_k: values.left, right_temperature_k: values.right, layers: [{ thickness_m: values.thickness, conductivity_w_mk: values.conductivity }], cells_per_layer: 2 } };
}

export function downloadArtifact(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename.replace(/[^a-zA-Z0-9_.-]/g, '_');
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

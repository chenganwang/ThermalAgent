import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Descriptions, List, Space, Spin, Tag, Typography } from 'antd';

import {
  getSimulationModelAsset,
  getSimulationModelAssets,
  submitSimulationModelAssetReview,
  uploadSimulationModelAsset,
} from './api/client';
import {
  formatFileSize,
  modelAssetCanSubmitReview,
  modelAssetId,
  modelAssetName,
  normalizeModelAssetList,
  publicModelAssetView,
  validateModelAssetFile,
} from './modelAssetView';

const { Paragraph, Text } = Typography;

function statusColor(status) {
  const value = String(status || '').toLowerCase();
  if (['approved', 'registered'].includes(value)) return 'success';
  if (['rejected', 'blocked', 'failed'].includes(value)) return 'error';
  if (['pending_review', 'pending_operator_review', 'submitted_for_review'].includes(value)) return 'processing';
  return 'warning';
}

function errorMessage(error) {
  const detail = error?.detail ?? error?.payload?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    return detail.message || detail.error?.message || detail.code || detail.status || error.message;
  }
  return error?.message || '请求失败，请检查后端连接。';
}

export default function ModelAssetPanel({ useMockResponses = false }) {
  const [loading, setLoading] = useState(true);
  const [limits, setLimits] = useState(normalizeModelAssetList({}));
  const [assets, setAssets] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedAssetId, setSelectedAssetId] = useState('');
  const [assetDetail, setAssetDetail] = useState(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [uploading, setUploading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [inputKey, setInputKey] = useState(0);

  const loadAssets = useCallback(async () => {
    if (useMockResponses) {
      setLoading(false);
      setError('Mock 模式不伪造模型文件、hash 或 operator 复核结果。');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const payload = await getSimulationModelAssets();
      const normalized = normalizeModelAssetList(payload);
      setLimits(normalized);
      setAssets(normalized.assets);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, [useMockResponses]);

  useEffect(() => { loadAssets(); }, [loadAssets]);

  useEffect(() => {
    if (!selectedAssetId || useMockResponses) {
      setAssetDetail(null);
      return undefined;
    }
    let cancelled = false;
    setDetailLoading(true);
    setError('');
    getSimulationModelAsset(selectedAssetId)
      .then(payload => { if (!cancelled) setAssetDetail(payload); })
      .catch(requestError => { if (!cancelled) setError(errorMessage(requestError)); })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [selectedAssetId, useMockResponses]);

  const accept = useMemo(
    () => limits.allowed_extensions.map(value => `.${String(value).replace(/^\./, '')}`).join(','),
    [limits.allowed_extensions],
  );
  const detail = assetDetail || assets.find(asset => modelAssetId(asset) === selectedAssetId) || null;
  const view = detail ? publicModelAssetView(detail) : null;

  const upload = async () => {
    const validationError = validateModelAssetFile(selectedFile, limits);
    if (validationError) {
      setError(validationError);
      return;
    }
    setUploading(true);
    setError('');
    setMessage('');
    try {
      const uploaded = await uploadSimulationModelAsset(selectedFile);
      const id = modelAssetId(uploaded);
      setMessage('文件已上传，仍不可执行。如需进入 operator 复核，请点击“提交复核”。');
      setSelectedFile(null);
      setInputKey(previous => previous + 1);
      await loadAssets();
      if (id) setSelectedAssetId(id);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setUploading(false);
    }
  };

  const submitReview = async () => {
    if (!selectedAssetId || !modelAssetCanSubmitReview(detail)) return;
    setSubmitting(true);
    setError('');
    setMessage('');
    try {
      const updated = await submitSimulationModelAssetReview(selectedAssetId);
      setAssetDetail(updated);
      setMessage('已提交 operator 复核。在 operator 完成审核和登记前，execution_allowed 始终为 false。');
      await loadAssets();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ padding: '20px 24px', textAlign: 'left' }}>
      <Space orientation="vertical" size={16} style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          title="上传不等于登记或可执行"
          description="普通用户只能上传文件并提交复核。本页不提供 admin 注册、本机路径或直接执行能力。"
        />
        {error && <Alert type="error" showIcon title={error} />}
        {message && <Alert type="success" showIcon title={message} />}

        <Card title="上传模型文件" size="small">
          <Descriptions
            size="small"
            column={{ xs: 1, sm: 2 }}
            items={[
              { key: 'formats', label: '允许格式', children: limits.allowed_extensions.join('、') || '以后端返回为准', span: 2 },
              { key: 'size', label: '大小上限', children: `${limits.max_file_size_mb} MB（以后端返回为准）` },
              { key: 'enabled', label: '上传状态', children: limits.upload_enabled ? '可上传' : '已禁用' },
            ]}
          />
          <div style={{ marginTop: 16 }}>
            <input
              key={inputKey}
              type="file"
              accept={accept || undefined}
              disabled={!limits.upload_enabled || uploading || useMockResponses}
              onChange={event => {
                const file = event.target.files?.[0] || null;
                setSelectedFile(file);
                setError(file ? validateModelAssetFile(file, limits) : '');
              }}
              aria-label="选择模型文件"
            />
            {selectedFile && (
              <Paragraph type="secondary" style={{ margin: '8px 0 0' }}>
                {selectedFile.name} · {formatFileSize(selectedFile.size)}
              </Paragraph>
            )}
            <Button
              type="primary"
              onClick={upload}
              loading={uploading}
              disabled={!selectedFile || !limits.upload_enabled || uploading || useMockResponses}
              style={{ marginTop: 12 }}
            >
              上传文件
            </Button>
          </div>
        </Card>

        <Card title="模型文件" size="small" extra={<Button onClick={loadAssets} disabled={loading}>刷新</Button>}>
          {loading ? <Spin tip="加载模型文件…" /> : (
            <List
              dataSource={assets}
              locale={{ emptyText: '暂无模型文件' }}
              renderItem={asset => (
                <List.Item
                  onClick={() => setSelectedAssetId(modelAssetId(asset))}
                  style={{ cursor: 'pointer', background: modelAssetId(asset) === selectedAssetId ? 'rgba(79,195,247,.08)' : undefined, paddingInline: 10 }}
                  extra={<Tag color={statusColor(asset.status)}>{asset.status || '—'}</Tag>}
                >
                  <List.Item.Meta
                    title={modelAssetName(asset)}
                    description={`ID: ${modelAssetId(asset)} · ${formatFileSize(asset.size_bytes)}`}
                  />
                </List.Item>
              )}
            />
          )}
        </Card>

        {selectedAssetId && (
          <Card title="模型文件详情" size="small">
            {detailLoading || !view ? <Spin /> : (
              <>
                {view.execution_allowed && (
                  <Alert
                    type="error"
                    showIcon
                    title="后端返回了异常的 execution_allowed=true，本页仍不提供执行入口。"
                    style={{ marginBottom: 14 }}
                  />
                )}
                <Descriptions
                  bordered
                  size="small"
                  column={{ xs: 1, sm: 2 }}
                  items={[
                    { key: 'name', label: '原始文件名', children: view.name, span: 2 },
                    { key: 'id', label: '文件 ID', children: view.asset_id, span: 2 },
                    { key: 'status', label: '状态', children: <Tag color={statusColor(view.status)}>{view.status}</Tag> },
                    { key: 'execution', label: '允许执行', children: view.execution_allowed ? '后端异常：是（前端已阻断）' : '否' },
                    { key: 'sha', label: 'SHA-256', children: view.sha256, span: 2 },
                    { key: 'size', label: '文件大小', children: formatFileSize(view.size_bytes) },
                    { key: 'type', label: '资产类型', children: view.asset_type },
                    { key: 'format', label: '文件格式', children: view.extension },
                    { key: 'mime', label: 'MIME 类型', children: view.mime_type },
                    { key: 'scan', label: '安全扫描', children: view.security_scan_status },
                    { key: 'reviewed', label: '人工复核', children: view.human_validated ? '已复核' : '尚未复核' },
                    { key: 'scenario', label: '关联场景', children: view.scenario_id, span: 2 },
                    { key: 'proposed-model', label: '拟登记模型 ID', children: view.proposed_model_id, span: 2 },
                    { key: 'registered-model', label: '已登记模型 ID', children: view.registered_model_id, span: 2 },
                    { key: 'operator', label: 'Operator 复核结果', children: view.operator_result, span: 2 },
                    { key: 'notes', label: 'Operator 备注', children: view.operator_notes, span: 2 },
                    { key: 'rejection', label: '驳回原因', children: view.rejection_reason, span: 2 },
                  ]}
                />
                <Button
                  type="primary"
                  onClick={submitReview}
                  loading={submitting}
                  disabled={!modelAssetCanSubmitReview(detail) || submitting}
                  style={{ marginTop: 14 }}
                >
                  提交复核
                </Button>
                {!modelAssetCanSubmitReview(detail) && (
                  <Text type="secondary" style={{ marginLeft: 10 }}>当前状态不能重复提交复核。</Text>
                )}
              </>
            )}
          </Card>
        )}
      </Space>
    </div>
  );
}

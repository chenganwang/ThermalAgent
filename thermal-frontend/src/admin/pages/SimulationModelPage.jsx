import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, Input, Modal, Popconfirm, Space, Table, Tabs, Typography } from 'antd';
import { LeftOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import {
  approveSimulationModel,
  disableSimulationModel,
  enableSimulationModel,
  getSimulationModel,
  rejectSimulationModel,
  smokeSimulationModel,
} from '../api/adminClient.js';
import { adminErrorMessage } from '../api/contracts.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import AdminStatusBadge from '../components/AdminStatusBadge.jsx';
import JsonPreview from '../components/JsonPreview.jsx';
import PageState from '../components/PageState.jsx';
import WorkflowCredential from '../components/WorkflowCredential.jsx';
import { formatDate, modelStatusPresentation, normalizeModel } from '../presentation/adminPresentation.js';

export default function SimulationModelPage() {
  const { assetId } = useParams();
  const navigate = useNavigate();
  const { token, workflowWriteToken } = useAdminAuth();
  const [model, setModel] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState(null);
  const [scenarioId] = useState('');
  const [rejectReason, setRejectReason] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const value = await getSimulationModel(token, assetId, { includeCode: true });
      setModel({ ...normalizeModel(value), raw: value });
    } catch (requestError) {
      setError(requestError);
    } finally {
      setLoading(false);
    }
  }, [token, assetId]);

  useEffect(() => { refresh(); }, [refresh]);

  const run = async (key, operation) => {
    setBusy(key);
    setError(null);
    try { await operation(); await refresh(); } catch (requestError) { setError(requestError); } finally { setBusy(''); }
  };

  const approve = () => {
    let nextScenario = scenarioId;
    Modal.confirm({
      title: '批准模型版本',
      content: <Input aria-label="执行场景标识" placeholder="请输入已登记的执行场景标识" defaultValue={scenarioId} onChange={event => { nextScenario = event.target.value; }} />,
      okText: '确认批准',
      okButtonProps: { disabled: !workflowWriteToken },
      onOk: () => run('approve', () => approveSimulationModel(token, workflowWriteToken, assetId, { scenario_id: nextScenario.trim(), operator_notes: 'Admin Console V1 approval' })),
    });
  };

  const reject = () => {
    let reason = rejectReason;
    Modal.confirm({
      title: '拒绝模型版本',
      content: <Input.TextArea aria-label="拒绝原因" rows={3} defaultValue={rejectReason} onChange={event => { reason = event.target.value; setRejectReason(reason); }} />,
      okText: '拒绝', okButtonProps: { danger: true, disabled: !workflowWriteToken },
      onOk: () => run('reject', () => rejectSimulationModel(token, workflowWriteToken, assetId, reason.trim())),
    });
  };

  return (
    <section>
      <div className="admin-page-heading">
        <div>
          <Button type="link" icon={<LeftOutlined />} onClick={() => navigate('/admin/simulation-models')}>返回模型库</Button>
          <Typography.Title level={2}>{model?.displayName || '模型详情'}</Typography.Title>
          <Typography.Text type="secondary">查看模型定义、安全检查、审核状态与版本记录。</Typography.Text>
        </div>
        <Space wrap><WorkflowCredential /><Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button></Space>
      </div>
      {error && <Alert className="admin-section-alert" type="error" showIcon title={adminErrorMessage(error)} />}
      <PageState loading={loading} error={error} onRetry={refresh}>
        {model && <>
          <Card className="admin-section-card">
            <Descriptions bordered column={{ xs: 1, lg: 2 }}>
              <Descriptions.Item label="模型标识">{model.modelId}</Descriptions.Item>
              <Descriptions.Item label="版本">{model.version}</Descriptions.Item>
              <Descriptions.Item label="状态"><AdminStatusBadge value={model.status} presentation={modelStatusPresentation} /></Descriptions.Item>
              <Descriptions.Item label="运行环境">{String(model.backend).toLowerCase() === 'matlab' ? 'MATLAB' : model.backend}</Descriptions.Item>
              <Descriptions.Item label="执行权限">{model.allowlistLabel}</Descriptions.Item>
              <Descriptions.Item label="执行能力">{model.executionLabel}</Descriptions.Item>
              <Descriptions.Item label="更新时间">{formatDate(model.updatedAt)}</Descriptions.Item>
              <Descriptions.Item label="测试状态">{model.smokeLabel}</Descriptions.Item>
            </Descriptions>
            <Space className="admin-detail-actions" wrap>
              <Button type="primary" disabled={!workflowWriteToken || model.status !== 'pending_approval'} loading={busy === 'approve'} onClick={approve}>批准</Button>
              <Button danger disabled={!workflowWriteToken || model.status !== 'pending_approval'} loading={busy === 'reject'} onClick={reject}>拒绝</Button>
              <Popconfirm title="确认禁用该模型版本？" description="历史记录会保留，禁用后不能用于新的仿真任务。" onConfirm={() => run('disable', () => disableSimulationModel(token, workflowWriteToken, assetId))}>
                <Button disabled={!workflowWriteToken || !['approved_file_only', 'preparation_only'].includes(model.status)} loading={busy === 'disable'}>禁用</Button>
              </Popconfirm>
              <Popconfirm title="确认启用该模型版本？" description="启用仍受当前执行权限限制。" onConfirm={() => run('enable', () => enableSimulationModel(token, workflowWriteToken, assetId))}>
                <Button disabled={!workflowWriteToken || model.status !== 'disabled'} loading={busy === 'enable'}>启用</Button>
              </Popconfirm>
              <Popconfirm title="运行模型测试？" description="本次只执行安全资格检查，不会启动真实 MATLAB。" onConfirm={() => run('smoke', () => smokeSimulationModel(token, workflowWriteToken, assetId, false))}>
                <Button disabled={!workflowWriteToken} loading={busy === 'smoke'}>测试模型</Button>
              </Popconfirm>
            </Space>
          </Card>
          <Tabs items={[
            { key: 'manifest', label: '模型定义', children: <JsonPreview label="查看高级模型定义" value={model.raw.manifest} /> },
            { key: 'validation', label: '校验结果', children: <JsonPreview label="查看高级校验信息" value={model.raw.validation} /> },
            { key: 'code', label: '代码预览', children: <Card><pre className="admin-code-preview">{model.raw.code_preview || '代码预览不可用'}</pre></Card> },
            { key: 'versions', label: '版本历史', children: <Table rowKey="asset_id" dataSource={model.raw.version_history || []} pagination={false} columns={[
              { title: '版本', dataIndex: 'version' }, { title: '状态', dataIndex: 'status', render: value => <AdminStatusBadge value={value} presentation={modelStatusPresentation} /> }, { title: '更新时间', dataIndex: 'updated_at', render: formatDate },
            ]} /> },
          ]} />
          <JsonPreview label="高级信息" value={{ asset_id: model.assetId, sha256: model.sha256, execution_allowed: model.executionAllowed }} />
        </>}
      </PageState>
    </section>
  );
}

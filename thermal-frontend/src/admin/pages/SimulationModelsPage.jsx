import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Collapse, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography, Upload } from 'antd';
import { InboxOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import {
  approveGeneratedModel,
  compileGeneratedModel,
  createGeneratedModelRevision,
  deleteGeneratedModel,
  disableGeneratedModel,
  enableGeneratedModel,
  getGeneratedModels,
  getSimulationModels,
  promoteGeneratedModel,
  rejectGeneratedModel,
  updateGeneratedModelMetadata,
  uploadSimulationModel,
} from '../api/adminClient.js';
import { adminErrorMessage } from '../api/contracts.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import AdminStatusBadge from '../components/AdminStatusBadge.jsx';
import PageState from '../components/PageState.jsx';
import WorkflowCredential from '../components/WorkflowCredential.jsx';
import { formatDate, modelStatusPresentation, normalizeGeneratedModel, normalizeModel } from '../presentation/adminPresentation.js';

const { Dragger } = Upload;
const MANIFEST_EXAMPLE = JSON.stringify({
  model_id: 'custom_thermal_model',
  version: '1.0.0',
  display_name: '自定义热模型',
  description: '受控上传的 MATLAB 模型文件。',
  backend: 'matlab',
  entry_point: 'custom_thermal_model',
  inputs: { input_value: { type: 'number', unit: '1', minimum: 0 } },
  outputs: { output_value: { type: 'number', unit: '1' } },
  units: { input_value: '1', output_value: '1' },
  constraints: ['input_value >= 0'],
  execution_type: 'preparation_only',
}, null, 2);

export default function SimulationModelsPage() {
  const navigate = useNavigate();
  const { token, workflowWriteToken } = useAdminAuth();
  const [models, setModels] = useState([]);
  const [generatedModels, setGeneratedModels] = useState([]);
  const [file, setFile] = useState(null);
  const [manifest, setManifest] = useState(MANIFEST_EXAMPLE);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [generatedBusy, setGeneratedBusy] = useState(null);
  const [generatedQuery, setGeneratedQuery] = useState('');
  const [originFilter, setOriginFilter] = useState('all');
  const [retentionFilter, setRetentionFilter] = useState('all');
  const [metadataEditor, setMetadataEditor] = useState(null);
  const [engineeringEditor, setEngineeringEditor] = useState(null);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editModelIr, setEditModelIr] = useState('');
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [value, generated] = await Promise.all([getSimulationModels(token), getGeneratedModels(token)]);
      setModels((value.items || []).map(normalizeModel));
      setGeneratedModels((generated.items || []).map(normalizeGeneratedModel));
    } catch (requestError) {
      setError(requestError);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { refresh(); }, [refresh]);

  const upload = async () => {
    setBusy(true);
    setError(null);
    try {
      JSON.parse(manifest);
      const form = new FormData();
      form.append('file', file, file.name);
      form.append('manifest', manifest);
      await uploadSimulationModel(token, workflowWriteToken, form);
      setFile(null);
      await refresh();
    } catch (requestError) {
      setError(requestError);
    } finally {
      setBusy(false);
    }
  };

  const runGeneratedAction = async (generationId, action) => {
    setGeneratedBusy(generationId);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (requestError) {
      setError(requestError);
    } finally {
      setGeneratedBusy(null);
    }
  };

  const filteredGeneratedModels = useMemo(() => {
    const keyword = generatedQuery.trim().toLocaleLowerCase();
    return generatedModels.filter(item => {
      if (originFilter !== 'all' && item.origin !== originFilter) return false;
      if (retentionFilter !== 'all' && item.retention !== retentionFilter) return false;
      if (!keyword) return true;
      return `${item.displayName} ${item.generationId} ${item.description} ${item.requirement}`.toLocaleLowerCase().includes(keyword);
    });
  }, [generatedModels, generatedQuery, originFilter, retentionFilter]);

  const openMetadataEditor = item => {
    setMetadataEditor(item);
    setEditName(item.displayName);
    setEditDescription(item.description);
  };

  const openEngineeringEditor = item => {
    setEngineeringEditor(item);
    setEditModelIr(JSON.stringify(item.raw?.model_ir || {}, null, 2));
  };

  const saveMetadata = async () => {
    const item = metadataEditor;
    if (!item) return;
    await runGeneratedAction(item.generationId, () => updateGeneratedModelMetadata(
      token, workflowWriteToken, item.generationId,
      { display_name: editName, description: editDescription },
    ));
    setMetadataEditor(null);
  };

  const saveEngineeringRevision = async () => {
    const item = engineeringEditor;
    if (!item) return;
    try {
      const modelIr = JSON.parse(editModelIr);
      await runGeneratedAction(item.generationId, () => createGeneratedModelRevision(
        token, workflowWriteToken, item.generationId,
        { model_ir: modelIr, reason: '管理员通过结构化 Model IR 编辑创建工程修订' },
      ));
      setEngineeringEditor(null);
    } catch (requestError) {
      setError(requestError);
    }
  };

  return (
    <section>
      <div className="admin-page-heading">
        <div>
          <Typography.Title level={2}>仿真模型</Typography.Title>
          <Typography.Text type="secondary">上传新版本，完成安全检查与审核后授予执行权限。</Typography.Text>
        </div>
        <Space wrap><WorkflowCredential /><Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button></Space>
      </div>
      <Alert className="admin-section-alert" type="warning" showIcon title="上传后需审核" description="新模型版本需通过安全检查和管理员审核，上传本身不会授予执行权限。" />
      {error && <Alert className="admin-section-alert" type="error" showIcon title={adminErrorMessage(error)} />}
      <Card title="上传模型" extra={<Typography.Text type="secondary">新版本不会覆盖历史文件</Typography.Text>} className="admin-section-card">
        <Form layout="vertical">
          <Form.Item label="MATLAB 模型文件 (.m)" required>
            <Dragger accept=".m" maxCount={1} beforeUpload={candidate => { setFile(candidate); return false; }} onRemove={() => setFile(null)} fileList={file ? [{ uid: 'model', name: file.name, status: 'done' }] : []} disabled={!workflowWriteToken}>
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p>选择新模型版本；不会覆盖已存在版本</p>
            </Dragger>
          </Form.Item>
          <Collapse size="small" items={[{
            key: 'model-definition',
            label: '模型定义（高级）',
            children: <Form.Item label="模型输入、输出与约束" required><Input.TextArea aria-label="模型定义" rows={13} value={manifest} onChange={event => setManifest(event.target.value)} spellCheck={false} /></Form.Item>,
          }]} />
          <Button type="primary" disabled={!file || !workflowWriteToken || !manifest.trim()} loading={busy} onClick={upload}>上传并校验</Button>
        </Form>
      </Card>
      <Card title={`模型版本 (${models.length})`}>
        <PageState loading={loading} error={error} empty={!loading && !models.length} onRetry={refresh}>
          <Table
            rowKey="assetId"
            dataSource={models}
            pagination={{ pageSize: 20 }}
            onRow={item => ({ onClick: () => navigate(`/admin/simulation-models/${item.assetId}`) })}
            rowClassName="admin-clickable-row"
            scroll={{ x: 1000 }}
            columns={[
              { title: '模型', dataIndex: 'displayName', ellipsis: true },
              { title: '模型标识', dataIndex: 'modelId', width: 180, ellipsis: true },
              { title: '版本', dataIndex: 'version', width: 100 },
              { title: '运行环境', dataIndex: 'backend', width: 100, render: value => String(value).toLowerCase() === 'matlab' ? 'MATLAB' : value },
              { title: '审核状态', dataIndex: 'status', width: 150, render: value => <AdminStatusBadge value={value} presentation={modelStatusPresentation} /> },
              { title: '执行权限', dataIndex: 'allowlistLabel', width: 110 },
              { title: '测试状态', dataIndex: 'smokeLabel', width: 130 },
              { title: '更新时间', dataIndex: 'updatedAt', width: 190, render: formatDate },
            ]}
          />
        </PageState>
      </Card>
      <Card title={`自主生成模型 (${filteredGeneratedModels.length})`} className="admin-section-card" extra={<Typography.Text type="secondary">工程状态与保留策略相互独立</Typography.Text>}>
        <Space wrap className="admin-section-toolbar">
          <Input.Search aria-label="搜索生成模型" allowClear placeholder="按名称、ID 或摘要搜索" value={generatedQuery} onChange={event => setGeneratedQuery(event.target.value)} style={{ width: 300 }} />
          <Select aria-label="来源筛选" value={originFilter} onChange={setOriginFilter} style={{ width: 150 }} options={[
            { value: 'all', label: '全部来源' }, { value: 'llm_generated', label: 'LLM 生成' }, { value: 'admin_uploaded', label: '管理员上传' },
          ]} />
          <Select aria-label="保留策略筛选" value={retentionFilter} onChange={setRetentionFilter} style={{ width: 150 }} options={[
            { value: 'all', label: '全部保留策略' }, { value: 'ephemeral', label: '临时' }, { value: 'resident', label: '常驻' },
          ]} />
        </Space>
        <PageState loading={loading} error={error} empty={!loading && !filteredGeneratedModels.length} onRetry={refresh}>
          <Table
            rowKey="generationId"
            dataSource={filteredGeneratedModels}
            pagination={{ pageSize: 20 }}
            scroll={{ x: 1100 }}
            expandable={{
              expandedRowRender: item => (
                <Space orientation="vertical" size="small">
                  <Typography.Text>{item.requirement || '未提供需求摘要'}</Typography.Text>
                  <Typography.Text>{item.description || item.modelDescription}</Typography.Text>
                  <Typography.Text type="secondary">内部标识：<Typography.Text code copyable>{item.generationId}</Typography.Text></Typography.Text>
                  <Typography.Text type="secondary">组件：{item.componentTypes.join('、') || '—'}；连接：{item.connectionCount}</Typography.Text>
                  <Typography.Text type={item.validationPassed ? 'success' : 'danger'}>Validator：{item.validationPassed ? '通过' : '未通过'}</Typography.Text>
                  {item.components.map(component => {
                    const parameters = Object.entries(component.parameters || {}).map(([name, value]) => `${name}=${value?.value ?? '—'} ${value?.unit || ''}`.trim()).join('；');
                    return <Typography.Text code key={`${item.generationId}-component-${component.id}`}>{component.id} · {component.type}{parameters ? ` · ${parameters}` : ''}</Typography.Text>;
                  })}
                  {item.topology.map((edge, index) => <Typography.Text code key={`${item.generationId}-${index}`}>{edge.from_component}.{edge.from_port} → {edge.to_component}.{edge.to_port}</Typography.Text>)}
                  {item.requestedOutputs.map(output => <Typography.Text code key={`${item.generationId}-output-${output.id}`}>输出 {output.id} · {output.type} · {output.source_component_id}{output.source_port ? `.${output.source_port}` : ''}</Typography.Text>)}
                  {!!item.missingParameters.length && <Alert type="warning" showIcon title={`待补参数：${item.missingParameters.join('、')}`} />}
                </Space>
              ),
            }}
            columns={[
              { title: '模型名称', dataIndex: 'displayName', width: 230, render: (value, item) => <Space orientation="vertical" size={0}><Typography.Text strong>{value}</Typography.Text><Typography.Text type="secondary" copyable={{ text: item.generationId }}>{item.generationId}</Typography.Text></Space> },
              { title: '来源 / 保留', width: 150, render: (_, item) => <Space wrap size={4}><Tag>{item.originLabel}</Tag><Tag color={item.retention === 'resident' ? 'green' : 'gold'}>{item.retentionLabel}</Tag></Space> },
              { title: '修订', dataIndex: 'revision', width: 75 },
              { title: '组件 / 连接', width: 110, render: (_, item) => `${item.componentCount} / ${item.connectionCount}` },
              { title: '状态', dataIndex: 'status', width: 145, render: value => <AdminStatusBadge value={value} presentation={modelStatusPresentation} /> },
              { title: '执行资格', dataIndex: 'executionEligible', width: 100, render: value => value ? '可确认执行' : '不可执行' },
              { title: '最近使用', width: 180, render: (_, item) => <Space orientation="vertical" size={0}><span>{formatDate(item.lastExecutedAt || item.lastUsedAt || item.lastActivityAt || item.updatedAt)}</span><Typography.Text type="secondary">累计 {item.useCount} 次{item.retention === 'ephemeral' && item.expiresAt ? ` · 预计清理 ${formatDate(item.expiresAt)}` : ''}</Typography.Text></Space> },
              {
                title: '操作', fixed: 'right', width: 430,
                render: (_, item) => <Space wrap>
                  <Button size="small" disabled={!workflowWriteToken} onClick={() => openMetadataEditor(item)}>编辑信息</Button>
                  <Button size="small" disabled={!workflowWriteToken || item.status === 'enabled'} onClick={() => openEngineeringEditor(item)}>工程修订</Button>
                  <Popconfirm title="将此模型转为常驻？" description="该操作不批准、不启用模型。" onConfirm={() => runGeneratedAction(item.generationId, () => promoteGeneratedModel(token, workflowWriteToken, item.generationId))}>
                    <Button size="small" disabled={!workflowWriteToken || item.retention === 'resident'}>转为常驻</Button>
                  </Popconfirm>
                  <Popconfirm title="确认编译该已验证模型？" description="编译只写入受控生成模型目录，不会运行仿真。" onConfirm={() => runGeneratedAction(item.generationId, () => compileGeneratedModel(token, workflowWriteToken, item.generationId))}>
                    <Button size="small" disabled={!workflowWriteToken || item.status !== 'draft' || !item.validationPassed || item.missingParameters.length > 0} loading={generatedBusy === item.generationId}>编译</Button>
                  </Popconfirm>
                  <Popconfirm title="确认批准该生成模型？" onConfirm={() => runGeneratedAction(item.generationId, () => approveGeneratedModel(token, workflowWriteToken, item.generationId, '管理员已复核拓扑、参数和编译证据'))}>
                    <Button size="small" type="primary" disabled={!workflowWriteToken || item.status !== 'pending_approval'}>批准</Button>
                  </Popconfirm>
                  <Popconfirm title="确认拒绝该生成模型？" onConfirm={() => runGeneratedAction(item.generationId, () => rejectGeneratedModel(token, workflowWriteToken, item.generationId, '管理员拒绝该生成模型'))}>
                    <Button size="small" danger disabled={!workflowWriteToken || !['pending_approval', 'approved', 'disabled'].includes(item.status)}>拒绝</Button>
                  </Popconfirm>
                  <Popconfirm title="确认启用该生成模型？" description="启用后仍必须由用户确认具体计划才会执行。" onConfirm={() => runGeneratedAction(item.generationId, () => enableGeneratedModel(token, workflowWriteToken, item.generationId))}>
                    <Button size="small" disabled={!workflowWriteToken || item.retention !== 'resident' || !['approved', 'disabled', 'execution_failed'].includes(item.status)}>启用</Button>
                  </Popconfirm>
                  <Popconfirm title="确认禁用该生成模型？" onConfirm={() => runGeneratedAction(item.generationId, () => disableGeneratedModel(token, workflowWriteToken, item.generationId))}>
                    <Button size="small" disabled={!workflowWriteToken || item.status !== 'enabled'}>禁用</Button>
                  </Popconfirm>
                  <Popconfirm title="确认删除该生成模型？" description="操作会写入墓碑并通过 artifact ID 清理工件；已启用或正在使用的模型会被拒绝。" onConfirm={() => runGeneratedAction(item.generationId, () => deleteGeneratedModel(token, workflowWriteToken, item.generationId, '管理员从生成模型目录中删除'))}>
                    <Button size="small" danger disabled={!workflowWriteToken || item.status === 'enabled'}>删除</Button>
                  </Popconfirm>
                </Space>,
              },
            ]}
          />
        </PageState>
      </Card>
      <Modal
        title="编辑生成模型信息"
        open={Boolean(metadataEditor)}
        onCancel={() => setMetadataEditor(null)}
        onOk={saveMetadata}
        confirmLoading={Boolean(metadataEditor && generatedBusy === metadataEditor.generationId)}
        okButtonProps={{ disabled: !workflowWriteToken || editName.trim().length < 2 }}
      >
        <Alert className="admin-section-alert" type="info" showIcon title="仅修改展示元数据" description="不会创建工程修订，也不会改变审核、启用或 Validator 状态。" />
        <Form layout="vertical">
          <Form.Item label="模型名称" required><Input value={editName} maxLength={40} showCount onChange={event => setEditName(event.target.value)} /></Form.Item>
          <Form.Item label="说明"><Input.TextArea value={editDescription} maxLength={1000} showCount rows={4} onChange={event => setEditDescription(event.target.value)} /></Form.Item>
        </Form>
      </Modal>
      <Modal
        title="创建工程修订"
        open={Boolean(engineeringEditor)}
        onCancel={() => setEngineeringEditor(null)}
        onOk={saveEngineeringRevision}
        width={860}
        confirmLoading={Boolean(engineeringEditor && generatedBusy === engineeringEditor.generationId)}
        okText="校验并创建草稿修订"
        okButtonProps={{ disabled: !workflowWriteToken || !editModelIr.trim() }}
      >
        <Alert className="admin-section-alert" type="warning" showIcon title="新修订不会继承批准" description="这里只接受结构化 Model IR；不能提交 MATLAB 入口、脚本、block path 或 artifact。Validator 通过后创建新的 draft，旧修订保持不变。" />
        <Form layout="vertical"><Form.Item label="Model IR"><Input.TextArea aria-label="Model IR" value={editModelIr} rows={20} spellCheck={false} onChange={event => setEditModelIr(event.target.value)} /></Form.Item></Form>
      </Modal>
    </section>
  );
}

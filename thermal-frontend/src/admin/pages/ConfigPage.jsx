import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Radio,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  getAdminConfig,
  getAdminConfigHistory,
  rollbackAdminConfig,
  updateAdminConfig,
} from '../api/adminClient.js';
import { adminErrorMessage, formatObservedAt } from '../api/contracts.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import {
  buildConfigPatchPayload,
  buildConfigRollbackPayload,
  canApplyPreview,
  mutationFingerprint,
} from '../configFlow.js';

function DiffList({ preview }) {
  if (!preview) return null;
  return (
    <Card size="small" title={preview.no_change ? 'Dry-run：无实际变化' : 'Dry-run 结构化 Diff'}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label="版本">{preview.previous_version} → {preview.new_version}</Descriptions.Item>
        <Descriptions.Item label="影响模块">{preview.affected_modules?.join('、') || '无'}</Descriptions.Item>
        <Descriptions.Item label="副作用">{preview.side_effects?.length ? preview.side_effects.join('、') : '无（side_effects=[]）'}</Descriptions.Item>
      </Descriptions>
      {(preview.diff || []).map(item => (
        <Alert
          key={item.key}
          className="admin-config-diff"
          type="info"
          showIcon
          title={`${item.key}: ${String(item.previous_value)} → ${String(item.new_value)}`}
        />
      ))}
    </Card>
  );
}

export default function ConfigPage() {
  const { token, configWriteToken, elevateConfigWrite, clearConfigWrite } = useAdminAuth();
  const [config, setConfig] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [credentialOpen, setCredentialOpen] = useState(false);
  const [credential, setCredential] = useState('');
  const [editItem, setEditItem] = useState(null);
  const [editValue, setEditValue] = useState(false);
  const [reason, setReason] = useState('');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState(null);
  const [rollbackReason, setRollbackReason] = useState('');
  const [rollbackPreview, setRollbackPreview] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [nextConfig, nextHistory] = await Promise.all([
        getAdminConfig(token),
        getAdminConfigHistory(token, { limit: 50 }),
      ]);
      setConfig(nextConfig);
      setHistory(nextHistory.items || []);
    } catch (requestError) {
      setError(adminErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { refresh(); }, [refresh]);

  const editPayload = useMemo(() => {
    if (!editItem || !config || !reason.trim()) return null;
    return buildConfigPatchPayload({
      key: editItem.key,
      value: editValue,
      expectedVersion: config.version,
      reason,
      dryRun: true,
    });
  }, [editItem, editValue, config, reason]);
  const editFingerprint = editPayload ? mutationFingerprint(editPayload) : '';

  const rollbackPayload = useMemo(() => {
    if (!rollbackTarget || !config || !rollbackReason.trim()) return null;
    return buildConfigRollbackPayload({
      targetVersion: rollbackTarget.version,
      expectedVersion: config.version,
      reason: rollbackReason,
      dryRun: true,
    });
  }, [rollbackTarget, config, rollbackReason]);
  const rollbackFingerprint = rollbackPayload ? mutationFingerprint(rollbackPayload) : '';

  const handleMutationError = (requestError) => {
    if (requestError?.code === 'ADMIN_CONFIG_WRITE_AUTH_INVALID' || requestError?.code === 'ADMIN_CONFIG_WRITE_AUTH_REQUIRED') {
      clearConfigWrite();
    }
    if (requestError?.statusCode === 412) refresh();
    setError(adminErrorMessage(requestError));
  };

  const openEdit = (item) => {
    setEditItem(item);
    setEditValue(item.value);
    setReason('');
    setPreview(null);
    setError('');
    setNotice('');
  };

  const runDryRun = async () => {
    if (!editPayload) return;
    setBusy(true);
    setError('');
    try {
      const result = await updateAdminConfig(token, configWriteToken, editPayload);
      setPreview({ ...result, fingerprint: editFingerprint });
    } catch (requestError) {
      handleMutationError(requestError);
    } finally {
      setBusy(false);
    }
  };

  const applyEdit = async () => {
    if (!canApplyPreview(preview, editFingerprint) || !editPayload) return;
    setBusy(true);
    setError('');
    try {
      const result = await updateAdminConfig(token, configWriteToken, { ...editPayload, dry_run: false });
      setNotice(result.no_change ? '配置值未变化，版本未增加。' : `配置已应用并创建版本 v${result.new_version}。`);
      setEditItem(null);
      setPreview(null);
      await refresh();
    } catch (requestError) {
      handleMutationError(requestError);
    } finally {
      setBusy(false);
    }
  };

  const runRollbackDryRun = async () => {
    if (!rollbackPayload) return;
    setBusy(true);
    setError('');
    try {
      const result = await rollbackAdminConfig(token, configWriteToken, rollbackPayload);
      setRollbackPreview({ ...result, fingerprint: rollbackFingerprint });
    } catch (requestError) {
      handleMutationError(requestError);
    } finally {
      setBusy(false);
    }
  };

  const applyRollback = async () => {
    if (!canApplyPreview(rollbackPreview, rollbackFingerprint) || !rollbackPayload) return;
    setBusy(true);
    setError('');
    try {
      const result = await rollbackAdminConfig(token, configWriteToken, { ...rollbackPayload, dry_run: false });
      setNotice(`已基于 v${rollbackTarget.version} 的快照创建新版本 v${result.new_version}；历史未删除。`);
      setRollbackTarget(null);
      setRollbackPreview(null);
      await refresh();
    } catch (requestError) {
      handleMutationError(requestError);
    } finally {
      setBusy(false);
    }
  };

  const configColumns = [
    { title: '配置项', dataIndex: 'display_name', key: 'display_name', render: (value, item) => <Space orientation="vertical" size={0}><strong>{value}</strong><Typography.Text code>{item.key}</Typography.Text></Space> },
    { title: '当前值', dataIndex: 'value', key: 'value', render: value => <Tag color={value ? 'green' : 'default'}>{String(value)}</Tag> },
    { title: '来源', dataIndex: 'source', key: 'source', render: value => <Tag>{value}</Tag> },
    { title: '版本', dataIndex: 'version', key: 'version', render: value => `v${value}` },
    { title: '风险', dataIndex: 'risk_level', key: 'risk_level', render: value => <Tag color="orange">{value}</Tag> },
    {
      title: '操作', key: 'action', render: (_, item) => configWriteToken
        ? <Button size="small" onClick={() => openEdit(item)}>修改</Button>
        : <Typography.Text type="secondary">Viewer 仅查看</Typography.Text>,
    },
  ];

  const historyColumns = [
    { title: '版本', dataIndex: 'version', key: 'version', render: value => `v${value}` },
    { title: '操作', dataIndex: 'operation', key: 'operation' },
    { title: '变更键', dataIndex: 'changed_keys', key: 'changed_keys', render: value => value?.join('、') || '基线/无变化' },
    { title: '原因', dataIndex: 'reason', key: 'reason' },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', render: formatObservedAt },
    {
      title: '回滚', key: 'rollback', render: (_, item) => configWriteToken && item.version !== config?.version
        ? <Button size="small" onClick={() => { setRollbackTarget(item); setRollbackReason(''); setRollbackPreview(null); setError(''); }}>准备回滚</Button>
        : null,
    },
  ];

  return (
    <section>
      <div className="admin-page-heading">
        <div>
          <Typography.Text type="secondary">Config Registry · 仅四个 Runtime Feature Flags</Typography.Text>
          <Typography.Title level={2}>配置中心</Typography.Title>
        </div>
        <Space>
          <Tag color="blue">当前 v{config?.version ?? '—'}</Tag>
          {configWriteToken
            ? <Button onClick={clearConfigWrite}>撤销内存写权限</Button>
            : <Button type="primary" onClick={() => setCredentialOpen(true)}>获取写权限</Button>}
          <Button onClick={refresh} loading={loading}>刷新</Button>
        </Space>
      </div>
      <Alert
        type="info"
        showIcon
        title="Visible/Enabled 只控制普通前端意图；不会绕过 MATLAB、模型、报告或其他后端安全门禁。"
        className="admin-config-alert"
      />
      {configWriteToken && <Alert type="warning" showIcon title="配置写凭据仅在当前 React 内存中，刷新或退出后失效。每次 Apply 前必须重新完成 dry-run。" className="admin-config-alert" />}
      {error && <Alert type="error" showIcon title={error} closable onClose={() => setError('')} className="admin-config-alert" />}
      {notice && <Alert type="success" showIcon title={notice} closable onClose={() => setNotice('')} className="admin-config-alert" />}
      <Card title="当前配置" loading={loading}>
        <Table rowKey="key" columns={configColumns} dataSource={config?.items || []} pagination={false} scroll={{ x: 900 }} />
      </Card>
      <Card title="版本历史（append-only）" className="admin-config-history" loading={loading} extra="回滚会创建新版本，不删除历史">
        <Table rowKey="version" columns={historyColumns} dataSource={history} pagination={{ pageSize: 10 }} scroll={{ x: 1000 }} />
      </Card>

      <Modal
        open={credentialOpen}
        title="配置写权限（内存提权）"
        okText="仅保存到当前内存"
        cancelText="取消"
        okButtonProps={{ disabled: !credential.trim() }}
        onCancel={() => { setCredentialOpen(false); setCredential(''); }}
        onOk={() => {
          elevateConfigWrite(credential);
          setCredential('');
          setCredentialOpen(false);
        }}
      >
        <Alert type="warning" showIcon title="Viewer Token 不会自动获得写权限；读写凭据必须独立。" />
        <Form layout="vertical" autoComplete="off" className="admin-config-credential-form">
          <Form.Item label="Config Write Credential">
            <Input.Password value={credential} onChange={event => setCredential(event.target.value)} autoComplete="off" />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        open={Boolean(editItem)}
        size="large"
        title={editItem ? `修改 ${editItem.display_name}` : '修改配置'}
        onClose={() => { setEditItem(null); setPreview(null); }}
        extra={<Tag color="orange">必须先 dry-run</Tag>}
      >
        {editItem && (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="Key">{editItem.key}</Descriptions.Item>
              <Descriptions.Item label="当前值">{String(editItem.value)}</Descriptions.Item>
              <Descriptions.Item label="expected_version">v{config.version}</Descriptions.Item>
              <Descriptions.Item label="影响模块">{editItem.affected_modules.join('、')}</Descriptions.Item>
            </Descriptions>
            <Form layout="vertical">
              <Form.Item label="新值" required>
                <Radio.Group value={editValue} onChange={event => { setEditValue(event.target.value); setPreview(null); }}>
                  <Radio value={true}>true</Radio>
                  <Radio value={false}>false</Radio>
                </Radio.Group>
              </Form.Item>
              <Form.Item label="变更原因" required>
                <Input.TextArea value={reason} maxLength={500} rows={3} onChange={event => { setReason(event.target.value); setPreview(null); }} />
              </Form.Item>
            </Form>
            <Button type="primary" onClick={runDryRun} disabled={!editPayload} loading={busy}>1. 执行 Dry-run</Button>
            <DiffList preview={preview} />
            <Button danger onClick={applyEdit} disabled={!canApplyPreview(preview, editFingerprint)} loading={busy}>2. 确认 Apply</Button>
          </Space>
        )}
      </Drawer>

      <Drawer
        open={Boolean(rollbackTarget)}
        size="large"
        title={rollbackTarget ? `回滚到 v${rollbackTarget.version} 的值` : '配置回滚'}
        onClose={() => { setRollbackTarget(null); setRollbackPreview(null); }}
        extra={<Tag color="orange">创建新版本</Tag>}
      >
        {rollbackTarget && (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            <Alert type="warning" showIcon title="Rollback 不删除或改写旧历史；Apply 后会在当前版本之后创建一个新版本。" />
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="目标快照">v{rollbackTarget.version}</Descriptions.Item>
              <Descriptions.Item label="当前版本">v{config.version}</Descriptions.Item>
              <Descriptions.Item label="目标原因">{rollbackTarget.reason}</Descriptions.Item>
            </Descriptions>
            <Form layout="vertical">
              <Form.Item label="回滚原因" required>
                <Input.TextArea value={rollbackReason} maxLength={500} rows={3} onChange={event => { setRollbackReason(event.target.value); setRollbackPreview(null); }} />
              </Form.Item>
            </Form>
            <Button type="primary" onClick={runRollbackDryRun} disabled={!rollbackPayload} loading={busy}>1. 回滚 Dry-run</Button>
            <DiffList preview={rollbackPreview} />
            <Button danger onClick={applyRollback} disabled={!canApplyPreview(rollbackPreview, rollbackFingerprint)} loading={busy}>2. 创建回滚版本</Button>
          </Space>
        )}
      </Drawer>
    </section>
  );
}

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import { ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import {
  dryRunAdminAction,
  getAdminAction,
  getAdminActions,
  invokeAdminAction,
} from '../api/adminClient.js';
import { adminErrorMessage } from '../api/contracts.js';
import {
  actionResultView,
  buildActionRequest,
  canDryRunAction,
  canInvokeAction,
  defaultActionParameters,
  normalizeActionDescriptor,
  riskMeta,
} from '../actionFlow.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import PageState from '../components/PageState.jsx';

function RiskTag({ level }) {
  const meta = riskMeta(level);
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

function ParameterFields({ action, values, onChange }) {
  const properties = action?.parameter_schema?.properties || {};
  const entries = Object.entries(properties);
  if (!entries.length) return <Alert type="info" showIcon title="此 Action 不接受参数；请求固定为 parameters={}。" />;
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      {entries.map(([key, schema]) => {
        const label = schema.title || key;
        const update = value => onChange({ ...values, [key]: value });
        if (Array.isArray(schema.enum)) {
          return <label key={key}>{label}<Select value={values[key]} options={schema.enum.map(value => ({ value, label: String(value) }))} onChange={update} /></label>;
        }
        if (schema.type === 'boolean') {
          return <label key={key}>{label}<Switch checked={values[key] === true} onChange={update} /></label>;
        }
        if (schema.type === 'number' || schema.type === 'integer') {
          return <label key={key}>{label}<InputNumber value={values[key]} min={schema.minimum} max={schema.maximum} precision={schema.type === 'integer' ? 0 : undefined} onChange={update} /></label>;
        }
        return <label key={key}>{label}<Input value={values[key] ?? ''} maxLength={256} onChange={event => update(event.target.value)} /></label>;
      })}
    </Space>
  );
}

export default function ActionsPage() {
  const { token, session } = useAdminAuth();
  const permissions = session?.identity?.permissions || [];
  const [filters, setFilters] = useState({ category: '', riskLevel: '', available: '' });
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [parameters, setParameters] = useState({});
  const [dryRun, setDryRun] = useState(null);
  const [result, setResult] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setListError(null);
    try {
      const payload = await getAdminActions(token, {
        category: filters.category || null,
        riskLevel: filters.riskLevel || null,
        available: filters.available === '' ? null : filters.available === 'true',
      });
      setItems((payload.items || []).map(normalizeActionDescriptor));
    } catch (error) {
      setListError(error);
    } finally {
      setLoading(false);
    }
  }, [token, filters.category, filters.riskLevel, filters.available]);

  useEffect(() => { refresh(); }, [refresh]);

  const openAction = async (item) => {
    setSelected(item);
    setParameters(defaultActionParameters(item));
    setDryRun(null);
    setResult(null);
    setActionError(null);
    setDetailLoading(true);
    try {
      const detail = normalizeActionDescriptor(await getAdminAction(token, item.action_id));
      setSelected(detail);
      setParameters(defaultActionParameters(detail));
    } catch (error) {
      setActionError(error);
    } finally {
      setDetailLoading(false);
    }
  };

  const requestBody = useMemo(() => {
    if (!selected) return null;
    try {
      return buildActionRequest(selected, parameters);
    } catch {
      return null;
    }
  }, [selected, parameters]);

  const runDryRun = async () => {
    if (!selected || !requestBody) return;
    setBusy(true);
    setActionError(null);
    setDryRun(null);
    setResult(null);
    try {
      setDryRun(await dryRunAdminAction(token, selected.action_id, requestBody.parameters));
    } catch (error) {
      setActionError(error);
    } finally {
      setBusy(false);
    }
  };

  const invoke = async () => {
    if (!selected || !requestBody || !canInvokeAction(selected, dryRun, permissions)) return;
    setBusy(true);
    setActionError(null);
    setResult(null);
    try {
      setResult(await invokeAdminAction(token, selected.action_id, requestBody.parameters));
    } catch (error) {
      setActionError(error);
    } finally {
      setBusy(false);
    }
  };

  const resultView = actionResultView(result);
  const categories = [...new Set(items.map(item => item.category))].map(value => ({ value, label: value }));
  const columns = [
    { title: '操作', dataIndex: 'name', key: 'name', render: (value, item) => <Space orientation="vertical" size={0}><strong>{value}</strong><Typography.Text code>{item.action_id}</Typography.Text></Space> },
    { title: '模块', dataIndex: 'category', key: 'category', width: 110 },
    { title: '风险', dataIndex: 'risk_level', key: 'risk_level', width: 80, render: value => <RiskTag level={value} /> },
    { title: '只读', dataIndex: 'read_only', key: 'read_only', width: 80, render: value => <Tag color={value ? 'success' : 'error'}>{value ? '是' : '否'}</Tag> },
    { title: '状态', dataIndex: 'available', key: 'available', width: 100, render: (value, item) => <Tag color={value && item.enabled ? 'success' : 'default'}>{value && item.enabled ? '可用' : '不可用'}</Tag> },
    { title: 'Dry-run', dataIndex: 'supports_dry_run', key: 'supports_dry_run', width: 90, render: value => value ? '支持' : '不支持' },
    { title: '超时', dataIndex: 'timeout_seconds', key: 'timeout_seconds', width: 80, render: value => `${value}s` },
    { title: '权限', dataIndex: 'required_permission', key: 'required_permission', width: 160 },
    { title: '执行', key: 'execute', width: 110, render: (_, item) => <Button size="small" disabled={!item.available} onClick={event => { event.stopPropagation(); openAction(item); }}>安全检查</Button> },
  ];

  return (
    <section>
      <div className="admin-page-heading">
        <div>
          <Typography.Text type="secondary">Action Registry · Static handlers only</Typography.Text>
          <Typography.Title level={2}>操作中心</Typography.Title>
        </div>
        <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>刷新</Button>
      </div>
      <Alert
        className="admin-action-alert"
        type="info"
        showIcon
        icon={<SafetyCertificateOutlined />}
        title="当前仅开放只读安全操作。"
        description="不提供索引重建、服务重启、模型审批、任意命令、SQL、脚本、路径或 Job Manager。"
      />
      <Card className="admin-action-filters" size="small">
        <Space wrap>
          <Select allowClear placeholder="Category" value={filters.category || undefined} options={categories} onChange={value => setFilters(current => ({ ...current, category: value || '' }))} style={{ width: 180 }} />
          <Select allowClear placeholder="Risk" value={filters.riskLevel || undefined} options={Object.entries({ low: '低', medium: '中', high: '高', critical: '关键' }).map(([value, label]) => ({ value, label }))} onChange={value => setFilters(current => ({ ...current, riskLevel: value || '' }))} style={{ width: 140 }} />
          <Select placeholder="Availability" value={filters.available} options={[{ value: '', label: '全部状态' }, { value: 'true', label: '可用' }, { value: 'false', label: '不可用' }]} onChange={value => setFilters(current => ({ ...current, available: value }))} style={{ width: 150 }} />
        </Space>
      </Card>
      <PageState loading={loading} error={listError} onRetry={refresh} empty={!loading && !listError && items.length === 0}>
        <Card loading={loading}>
          <Table rowKey="action_id" columns={columns} dataSource={items} pagination={false} scroll={{ x: 1120 }} onRow={item => ({ onClick: () => openAction(item) })} rowClassName="admin-clickable-row" />
        </Card>
      </PageState>

      <Drawer
        open={Boolean(selected)}
        size="large"
        title={selected?.name || 'Action Detail'}
        onClose={() => setSelected(null)}
        extra={selected ? <RiskTag level={selected.risk_level} /> : null}
        loading={detailLoading}
      >
        {selected && (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="Action ID">{selected.action_id}</Descriptions.Item>
              <Descriptions.Item label="说明">{selected.description}</Descriptions.Item>
              <Descriptions.Item label="Category">{selected.category}</Descriptions.Item>
              <Descriptions.Item label="Risk"><RiskTag level={selected.risk_level} /></Descriptions.Item>
              <Descriptions.Item label="Read-only">{selected.read_only ? '是' : '否'}</Descriptions.Item>
              <Descriptions.Item label="Side Effects">{selected.side_effects.length ? selected.side_effects.join('、') : '[]'}</Descriptions.Item>
              <Descriptions.Item label="Timeout / Concurrency">{selected.timeout_seconds}s / {selected.concurrency_limit}</Descriptions.Item>
              <Descriptions.Item label="Permission">{selected.required_permission}</Descriptions.Item>
              <Descriptions.Item label="Availability">{selected.available ? '可用' : selected.availability_reason || '不可用'}</Descriptions.Item>
            </Descriptions>
            <Card size="small" title="Parameter Schema（受控）"><pre className="admin-json-view">{JSON.stringify(selected.parameter_schema, null, 2)}</pre></Card>
            <Card size="small" title="1. 结构化参数"><ParameterFields action={selected} values={parameters} onChange={value => { setParameters(value); setDryRun(null); setResult(null); }} /></Card>
            <Button type="primary" onClick={runDryRun} loading={busy} disabled={!requestBody || !canDryRunAction(selected, permissions)}>2. Dry-run</Button>
            {dryRun && (
              <Card size="small" title={dryRun.allowed ? 'Dry-run：Allowed' : 'Dry-run：Blocked'}>
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="Allowed">{String(dryRun.allowed)}</Descriptions.Item>
                  <Descriptions.Item label="Risk">{dryRun.risk_level}</Descriptions.Item>
                  <Descriptions.Item label="Parameters"><pre className="admin-json-view">{JSON.stringify(dryRun.normalized_parameters, null, 2)}</pre></Descriptions.Item>
                  <Descriptions.Item label="Preconditions"><pre className="admin-json-view">{JSON.stringify(dryRun.preconditions, null, 2)}</pre></Descriptions.Item>
                  <Descriptions.Item label="Warnings">{dryRun.warnings?.join('；') || '无'}</Descriptions.Item>
                  <Descriptions.Item label="Side Effects">{dryRun.side_effects?.length ? dryRun.side_effects.join('、') : '[]'}</Descriptions.Item>
                </Descriptions>
              </Card>
            )}
            <Button onClick={invoke} loading={busy} disabled={!canInvokeAction(selected, dryRun, permissions)}>3. 执行安全检查</Button>
            {actionError && (
              <Alert
                type={actionError.code === 'ADMIN_ACTION_TIMEOUT' ? 'warning' : 'error'}
                showIcon
                title={`${actionError.code || 'ADMIN_ACTION_FAILED'} · ${adminErrorMessage(actionError)}`}
                description={actionError.requestId ? `Request ID: ${actionError.requestId}` : undefined}
              />
            )}
            {resultView && (
              <Card size="small" title={`结果：${resultView.status}`}>
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="Status">{resultView.status}</Descriptions.Item>
                  <Descriptions.Item label="Duration">{resultView.durationMs} ms</Descriptions.Item>
                  <Descriptions.Item label="Invocation ID">{resultView.invocationId}</Descriptions.Item>
                  <Descriptions.Item label="Summary"><pre className="admin-json-view">{JSON.stringify(resultView.summary, null, 2)}</pre></Descriptions.Item>
                  <Descriptions.Item label="Metrics"><pre className="admin-json-view">{JSON.stringify(resultView.metrics, null, 2)}</pre></Descriptions.Item>
                  <Descriptions.Item label="Warnings">{resultView.warnings.join('；') || '无'}</Descriptions.Item>
                </Descriptions>
                <details><summary>技术原始 JSON（已由后端 sanitizer 处理）</summary><pre className="admin-json-view">{JSON.stringify(result, null, 2)}</pre></details>
              </Card>
            )}
            {!dryRun && !result && !actionError && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先完成 Dry-run" />}
          </Space>
        )}
      </Drawer>
    </section>
  );
}

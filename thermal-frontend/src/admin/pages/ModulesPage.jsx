import { useCallback, useMemo, useState } from 'react';
import { Button, Card, Select, Space, Table, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { checkAllAdminModules, getAdminModules } from '../api/adminClient.js';
import { booleanState, formatObservedAt } from '../api/contracts.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import HealthBadge from '../components/HealthBadge.jsx';
import PageState from '../components/PageState.jsx';
import useAdminResource from '../hooks/useAdminResource.js';
import { useAppTheme } from '../../theme/useAppTheme.js';
import { HyperBenchmarkNote } from '../components/HyperLab.jsx';

export default function ModulesPage() {
  const { token } = useAdminAuth();
  const { themeId } = useAppTheme();
  const hyper = themeId === 'hyper';
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState(null);
  const [categoryFilter, setCategoryFilter] = useState(null);
  const [checking, setChecking] = useState(false);
  const loader = useCallback(() => getAdminModules(token), [token]);
  const { data, loading, error, refresh } = useAdminResource(loader);
  const items = useMemo(() => (data?.items || []).filter(item => (
    (!statusFilter || item.status === statusFilter) && (!categoryFilter || item.category === categoryFilter)
  )), [data, statusFilter, categoryFilter]);
  const categories = [...new Set((data?.items || []).map(item => item.category))].sort();

  const checkAll = async () => {
    setChecking(true);
    try {
      await checkAllAdminModules(token);
      refresh();
    } finally {
      setChecking(false);
    }
  };

  return (
    <section>
      <div className="admin-page-heading">
        <div>
          <Typography.Title level={2}>模块监控</Typography.Title>
          <Typography.Text type="secondary">{hyper ? `${Array.isArray(data?.items) ? data.items.length : '—'} 个注册模块；实际检查数据来自模块 API。` : '16 个注册模块；disabled 不计为异常，unknown 不显示为健康。'}</Typography.Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
          <Button type="primary" onClick={checkAll} loading={checking}>执行全部只读检查</Button>
        </Space>
      </div>
      <PageState loading={loading} error={error} onRetry={refresh} empty={!loading && !error && items.length === 0}>
        {hyper && <div className="hyper-lab-modules">{[
          ['REGISTRY', '已注册模块', Array.isArray(data?.items) ? data.items.length : null],
          ['READY', '明确就绪', Array.isArray(data?.items) ? data.items.filter(item => item.ready === true).length : null],
          ['NOT CHECKED', '就绪状态未检查', Array.isArray(data?.items) ? data.items.filter(item => typeof item.ready !== 'boolean').length : null],
        ].map(([english, title, value]) => <div className="hyper-lab-module-summary" key={english}><span className="hyper-lab-kicker">{english}</span><strong>{value ?? '—'}</strong><span>{title}</span></div>)}</div>}
        <Card>
          <Space wrap className="admin-table-filters">
            <Select allowClear placeholder="按状态筛选" value={statusFilter} onChange={setStatusFilter} style={{ width: 160 }} options={['healthy', 'degraded', 'unhealthy', 'disabled', 'unavailable', 'unknown'].map(value => ({ value, label: value }))} />
            <Select allowClear placeholder="按类别筛选" value={categoryFilter} onChange={setCategoryFilter} style={{ width: 160 }} options={categories.map(value => ({ value, label: value }))} />
          </Space>
          <Table
            rowKey="module_id"
            dataSource={items}
            pagination={{ pageSize: 12 }}
            onRow={item => ({ onClick: () => navigate(`/admin/modules/${encodeURIComponent(item.module_id)}`) })}
            rowClassName="admin-clickable-row"
            scroll={{ x: 980 }}
            columns={[
              { title: '模块', dataIndex: 'name', fixed: 'left', width: 180 },
              { title: '类别', dataIndex: 'category', width: 110 },
              { title: '状态', dataIndex: 'status', width: 100, render: value => <HealthBadge status={value} /> },
              { title: '启用', dataIndex: 'enabled', width: 80, render: booleanState },
              { title: '可用', dataIndex: 'available', width: 90, render: booleanState },
              { title: '就绪', dataIndex: 'ready', width: 90, render: booleanState },
              { title: '健康', dataIndex: 'healthy', width: 90, render: booleanState },
              { title: '耗时', dataIndex: 'latency_ms', width: 90, render: value => `${value} ms` },
              { title: '最后检查', dataIndex: 'observed_at', width: 180, render: formatObservedAt },
              { title: '说明', dataIndex: 'message', ellipsis: true },
            ]}
          />
        </Card>
        {hyper && <HyperBenchmarkNote />}
      </PageState>
    </section>
  );
}

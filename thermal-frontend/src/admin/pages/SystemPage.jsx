import { useCallback } from 'react';
import { Button, Card, Table, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { getAdminSystem } from '../api/adminClient.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import HealthBadge from '../components/HealthBadge.jsx';
import PageState from '../components/PageState.jsx';
import JsonPreview from '../components/JsonPreview.jsx';
import useAdminResource from '../hooks/useAdminResource.js';
import { systemComponentName, systemComponentSummary } from '../presentation/adminPresentation.js';

export default function SystemPage() {
  const { token } = useAdminAuth();
  const loader = useCallback(() => getAdminSystem(token), [token]);
  const { data, loading, error, refresh } = useAdminResource(loader);

  return (
    <section>
      <div className="admin-page-heading">
        <div><Typography.Title level={2}>系统</Typography.Title><Typography.Text type="secondary">查看 ThermalAgent 各项服务的运行状态。</Typography.Text></div>
        <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
      </div>
      <Card title="系统组件">
        <PageState loading={loading} error={error} empty={!loading && !data?.items?.length} onRetry={refresh}>
          <Table
            rowKey="module_id"
            dataSource={data?.items || []}
            pagination={{ pageSize: 30 }}
            scroll={{ x: 720 }}
            columns={[
              { title: '组件', key: 'name', width: 190, render: (_, item) => systemComponentName(item) },
              { title: '状态', dataIndex: 'status', width: 120, render: value => <HealthBadge status={value} /> },
              { title: '说明', key: 'summary', ellipsis: true, render: (_, item) => systemComponentSummary(item) },
            ]}
          />
        </PageState>
      </Card>
      {data && <JsonPreview label="查看高级诊断" value={data} />}
    </section>
  );
}

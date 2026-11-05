import { useCallback, useState } from 'react';
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons';
import { Button, Card, Descriptions, Space, Tag, Typography } from 'antd';
import { useNavigate, useParams } from 'react-router-dom';
import { checkAdminModule, getAdminModule } from '../api/adminClient.js';
import { booleanState, formatObservedAt } from '../api/contracts.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import HealthBadge from '../components/HealthBadge.jsx';
import PageState from '../components/PageState.jsx';
import useAdminResource from '../hooks/useAdminResource.js';

export default function ModuleDetailPage() {
  const { moduleId } = useParams();
  const { token } = useAdminAuth();
  const navigate = useNavigate();
  const [checking, setChecking] = useState(false);
  const loader = useCallback(() => getAdminModule(token, moduleId), [token, moduleId]);
  const { data, loading, error, refresh, setData } = useAdminResource(loader);

  const check = async () => {
    setChecking(true);
    try {
      const result = await checkAdminModule(token, moduleId);
      setData(result.module);
    } finally {
      setChecking(false);
    }
  };

  return (
    <section>
      <div className="admin-page-heading">
        <div>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/modules')}>返回模块列表</Button>
          <Typography.Title level={2}>{data?.name || moduleId}</Typography.Title>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh}>刷新缓存</Button>
          <Button type="primary" onClick={check} loading={checking}>执行单模块只读检查</Button>
        </Space>
      </div>
      <PageState loading={loading} error={error} onRetry={refresh}>
        {data && (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            <Card>
              <Descriptions bordered column={2}>
                <Descriptions.Item label="Module ID">{data.module_id}</Descriptions.Item>
                <Descriptions.Item label="类别">{data.category}</Descriptions.Item>
                <Descriptions.Item label="状态"><HealthBadge status={data.status} /></Descriptions.Item>
                <Descriptions.Item label="已配置">{booleanState(data.configured)}</Descriptions.Item>
                <Descriptions.Item label="已启用">{booleanState(data.enabled)}</Descriptions.Item>
                <Descriptions.Item label="可用">{booleanState(data.available)}</Descriptions.Item>
                <Descriptions.Item label="就绪">{booleanState(data.ready)}</Descriptions.Item>
                <Descriptions.Item label="健康">{booleanState(data.healthy)}</Descriptions.Item>
                <Descriptions.Item label="实验性">{booleanState(data.experimental)}</Descriptions.Item>
                <Descriptions.Item label="可选模块">{booleanState(data.optional)}</Descriptions.Item>
                <Descriptions.Item label="检查耗时">{data.latency_ms} ms</Descriptions.Item>
                <Descriptions.Item label="观测时间">{formatObservedAt(data.observed_at)}</Descriptions.Item>
                <Descriptions.Item label="数据源">{data.source}</Descriptions.Item>
                <Descriptions.Item label="错误码">{data.error_code || '无'}</Descriptions.Item>
                <Descriptions.Item label="依赖" span={2}>{data.dependencies?.length ? data.dependencies.map(item => <Tag key={item}>{item}</Tag>) : '无'}</Descriptions.Item>
                <Descriptions.Item label="说明" span={2}>{data.message}</Descriptions.Item>
                <Descriptions.Item label="建议" span={2}>{data.next_action || '无需操作'}</Descriptions.Item>
              </Descriptions>
            </Card>
            <Card title="安全指标">
              <pre className="admin-json-view">{JSON.stringify(data.metrics || {}, null, 2)}</pre>
              <Typography.Text type="secondary">本次检查副作用：{data.side_effects?.length ? data.side_effects.join(', ') : '无'}</Typography.Text>
            </Card>
          </Space>
        )}
      </PageState>
    </section>
  );
}

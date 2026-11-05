import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Descriptions, Drawer, Space, Table, Tag, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { getAdminAudit, getAdminAuditEvent, getWorkflowAudit } from '../api/adminClient.js';
import { formatObservedAt } from '../api/contracts.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import PageState from '../components/PageState.jsx';
import JsonPreview from '../components/JsonPreview.jsx';
import useAdminResource from '../hooks/useAdminResource.js';
import { auditActionPresentation } from '../presentation/adminPresentation.js';

export default function AuditPage() {
  const { token } = useAdminAuth();
  const [cursor, setCursor] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const loader = useCallback(async () => {
    const [legacy, workflow] = await Promise.all([
      getAdminAudit(token, { limit: 50, cursor }),
      getWorkflowAudit(token, { limit: 100 }),
    ]);
    const workflowItems = (workflow.items || []).map(item => ({
      ...item,
      audit_id: item.event_id,
      target_id: item.resource_id,
      success: item.result === 'success',
      risk_level: 'high',
      source: 'admin_v1_workflow',
    }));
    return { ...legacy, items: [...workflowItems, ...(legacy.items || [])].sort((a, b) => String(b.timestamp || '').localeCompare(String(a.timestamp || ''))) };
  }, [token, cursor]);
  const { data, loading, error, refresh } = useAdminResource(loader);

  useEffect(() => {
    let active = true;
    if (!selectedId) {
      setDetail(null);
      return undefined;
    }
    const embedded = data?.items?.find(item => item.audit_id === selectedId && item.source === 'admin_v1_workflow');
    if (embedded) {
      setDetail(embedded);
      return undefined;
    }
    getAdminAuditEvent(token, selectedId).then(value => {
      if (active) setDetail(value);
    }).catch(() => {
      if (active) setDetail(null);
    });
    return () => { active = false; };
  }, [selectedId, token, data?.items]);

  return (
    <section>
      <div className="admin-page-heading">
        <div>
          <Typography.Title level={2}>操作记录</Typography.Title>
          <Typography.Text type="secondary">查看管理员的重要操作及执行结果。</Typography.Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
      </div>
      <PageState loading={loading} error={error} onRetry={refresh} empty={!loading && !error && !data?.items?.length}>
        <Card>
          <Table
            rowKey="audit_id"
            dataSource={data?.items || []}
            pagination={false}
            onRow={item => ({ onClick: () => setSelectedId(item.audit_id) })}
            rowClassName="admin-clickable-row"
            scroll={{ x: 920 }}
            columns={[
              { title: '时间', dataIndex: 'timestamp', width: 190, render: formatObservedAt },
              { title: '操作人', dataIndex: 'actor_id', width: 160, ellipsis: true, render: value => value || '管理员' },
              { title: '操作', dataIndex: 'action', width: 210, render: auditActionPresentation },
              { title: '对象', dataIndex: 'target_id', ellipsis: true, render: value => value || '—' },
              { title: '结果', dataIndex: 'success', width: 90, render: value => <Tag color={value ? 'success' : 'error'}>{value ? '成功' : '失败'}</Tag> },
            ]}
          />
          <Space className="admin-pagination">
            <Button disabled={!cursor} onClick={() => setCursor(null)}>返回首批</Button>
            <Button disabled={!data?.next_cursor} onClick={() => setCursor(data.next_cursor)}>下一批</Button>
            <Typography.Text type="secondary">当前显示 {data?.returned || data?.items?.length || 0} 条</Typography.Text>
          </Space>
        </Card>
      </PageState>
      <Drawer title="操作详情" size="large" open={Boolean(selectedId)} onClose={() => setSelectedId(null)}>
        {detail ? (
          <>
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="时间">{formatObservedAt(detail.timestamp)}</Descriptions.Item>
              <Descriptions.Item label="操作人">{detail.actor_id || detail.actor || '管理员'}</Descriptions.Item>
              <Descriptions.Item label="操作">{auditActionPresentation(detail.action)}</Descriptions.Item>
              <Descriptions.Item label="对象">{detail.target_id || detail.resource_id || '—'}</Descriptions.Item>
              <Descriptions.Item label="结果">{detail.success === false || detail.result === 'failure' ? '失败' : '成功'}</Descriptions.Item>
              {(detail.before || detail.after) && <Descriptions.Item label="变化">已记录操作前后的安全快照</Descriptions.Item>}
            </Descriptions>
            <JsonPreview label="查看高级信息" value={detail} />
          </>
        ) : <Typography.Text type="secondary">正在读取脱敏详情…</Typography.Text>}
      </Drawer>
    </section>
  );
}

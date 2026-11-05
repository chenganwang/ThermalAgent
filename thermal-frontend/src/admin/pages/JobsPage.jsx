import { useCallback, useState } from 'react';
import { Alert, Button, Card, Descriptions, Drawer, Progress, Select, Space, Table, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { getAdminJob, getAdminJobs, retryAdminJob } from '../api/adminClient.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import AdminStatusBadge from '../components/AdminStatusBadge.jsx';
import JsonPreview from '../components/JsonPreview.jsx';
import PageState from '../components/PageState.jsx';
import WorkflowCredential from '../components/WorkflowCredential.jsx';
import useAdminResource from '../hooks/useAdminResource.js';
import { formatDate, jobStatusPresentation, jobTypePresentation } from '../presentation/adminPresentation.js';

export default function JobsPage() {
  const { token, workflowWriteToken } = useAdminAuth();
  const [selected, setSelected] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [retrying, setRetrying] = useState(false);
  const loader = useCallback(() => getAdminJobs(token, { limit: 200, status: statusFilter, job_type: typeFilter }), [token, statusFilter, typeFilter]);
  const { data, loading, error, refresh } = useAdminResource(loader);

  const open = async (job) => setSelected(await getAdminJob(token, job.job_id));
  const retry = async () => {
    setRetrying(true);
    try {
      await retryAdminJob(token, workflowWriteToken, selected.job_id);
      setSelected(null);
      await refresh();
    } finally {
      setRetrying(false);
    }
  };

  return (
    <section>
      <div className="admin-page-heading">
        <div><Typography.Title level={2}>任务记录</Typography.Title><Typography.Text type="secondary">查看文档处理与模型检查任务的进度和结果。</Typography.Text></div>
        <Space wrap><WorkflowCredential /><Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button></Space>
      </div>
      <Card>
        <Alert className="admin-section-alert" type="info" showIcon title="任务记录保存在当前主机" description="应用重启前正在执行的任务可能需要重新发起；已完成记录可在刷新后继续查看。" />
        <Space wrap className="admin-filter-bar">
          <Select aria-label="任务状态" value={statusFilter} onChange={setStatusFilter} style={{ width: 160 }} options={[
            { value: '', label: '全部状态' }, { value: 'queued', label: '等待中' }, { value: 'running', label: '执行中' },
            { value: 'succeeded', label: '已完成' }, { value: 'failed', label: '失败' }, { value: 'cancelled', label: '已取消' },
          ]} />
          <Select aria-label="任务类型" value={typeFilter} onChange={setTypeFilter} style={{ width: 220 }} options={[
            { value: '', label: '全部类型' }, { value: 'document_preflight', label: '文档预检' },
            { value: 'document_dry_run', label: '文档切分预览' }, { value: 'document_commit', label: '文档入库' },
            { value: 'model_validation', label: '模型校验' }, { value: 'model_smoke', label: '模型测试' },
          ]} />
        </Space>
        <PageState loading={loading} error={error} empty={!loading && !data?.items?.length} onRetry={refresh}>
          <Table
            rowKey="job_id"
            dataSource={data?.items || []}
            pagination={{ pageSize: 30 }}
            rowClassName="admin-clickable-row"
            onRow={item => ({ onClick: () => open(item) })}
            scroll={{ x: 1050 }}
            columns={[
              { title: '任务', dataIndex: 'type', width: 180, render: jobTypePresentation },
              { title: '对象', dataIndex: 'resource_id', ellipsis: true },
              { title: '状态', dataIndex: 'status', width: 110, render: value => <AdminStatusBadge value={value} presentation={jobStatusPresentation} /> },
              { title: '进度', dataIndex: 'progress', width: 150, render: value => <Progress percent={value || 0} size="small" /> },
              { title: '开始', dataIndex: 'started_at', width: 190, render: formatDate },
              { title: '耗时', dataIndex: 'duration_ms', width: 100, render: value => value == null ? '—' : `${value} ms` },
              { title: '消息', dataIndex: 'message', ellipsis: true },
            ]}
          />
        </PageState>
      </Card>
      <Drawer title="任务详情" size="large" open={Boolean(selected)} onClose={() => setSelected(null)}>
        {selected && <>
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="任务">{jobTypePresentation(selected.type)}</Descriptions.Item>
            <Descriptions.Item label="状态"><AdminStatusBadge value={selected.status} presentation={jobStatusPresentation} /></Descriptions.Item>
            <Descriptions.Item label="对象">{selected.resource_id || '—'}</Descriptions.Item>
            <Descriptions.Item label="开始时间">{formatDate(selected.started_at || selected.created_at)}</Descriptions.Item>
            <Descriptions.Item label="完成时间">{formatDate(selected.finished_at)}</Descriptions.Item>
            <Descriptions.Item label="说明">{selected.message || '—'}</Descriptions.Item>
          </Descriptions>
          <JsonPreview label="高级信息" value={selected} />
          <Button
            type="primary"
            loading={retrying}
            disabled={!workflowWriteToken || !['failed', 'cancelled'].includes(selected.status) || !['document_preflight', 'document_dry_run', 'document_commit', 'document_ingestion'].includes(selected.type)}
            onClick={retry}
          >安全重试</Button>
          {!['document_preflight', 'document_dry_run', 'document_commit', 'document_ingestion'].includes(selected.type) && <Typography.Paragraph type="secondary">此类型无法从回执安全重建，不提供重试。</Typography.Paragraph>}
        </>}
      </Drawer>
    </section>
  );
}

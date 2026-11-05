import { Alert, Button, Card, Progress, Space, Table, Tag, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { coverageView } from '../presentation/experience.js';
import { formatDate } from '../presentation/adminPresentation.js';
import { LabTitle } from './AnimeLab.jsx';

export default function KnowledgeCoverage({ data, compact = false }) {
  const view = coverageView(data);
  const navigate = useNavigate();
  return <Card className="admin-coverage" title={<LabTitle code="01" english="KNOWLEDGE LINK">知识库 → 当前检索索引</LabTitle>} extra={<Tag color={view.status === 'gap' ? 'warning' : view.known ? 'blue' : 'default'}>{view.label}</Tag>}>
    <div className="admin-coverage-flow">
      <div><span>有效内容片段</span><strong>{view.active ?? '—'}</strong></div>
      <div><span>已映射到当前索引</span><strong>{view.indexed ?? '—'}</strong></div>
      <div><span>待覆盖片段</span><strong className={view.missing > 0 ? 'admin-attention-number' : ''}>{view.missing ?? '—'}</strong></div>
    </div>
    {view.percent !== null && <Progress percent={Number(view.percent.toFixed(1))} strokeColor="var(--ta-primary)" trailColor="var(--ta-surface-muted)" />}
    <Alert type={view.status === 'gap' || !view.known ? 'warning' : 'info'} showIcon title={view.description} />
    <div className="admin-coverage-note"><Typography.Text type="secondary">数据来源：当前数据库有效片段、索引元数据与映射。覆盖不代表检索质量验收。{data?.observed_at && ` 更新于 ${formatDate(data.observed_at)}`}</Typography.Text></div>
    {compact ? <Button className="admin-detail-actions" onClick={() => navigate('/admin/knowledge')}>查看各文档覆盖</Button> : <Table
      className="admin-detail-actions" size="small" rowKey="document_id" dataSource={data?.documents || []} pagination={{ pageSize: 10 }} scroll={{ x: 600 }}
      columns={[
        { title: '文档', dataIndex: 'title', render: (title, row) => <Button type="link" onClick={() => navigate(`/admin/knowledge/${row.document_id}`)}>{title}</Button> },
        { title: '有效片段', dataIndex: 'active_chunks' },
        { title: '已映射', dataIndex: 'indexed_chunks', render: value => value ?? '—' },
        { title: '待覆盖', dataIndex: 'missing_chunks', render: value => value ?? '—' },
        { title: '覆盖', dataIndex: 'status', render: value => <Space><Tag color={value === 'gap' ? 'warning' : value === 'covered' ? 'blue' : 'default'}>{value === 'gap' ? '待更新' : value === 'covered' ? '已覆盖' : '未获取'}</Tag></Space> },
      ]} />}
  </Card>;
}

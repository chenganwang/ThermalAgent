import { useCallback } from 'react';
import { Alert, Button, Card, Col, Empty, Row, Space, Statistic, Table, Typography } from 'antd';
import { ArrowRightOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { getAdminDashboard, getAgentTasks, getGeneratedModels, getKnowledgeCoverage } from '../api/adminClient.js';
import { formatObservedAt } from '../api/contracts.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import HealthBadge from '../components/HealthBadge.jsx';
import PageState from '../components/PageState.jsx';
import KnowledgeCoverage from '../components/KnowledgeCoverage.jsx';
import AgentTaskTable from '../components/AgentTaskTable.jsx';
import useAdminResource from '../hooks/useAdminResource.js';
import { systemComponentName, modelStatusPresentation, normalizeGeneratedModel } from '../presentation/adminPresentation.js';
import AdminStatusBadge from '../components/AdminStatusBadge.jsx';
import { knownCount, monitorTotal } from '../presentation/experience.js';
import { useAppTheme } from '../../theme/useAppTheme.js';
import { LabCoolingDrawing, LabTitle } from '../components/AnimeLab.jsx';
import { HyperBenchmarkNote, HyperLabHero } from '../components/HyperLab.jsx';

export default function OverviewPage() {
  const { token } = useAdminAuth();
  const { themeId } = useAppTheme();
  const anime = themeId === 'cel';
  const hyper = themeId === 'hyper';
  const navigate = useNavigate();
  const loader = useCallback(async () => {
    const keys = ['dashboard', 'coverage', 'tasks', 'models'];
    const responses = await Promise.allSettled([getAdminDashboard(token), getKnowledgeCoverage(token), getAgentTasks(token, { limit: 6 }), getGeneratedModels(token)]);
    return Object.fromEntries(keys.map((key, index) => [key, responses[index].status === 'fulfilled' ? { data: responses[index].value } : { error: responses[index].reason }]));
  }, [token]);
  const resource = useAdminResource(loader);
  const dashboard = resource.data?.dashboard.data;
  const tasks = resource.data?.tasks.data;
  const modules = dashboard?.modules || [];
  const models = resource.data?.models.data?.items?.map(raw => ({ ...normalizeGeneratedModel(raw), status: raw.status || 'unknown' }));
  return <section>
    <div className="admin-page-heading"><div><Typography.Title level={2}>系统概览</Typography.Title><Typography.Text type="secondary">从知识到执行，查看工程助手当前可用能力与待处理事项。</Typography.Text></div><Button icon={<ReloadOutlined />} onClick={resource.refresh} loading={resource.loading}>刷新状态</Button></div>
    {hyper ? <HyperLabHero dashboard={dashboard} /> : anime ? <div className="admin-overview-hero lab-overview-sheet"><div className="lab-hero-copy"><span className="lab-chapter-label">OPERATIONS FILE / 研究档案</span><p className="lab-hero-title">CONTROL<br /><em>THE NEXT</em> DESIGN<span aria-hidden="true">.</span></p><Typography.Title level={3}>每次工程探索，都有据可循。</Typography.Title><Typography.Paragraph>知识、计算与物理验证在这里汇合。查看真实状态，追踪每一次工程任务。</Typography.Paragraph><Button type="primary" icon={<ArrowRightOutlined />} onClick={() => navigate('/admin/agent-tasks')}>打开任务监控</Button></div><LabCoolingDrawing /></div> : <div className="admin-overview-hero"><div><span className="admin-eyebrow">THERMALAGENT / OPERATIONS</span><Typography.Title level={3}>让每次工程回答，都有可追踪的基础。</Typography.Title><Typography.Paragraph>知识覆盖、执行记录与模型审核在这里汇合。先确认数据状态，再进入对应工作区处理。</Typography.Paragraph></div><Button type="primary" icon={<ArrowRightOutlined />} onClick={() => navigate('/admin/agent-tasks')}>查看 Agent 运行</Button></div>}
    <PageState loading={resource.loading} error={resource.error} onRetry={resource.refresh}>
      {!resource.loading && <>
        <Row gutter={[16, 16]} className="admin-section-card">
          {[
            ['已入库文档', knownCount(dashboard?.statistics?.documents), '/admin/knowledge'],
            ['有效知识片段', knownCount(resource.data?.coverage.data?.active_chunks), '/admin/knowledge'],
            ['仿真模型资产', knownCount(dashboard?.statistics?.simulation_models), '/admin/simulation-models'],
            ['已记录 Agent 任务', monitorTotal(tasks), '/admin/agent-tasks'],
          ].map(([title, value, path], index) => <Col xs={12} xl={6} key={title}><Card className="admin-metric-card">{hyper && <div className="hyper-lab-metric-tag"><span>{['KNOWLEDGE', 'FRAGMENTS', 'MODEL ASSETS', 'MISSION LOG'][index]}</span><b>{String(index + 1).padStart(2, '0')}</b></div>}{anime && <div className="lab-metric-register"><span>{['KNOWLEDGE', 'FRAGMENTS', 'MODEL ASSETS', 'MISSION LOG'][index]}</span><b>{String(index + 1).padStart(2, '0')}</b></div>}<Statistic title={title} value={value ?? '—'} /><Button type="link" onClick={() => navigate(path)}>{value === null ? '查看数据状态' : '查看详情'} <ArrowRightOutlined /></Button></Card></Col>)}
        </Row>
        <PageState error={resource.data?.coverage.error} onRetry={resource.refresh}><KnowledgeCoverage data={resource.data?.coverage.data} compact /></PageState>
        <Card title={<LabTitle code="02" english="MISSION ARCHIVE">近期 Agent 任务</LabTitle>} className="admin-section-card" extra={<Button type="link" onClick={() => navigate('/admin/agent-tasks')}>全部执行记录</Button>}>
          <PageState error={resource.data?.tasks.error} onRetry={resource.refresh}>{tasks && (tasks.store_available === false ? <Empty description="任务存储尚未建立，当前任务数量未知。" /> : <AgentTaskTable tasks={tasks.tasks || []} onSelect={() => navigate('/admin/agent-tasks')} />)}</PageState>
        </Card>
        <Row gutter={[16, 16]}>
          <Col xs={24} xl={13}><Card title={<LabTitle code="03" english="SYSTEM COMPONENTS">服务组件</LabTitle>} extra={<Button type="link" onClick={() => navigate('/admin/system')}>系统详情</Button>}><PageState error={resource.data?.dashboard.error} onRetry={resource.refresh}>
            {dashboard && <><Space className="admin-section-alert">组件检查 <HealthBadge status={dashboard.overall_status?.status} /><Typography.Text type="secondary">{formatObservedAt(dashboard.generated_at)}</Typography.Text></Space><Table size="small" pagination={false} rowKey="module_id" dataSource={modules.slice(0, 6)} columns={[{ title: '组件', key: 'name', render: (_, item) => systemComponentName(item) }, { title: '状态', dataIndex: 'status', render: value => <HealthBadge status={value} /> }]} /></>}
          </PageState></Card></Col>
          <Col xs={24} xl={11}><Card title={<LabTitle code="04" english="MODEL REVIEW">生成模型审核</LabTitle>} extra={<Button type="link" onClick={() => navigate('/admin/simulation-models')}>管理模型</Button>}><PageState error={resource.data?.models.error} onRetry={resource.refresh}>
            {models && <Table size="small" rowKey="generationId" pagination={{ pageSize: 5, hideOnSinglePage: true }} dataSource={models} columns={[{ title: '模型', dataIndex: 'displayName', render: (value, item) => value || item.modelId }, { title: '审核状态', dataIndex: 'status', render: value => <AdminStatusBadge value={value} presentation={modelStatusPresentation} /> }]} />}
          </PageState><Alert type="info" showIcon title="模型审核与可执行性分别记录" description="查看模型详情中的校验、编译和执行限制。" /></Card></Col>
        </Row>
        {hyper && <HyperBenchmarkNote />}
      </>}
    </PageState>
  </section>;
}

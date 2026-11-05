import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, Drawer, Empty, Space, Table, Tag, Timeline, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { getAgentTask, getAgentTasks } from '../api/adminClient.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import useAdminResource from '../hooks/useAdminResource.js';
import PageState from '../components/PageState.jsx';
import AgentTaskTable from '../components/AgentTaskTable.jsx';
import JsonPreview from '../components/JsonPreview.jsx';
import { monitorTotal, taskStatus } from '../presentation/experience.js';
import { formatDate } from '../presentation/adminPresentation.js';
import { useAppTheme } from '../../theme/useAppTheme.js';
import { LabTitle } from '../components/AnimeLab.jsx';
import { HyperMonitorIntro } from '../components/HyperLab.jsx';
import MarkdownContent from '../../MarkdownContent.jsx';

export default function AgentTasksPage() {
  const { token } = useAdminAuth();
  const { themeId } = useAppTheme();
  const anime = themeId === 'cel';
  const hyper = themeId === 'hyper';
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const loader = useCallback(() => getAgentTasks(token, { limit: 20, offset: (page - 1) * 20 }), [token, page]);
  const list = useAdminResource(loader);
  const detailLoader = useCallback(() => selected ? getAgentTask(token, selected) : Promise.resolve(null), [token, selected]);
  const detail = useAdminResource(detailLoader);
  const refreshList = list.refresh;
  const refreshDetail = detail.refresh;
  useEffect(() => {
    if (!autoRefresh) return undefined;
    const timer = setInterval(() => { refreshList(); if (selected) refreshDetail(); }, 10000);
    return () => clearInterval(timer);
  }, [autoRefresh, refreshList, refreshDetail, selected]);
  const total = monitorTotal(list.data);
  return <section>
    <div className="admin-page-heading"><div><Typography.Title level={2}>Agent 运行监控</Typography.Title><Typography.Text type="secondary">查看真实工程任务的执行步骤、结果与异常，记录来自同一任务存储。</Typography.Text></div>
      <Space wrap><Button onClick={() => setAutoRefresh(value => !value)}>{autoRefresh ? '停止自动刷新' : '每 10 秒刷新'}</Button><Button icon={<ReloadOutlined />} loading={list.loading} onClick={list.refresh}>刷新</Button></Space></div>
    {hyper && <HyperMonitorIntro total={total} />}
    {anime && <div className="lab-monitor-intro"><span>MISSION CONTROL</span><p>任务档案 / 从目标到验证</p><small>真实执行记录 · 按需刷新 · 异常保留</small></div>}
    <Card title={<LabTitle code="M" english="MISSION ARCHIVE">{total === null ? '任务存储未就绪' : `已记录任务 · ${total}`}</LabTitle>} extra={<Tag>只读监控</Tag>}>
      <PageState loading={list.loading} error={list.error} onRetry={list.refresh}>
        {list.data?.store_available === false ? <Empty description="尚未建立任务存储。通过工程工作台提交任务后，可在这里跟踪执行。" /> : <AgentTaskTable tasks={list.data?.tasks || []} onSelect={task => setSelected(task.task_id)} pagination={{ current: page, pageSize: 20, total: total ?? 0, onChange: setPage, showSizeChanger: false }} />}
      </PageState>
    </Card>
    <Drawer title={<LabTitle code="M" english="MISSION LOG">任务执行详情</LabTitle>} className={hyper ? 'hyper-lab-task-drawer' : anime ? 'lab-task-drawer' : undefined} size="large" open={Boolean(selected)} onClose={() => setSelected(null)}>
      <PageState loading={detail.loading} error={detail.error} onRetry={detail.refresh}>
        {!detail.loading && !detail.error && detail.data && <>
          {hyper && <div className="hyper-lab-detail-register">ENGINE TASK / <code>{detail.data.task_id}</code></div>}
          {anime && <div className="lab-detail-register">ENGINE TASK / <code>{detail.data.task_id}</code></div>}
          <Typography.Title level={4}>{detail.data.query || '工程任务'}</Typography.Title>
          <Descriptions column={{ xs: 1, sm: 2 }} size="small" items={[
            { key: 'state', label: '状态', children: <Tag color={taskStatus(detail.data.status).color}>{taskStatus(detail.data.status).label}</Tag> },
            { key: 'time', label: '更新时间', children: formatDate(detail.data.updated_at) },
            { key: 'parent', label: '父任务', children: detail.data.parent_task_id || '独立任务' },
          ]} />
          {detail.data.error && <Alert className="admin-section-alert" type="error" showIcon title="任务未成功完成" description={typeof detail.data.error === 'string' ? detail.data.error : detail.data.error.message || detail.data.error.code || '查看步骤中的异常记录。'} />}
          <Card title={<LabTitle code="01" english="MISSION PROGRESS">执行步骤</LabTitle>} size="small" className="admin-section-card"><Timeline items={(detail.data.steps || []).map((step, index) => ({
            color: ['failed', 'blocked'].includes(step.status) ? 'var(--ta-danger)' : step.status === 'completed' ? 'var(--ta-success)' : 'var(--ta-primary)',
            content: <div className={hyper ? 'hyper-lab-step' : anime ? 'lab-step-entry' : undefined} data-status={anime || hyper ? step.status : undefined}>{hyper && <span className="hyper-lab-step-index">PHASE {String(index + 1).padStart(2, '0')}{step.status === 'running' && <b>NOW EXECUTING</b>}</span>}{anime && <span className="lab-step-register">STEP {String(index + 1).padStart(2, '0')}{step.status === 'running' && <b> / NOW EXECUTING</b>}</span>}<Space wrap><strong>{step.title || step.step_id}</strong><Tag color={taskStatus(step.status).color}>{taskStatus(step.status).label}</Tag></Space>
              {step.tool_name && <p className="admin-step-meta">工具：{step.tool_name}{step.tool_version && ` · ${step.tool_version}`}</p>}
              <p className="admin-step-meta">{step.started_at ? formatDate(step.started_at) : '尚未开始'}{step.finished_at && ` → ${formatDate(step.finished_at)}`}</p>
              {step.error && <Alert type="error" title={typeof step.error === 'string' ? step.error : step.error.message || step.error.code || '步骤失败'} />}
              <JsonPreview label="查看步骤输入与输出" value={{ inputs: step.inputs, outputs: step.outputs, depends_on: step.depends_on }} />
            </div>,
          }))} /></Card>
          <Card title="中间变量" size="small" className="admin-section-card"><Table size="small" scroll={{ x: 540 }} rowKey={(row, index) => `${row.step_id}-${row.name}-${index}`} dataSource={detail.data.variables || []} pagination={{ pageSize: 8 }} columns={[
            { title: '变量', dataIndex: 'name' }, { title: '数值', dataIndex: 'value', render: value => typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—') },
            { title: '单位', dataIndex: 'unit', render: value => value || '未声明' }, { title: '来源', dataIndex: 'source' },
          ]} /></Card>
          <JsonPreview label="查看完整事件 Trace" value={detail.data.events || []} />
          {detail.data.result && <Card title="执行结果" size="small" className="admin-section-card">{anime || hyper ? <div className={hyper ? "hyper-lab-report" : "lab-report-content"}><MarkdownContent>{detail.data.result.answer || '结果已保存，请展开结构化记录。'}</MarkdownContent></div> : <Typography.Paragraph className="admin-chunk-text">{detail.data.result.answer || '结果已保存，请展开结构化记录。'}</Typography.Paragraph>}<JsonPreview label="查看结构化结果与来源" value={detail.data.result} /></Card>}
        </>}
      </PageState>
    </Drawer>
  </section>;
}

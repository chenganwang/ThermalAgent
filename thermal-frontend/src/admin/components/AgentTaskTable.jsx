import { Button, Empty, Pagination, Progress, Spin, Table, Tag, Typography } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';
import { formatDate } from '../presentation/adminPresentation.js';
import { taskProgress, taskStatus } from '../presentation/experience.js';
import { useAppTheme } from '../../theme/useAppTheme.js';

export default function AgentTaskTable({ tasks = [], onSelect, pagination = false, loading = false }) {
  const { themeId } = useAppTheme();
  if (themeId === 'hyper') return <Spin spinning={loading}><div>
    {tasks.length ? <ul className="hyper-lab-missions">{tasks.map(task => {
      const status = taskStatus(task.status);
      const progress = taskProgress(task);
      return <li className="hyper-lab-mission" data-status={task.status} key={task.task_id}>
        <div className="hyper-lab-mission-head"><span>ENGINEERING ARCHIVE<code title={task.task_id}>#{task.task_id?.slice(-8) || '—'}</code></span><Tag color={status.color}>{status.label}</Tag></div>
        <Button type="link" className="admin-task-query" onClick={() => onSelect(task)}>{task.query || '未记录问题摘要'}</Button>
        {progress.percent !== null && <Progress size="small" percent={progress.percent} showInfo={false} strokeColor="var(--ta-primary)" />}
        <div className="hyper-lab-mission-footer"><span>{progress.text}<time>{formatDate(task.updated_at)}</time></span><Button icon={<ArrowRightOutlined />} aria-label={`查看任务：${task.query || task.task_id}`} onClick={() => onSelect(task)}>档案</Button></div>
      </li>;
    })}</ul> : <Empty description="暂无工程任务记录" />}
    {pagination && <Pagination {...pagination} className="admin-pagination" />}
  </div></Spin>;
  if (themeId === 'cel') return <Spin spinning={loading}><div className="lab-mission-archive">
    {tasks.length ? <ul className="lab-mission-list">{tasks.map(task => {
      const status = taskStatus(task.status);
      const progress = taskProgress(task);
      return <li className="lab-mission-card" data-status={task.status} key={task.task_id}>
        <div className="lab-mission-index"><span>ENGINE TASK</span><code title={task.task_id}>#{task.task_id?.slice(-8) || '—'}</code></div>
        <div className="lab-mission-content"><Button type="link" className="admin-task-query" onClick={() => onSelect(task)}>{task.query || '未记录问题摘要'}</Button><div className="lab-mission-metadata"><Tag color={status.color}>{status.label}</Tag><span>{progress.text}</span><time>{formatDate(task.updated_at)}</time></div>{progress.percent !== null && <Progress size="small" percent={progress.percent} showInfo={false} strokeColor="var(--ta-primary)" />}</div>
        <Button className="lab-mission-open" icon={<ArrowRightOutlined />} aria-label={`查看任务：${task.query || task.task_id}`} onClick={() => onSelect(task)} />
      </li>;
    })}</ul> : <Empty description="暂无工程任务记录" />}
    {pagination && <Pagination {...pagination} className="admin-pagination" />}
  </div></Spin>;
  return <Table rowKey="task_id" dataSource={tasks} loading={loading} pagination={pagination} scroll={{ x: 650 }} size="small" columns={[
    { title: '工程任务', dataIndex: 'query', render: (query, task) => <Button type="link" className="admin-task-query" onClick={() => onSelect(task)}>{query || '未记录问题摘要'}</Button> },
    { title: '状态', dataIndex: 'status', width: 112, render: status => { const view = taskStatus(status); return <Tag color={view.color}>{view.label}</Tag>; } },
    { title: '执行进度', width: 170, render: (_, task) => { const view = taskProgress(task); return <div><Typography.Text type="secondary">{view.text}</Typography.Text>{view.percent !== null && <Progress size="small" percent={view.percent} showInfo={false} strokeColor="var(--ta-primary)" />}</div>; } },
    { title: '更新时间', dataIndex: 'updated_at', width: 170, render: formatDate },
  ]} />;
}

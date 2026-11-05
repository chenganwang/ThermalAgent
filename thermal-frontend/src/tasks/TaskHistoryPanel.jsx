import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Empty, Input, Popconfirm, Space, Spin } from 'antd';
import { cancelEngineeringTask, getEngineeringTask, getEngineeringTasks, retryEngineeringTask } from '../api/client.js';
import EngineeringRunCard from '../EngineeringRunCard.jsx';
import KnowledgeSourcesDisclosure from '../KnowledgeSourcesDisclosure.jsx';
import MarkdownContent from '../MarkdownContent.jsx';
import TaskProgressCard from './TaskProgressCard.jsx';
import { acceptTaskSnapshot, canRetryTask, isTerminalTask, taskConnectionError, taskStatusLabel } from './taskState.js';

export default function TaskHistoryPanel({ active, initialTaskId, useMockResponses }) {
  const [tasks, setTasks] = useState([]);
  const [selectedId, setSelectedId] = useState(initialTaskId || null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [revisionQuery, setRevisionQuery] = useState('');
  const operation = useRef(false);
  const epoch = useRef(0);
  useEffect(() => { if (active && initialTaskId) setSelectedId(initialTaskId); }, [active, initialTaskId]);
  useEffect(() => {
    if (!active || useMockResponses) return undefined;
    const controller = new AbortController();
    setLoading(true);
    getEngineeringTasks({ offset }, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) { setTasks(data.tasks || []); setTotal(data.total || 0); }
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.statusCode === 404 ? '当前后端尚未提供工程任务历史；普通问答仍可使用。' : taskConnectionError(failure)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [active, useMockResponses, refresh, offset]);
  useEffect(() => {
    const generation = ++epoch.current;
    setSelected(null); setRevisionQuery(''); setError('');
    if (!active || !selectedId || useMockResponses) return undefined;
    const controller = new AbortController();
    let timer;
    let previous = null;
    const read = async () => {
      try {
        const next = await getEngineeringTask(selectedId, { signal: controller.signal });
        if (controller.signal.aborted || generation !== epoch.current) return;
        previous = acceptTaskSnapshot(previous, next, { taskId: selectedId });
        setSelected(previous);
        if (!isTerminalTask(previous)) timer = setTimeout(read, 1500);
      } catch (failure) { if (!controller.signal.aborted && generation === epoch.current) setError(taskConnectionError(failure, selectedId)); }
    };
    read();
    return () => { controller.abort(); clearTimeout(timer); epoch.current = generation + 1; };
  }, [active, selectedId, useMockResponses, refresh]);
  const act = async kind => {
    if (operation.current || !selected) return;
    operation.current = true; setBusy(true); setError('');
    const generation = epoch.current;
    try {
      const response = kind === 'retry'
        ? await retryEngineeringTask(selected.task_id, { revision: selected.revision, query: revisionQuery })
        : await cancelEngineeringTask(selected.task_id, selected.revision);
      if (generation === epoch.current) { if (response.task_id) setSelectedId(response.task_id); setRefresh(value => value + 1); }
    } catch (failure) { if (generation === epoch.current) setError(taskConnectionError(failure, selected.task_id)); }
    finally { operation.current = false; setBusy(false); }
  };
  if (useMockResponses) return <Alert type="info" title="前端离线示例模式不连接任务服务，也不生成虚构执行进度。" />;
  return <div className="ta-task-history" data-testid="engineering-task-history">
    <div className="ta-history-toolbar"><div><h2>任务记录</h2><p className="ta-muted">重新读取服务保存的计划、事件、参数与结果。</p></div><Button disabled={busy} onClick={() => setRefresh(value => value + 1)}>刷新任务</Button></div>
    {error && <Alert type="warning" showIcon title={error} />}
    <div className="ta-history-layout"><nav className="ta-task-list" aria-label="历史工程任务">
      {loading && <Spin size="small" />}{tasks.map(task => <button type="button" className={selectedId === task.task_id ? 'active' : ''} key={task.task_id} disabled={busy} onClick={() => setSelectedId(task.task_id)}><strong>{task.query || task.task_id}</strong><span>{taskStatusLabel(task.status)} · {task.created_at ? new Date(task.created_at).toLocaleString() : '时间未记录'}</span></button>)}
      {!tasks.length && !loading && <Empty description="暂无工程任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      <Space><Button disabled={offset === 0 || busy} onClick={() => setOffset(value => Math.max(0, value - 20))}>上一页</Button><Button disabled={offset + 20 >= total || busy} onClick={() => setOffset(value => value + 20)}>下一页</Button></Space>
    </nav><div className="ta-task-detail">{selected ? <>
      <TaskProgressCard task={selected} />
      {selected.parent_task_id && <p className="ta-muted">关联原任务：<code>{selected.parent_task_id}</code></p>}
      {canRetryTask(selected) && <div className="ta-task-retry"><h3>补充条件后重新执行</h3><p>填写完整修订问题；留空使用已保存输入。确认后新建关联任务，保留原记录。</p><Input.TextArea aria-label="修订工程问题" value={revisionQuery} onChange={event => setRevisionQuery(event.target.value)} disabled={busy} rows={3} placeholder="补充缺失参数，或修订完整的工程问题…" /><Popconfirm title="确认新建关联任务？" description="只在你确认后提交一次，不自动重试。" onConfirm={() => act('retry')} okText="确认修订重试" cancelText="取消"><Button type="primary" disabled={busy}>修订并重试</Button></Popconfirm></div>}
      {!isTerminalTask(selected) && <Popconfirm title="请求在安全步骤边界取消？" description="已完成的计算与证据会保留；只有服务回执确认后才视为取消。" onConfirm={() => act('cancel')} okText="请求取消" cancelText="继续执行"><Button disabled={busy}>请求取消任务</Button></Popconfirm>}
      {selected.result && <section className="ta-task-result"><h3>执行结果</h3><MarkdownContent>{selected.result.answer || '任务已有响应，见下方执行证据。'}</MarkdownContent><EngineeringRunCard response={selected.result} /><KnowledgeSourcesDisclosure sources={selected.result.sources} />{selected.result.metadata?.report?.content && <details><summary>查看工程报告</summary><MarkdownContent>{selected.result.metadata.report.content}</MarkdownContent></details>}</section>}
    </> : <p className="ta-muted">选择任务查看详情；历史内容以服务记录为准。</p>}</div></div>
  </div>;
}

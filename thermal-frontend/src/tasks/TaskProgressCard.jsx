import { useState } from 'react';
import { Alert, Tag } from 'antd';
import { engineeringValue } from '../engineeringRunPresentation.js';
import { isTerminalTask, orderedTaskEvents, taskStatusLabel } from './taskState.js';
import TaskDependencyGraph from './TaskDependencyGraph.jsx';
import { useAppTheme } from '../theme/useAppTheme.js';
import MissionBoard from './MissionBoard.jsx';
import HyperMissionBoard from './HyperMissionBoard.jsx';

function StepData({ value }) {
  if (value === null || value === undefined || (typeof value === 'object' && !Object.keys(value).length)) return <span className="ta-muted">尚无记录</span>;
  return <pre className="ta-step-json">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>;
}

export default function TaskProgressCard({ task, compact = false, onOpen }) {
  const [selectedId, setSelectedId] = useState(null);
  const { themeId } = useAppTheme();
  if (!task) return null;
  const steps = Array.isArray(task.steps) ? task.steps : [];
  const current = steps.find(step => step.status === 'running');
  const selected = steps.find(step => step.step_id === selectedId) || current || steps.find(step => ['blocked', 'failed'].includes(step.status)) || steps.at(-1);
  const events = orderedTaskEvents(task.events);
  const completed = steps.filter(step => step.status === 'completed').length;
  const status = taskStatusLabel(task.status);
  const isAnime = themeId === 'cel';
  const isHyper = themeId === 'hyper';
  return <section className={`ta-task-card${compact ? ' compact' : ''}${isAnime ? ' ta-mission-card' : ''}${isHyper ? ' ta-hyper-task-card' : ''}`} data-testid="task-progress-card" aria-label="实际工程任务进度">
    {isHyper ? <HyperMissionBoard task={task} steps={steps} selectedId={selected?.step_id} onSelect={setSelectedId} compact={compact} /> : isAnime ? <MissionBoard task={task} steps={steps} current={current} selectedId={selected?.step_id} onSelect={setSelectedId} compact={compact} /> : <>
    <div className="ta-task-heading"><strong>{compact ? '当前执行' : '工程任务执行记录'}</strong><Tag color={task.status === 'completed' ? 'success' : ['failed', 'interrupted'].includes(task.status) ? 'error' : task.status === 'blocked' ? 'warning' : 'processing'}>{status}</Tag></div>
    <p className="ta-task-query">{task.query || '已提交的工程任务'}</p>
    <p className="ta-muted ta-task-truth" role="status">{current ? `正在执行：${current.title}` : status} · 已完成 {completed}/{steps.length} 个已声明步骤</p>
    {!compact && <TaskDependencyGraph steps={steps} />}
    <ol className="ta-task-steps">{steps.map((step, index) => <li key={step.step_id || index} data-status={step.status}>
      <button type="button" onClick={() => setSelectedId(step.step_id)} aria-pressed={selected?.step_id === step.step_id}>
        <span className="ta-step-number" aria-hidden="true">{step.status === 'completed' ? '✓' : index + 1}</span><span><strong>{step.title || step.step_id}</strong><small>{taskStatusLabel(step.status)}</small></span>
      </button>
      {!compact && (step.depends_on || []).length > 0 && <span className="ta-step-dependency">依赖：{step.depends_on.map(id => steps.find(item => item.step_id === id)?.title || id).join('、')}</span>}
    </li>)}</ol>
    {steps.length === 0 && <p className="ta-muted">等待服务记录计划；尚未声明工具执行。</p>}
    </>}
    {task.error && <Alert type="error" title={task.error.message || '任务执行异常'} description={task.error.code} />}
    {!compact && task.validation && <Alert type={task.validation.status === 'passed' && task.validation.passed === true ? 'success' : task.validation.status === 'failed' ? 'error' : 'warning'} title={task.validation.status === 'passed' && task.validation.passed === true ? '已通过已配置物理检查' : task.validation.status === 'failed' ? '物理检查未通过' : '物理校验证据尚不完整'} description={(task.validation.issues || []).map(issue => issue.message).filter(Boolean).join('；') || '检查针对显式输入与配置约束；不等同独立实验或 CFD 验证。'} />}
    {!compact && selected && <details className="ta-step-details" open={!isHyper}><summary>{selected.title || selected.step_id} · 输入与输出</summary>
      <div className="ta-muted">工具：{selected.tool_name || '未声明'} · 版本：{selected.tool_version || '未声明'}</div>
      <div className="ta-step-data"><div><h4>输入 / 来源</h4><StepData value={selected.inputs} /></div><div><h4>输出</h4><StepData value={selected.outputs} /></div></div>
    </details>}
    {!compact && (task.variables || []).length > 0 && <details className="ta-step-details"><summary>中间变量与单位（{task.variables.length}）</summary><div className="ta-table-scroll"><table className="ta-data-table"><thead><tr><th>变量</th><th>值</th><th>单位</th><th>来源</th></tr></thead><tbody>{task.variables.map((variable, index) => <tr key={index}><td>{variable.name}</td><td>{engineeringValue(variable.value)}</td><td>{variable.unit || '未声明'}</td><td>{variable.source || variable.step_id || '未记录'}</td></tr>)}</tbody></table></div></details>}
    <details className="ta-step-details"><summary>真实事件时间线（{events.length}）</summary><ol className="ta-task-events">{events.map(event => <li key={event.sequence}><time>{event.at ? new Date(event.at).toLocaleTimeString() : '未记录时间'}</time> <strong>{event.title || event.step_id}</strong> · {taskStatusLabel(event.status)}{event.detail && <div>{engineeringValue(event.detail)}</div>}</li>)}</ol>{events.length === 0 && <p>尚无事件；不会显示估算进度。</p>}</details>
    <div className="ta-task-footer"><code title={task.task_id}>{task.task_id}</code>{onOpen && <button className="ta-link-button" onClick={() => onOpen(task.task_id)}>查看详情</button>}</div>
    {!compact && (task.limitations || []).length > 0 && <details className="ta-step-details"><summary>适用范围与限制</summary><ul>{task.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}
    {!isTerminalTask(task) && <small className="ta-muted">按服务实际记录刷新，不估算完成百分比。</small>}
  </section>;
}

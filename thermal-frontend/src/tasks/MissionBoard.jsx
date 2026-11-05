import { taskStatusLabel } from './taskState.js';
import TaskDependencyGraph from './TaskDependencyGraph.jsx';
import './mission.css';

const STATUS_EN = {
  queued: 'QUEUED', planned: 'PLANNED', pending: 'STANDBY', running: 'IN PROGRESS', cancelling: 'CANCEL REQUESTED',
  completed: 'COMPLETED', blocked: 'INPUT REQUIRED', failed: 'FAILED', incomplete: 'EVIDENCE INCOMPLETE',
  cancelled: 'CANCELLED', interrupted: 'INTERRUPTED', skipped: 'SKIPPED',
};
const MARKS = { completed: '✓', running: '▶', failed: '!', blocked: '?', incomplete: '!', cancelled: '×', interrupted: '!', skipped: '–' };

function missionReference(taskId) {
  return typeof taskId === 'string' && taskId ? taskId.split('_').at(-1).slice(-8).toUpperCase() : 'UNASSIGNED';
}

export default function MissionBoard({ task, steps, current, selectedId, onSelect, compact }) {
  const completed = steps.filter(step => step.status === 'completed').length;
  const status = taskStatusLabel(task.status);
  return <div className="ta-mission-board" data-testid="mission-board" data-mission-status={task.status}>
    <header className="ta-mission-head">
      <div className="ta-mission-overline"><span>MISSION <b>/ ENGINEERING TASK</b></span><span title={task.task_id}>#{missionReference(task.task_id)}</span></div>
      <div className="ta-mission-heading"><h3>{compact ? '任务推进面板' : '工程任务档案'}</h3><span className="ta-mission-insignia" aria-hidden="true">TA</span></div>
      <p className="ta-task-query">{task.query || '已提交的工程任务'}</p>
      <div className="ta-mission-status" role="status"><span>STATUS : <strong>{STATUS_EN[task.status] || 'UNCONFIRMED'}</strong></span><span>{status}</span></div>
    </header>
    <div className="ta-mission-current" data-status={current?.status || task.status}>
      <span className="ta-mission-signal" aria-hidden="true" /><div><small>{current ? 'ACTIVE CHAPTER' : 'MISSION RECORD'}</small><strong>{current ? current.title || current.step_id : status}</strong></div>
      <span className="ta-mission-tally" aria-label={`已完成 ${completed}/${steps.length} 个已声明步骤`}><b>{String(completed).padStart(2, '0')}</b><span>/ {String(steps.length).padStart(2, '0')}<small>已声明步骤</small></span></span>
    </div>
    <div className="ta-mission-ledger-title"><span>任务日志 <b>/ CHAPTER LOG</b></span><small>按服务计划排列</small></div>
    <ol className="ta-mission-chapters">{steps.map((step, index) => <li key={step.step_id || index} data-status={step.status}>
      <button type="button" className="ta-mission-chapter" onClick={() => onSelect(step.step_id)} aria-pressed={selectedId === step.step_id}>
        <span className="ta-mission-chapter-number" aria-hidden="true"><small>CH.</small>{String(index + 1).padStart(2, '0')}</span>
        <span className="ta-mission-chapter-copy"><span className="ta-mission-chapter-title">{step.title || step.step_id}</span>
          <span className="ta-mission-chapter-meta">{step.tool_name ? <><b>TOOL</b> <code>{step.tool_name}</code></> : <><b>STEP</b> <code>{step.step_id || '未记录编号'}</code></>}</span>
          <span className="ta-mission-chapter-state">{taskStatusLabel(step.status)} <span>/ {STATUS_EN[step.status] || 'UNCONFIRMED'}</span></span>
        </span>
        <span className="ta-mission-chapter-mark" aria-hidden="true">{MARKS[step.status] || '·'}</span>
      </button>
      {!compact && (step.depends_on || []).length > 0 && <p className="ta-mission-dependency">依赖：{step.depends_on.map(id => steps.find(item => item.step_id === id)?.title || id).join('、')}</p>}
    </li>)}</ol>
    {steps.length === 0 && <p className="ta-mission-awaiting">等待服务记录计划；尚未声明工具执行。</p>}
    {!compact && <details className="ta-step-details ta-mission-dependencies"><summary>依赖关系 / DEPENDENCY MAP</summary><TaskDependencyGraph steps={steps} /></details>}
    {task.status === 'completed' && <p className="ta-mission-complete-stamp" data-testid="mission-completed-stamp"><span aria-hidden="true">✓</span> MISSION COMPLETED <small>服务已记录完成</small></p>}
  </div>;
}

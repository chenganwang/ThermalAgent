import { engineeringValue } from '../engineeringRunPresentation.js';
import { taskStatusLabel } from './taskState.js';
import TaskDependencyGraph from './TaskDependencyGraph.jsx';
import { designReviewStatus, hyperMissionReference, hyperMissionState, HYPER_MARK, HYPER_STATUS } from './hyperMissionState.js';
import './hyperMission.css';

function JournalMark() {
  return <svg className="ta-hyper-journal-mark" viewBox="0 0 64 72" aria-hidden="true"><path d="M32 10v51M12 19c9-3 15-1 20 3 5-4 11-6 20-3v36c-8-2-14-1-20 4-6-5-12-6-20-4Z" /><path d="M19 28c4-1 7 0 9 2m-9 7c4-1 7 0 9 2m8-9c3-2 6-3 9-2m-9 11c3-2 6-3 9-2M26 9l6-6 6 6-6 6Z" /><path className="ta-hyper-journal-petal" d="M49 6c8 3 11 9 7 15-7-2-10-8-7-15Z" /></svg>;
}

function OutcomeNote({ state }) {
  const note = {
    design_failed: ['计算已完成，设计指标未通过', '物理检查已通过，但实际计算超出设计上限。原始结果已保留，可调整约束或参数后新建关联任务。'],
    incomplete: ['仍有待补全的篇章', '部分证据尚不完整。计算记录可以查阅，工程结论仍需补充依据。'],
    blocked: ['这一页，等待你的补充', '任务尚未满足执行条件。请在记录中核对缺失参数或前置步骤。'],
    failed: ['先核对，再继续', '本次执行遇到异常。保留已有记录，核对错误后再发起任务。'],
    interrupted: ['手记停在了这里', '执行已中断；请核对任务档案中的实际状态和已有结果。'],
    cancelled: ['本次手记已暂停', '任务已取消。下方仍保留本次执行中实际生成的记录。'],
  }[state.status];
  if (!note) return null;
  return <aside className="ta-hyper-outcome-note" data-outcome={state.status}>
    <span aria-hidden="true">◇</span><div><strong>{note[0]}</strong><p>{note[1]}</p></div>
  </aside>;
}

function DesignReview({ review, compact }) {
  if (!review || !Array.isArray(review.checks)) return null;
  return <details className="ta-hyper-design-review" open={!compact} data-testid="hyper-design-review" data-review-status={review.status}>
    <summary><span>设计指标 <small>/ DESIGN CHECK</small></span><strong>{designReviewStatus(review.status)}</strong></summary>
    <p>设计上限与物理一致性分别记录；数值和结论均来自本次任务。</p>
    <div className="ta-table-scroll"><table><caption>已声明的设计上限与实际工具输出</caption><thead><tr><th>指标 / 来源</th><th>实际值</th><th>上限</th><th>单位</th><th>结果</th></tr></thead>
      <tbody>{review.checks.map((check, index) => <tr key={check.criterion || index} data-check-status={check.status}>
        <th scope="row">{check.label || check.metric || '未命名指标'}<small>{check.source || '来源未记录'}</small></th>
        <td>{engineeringValue(check.actual)}</td><td>{engineeringValue(check.maximum)}</td><td>{check.unit || '未声明'}</td><td>{designReviewStatus(check.status)}</td>
      </tr>)}</tbody></table></div>
    {review.checks.length === 0 && <p>尚未记录可核对的指标。</p>}
    <small className="ta-hyper-review-version">检查器：{review.reviewer_version || '版本未记录'}</small>
    {(review.limitations || []).length > 0 && <ul>{review.limitations.map((line, index) => <li key={index}>{line}</li>)}</ul>}
  </details>;
}

export default function HyperMissionBoard({ task, steps, selectedId, onSelect, compact }) {
  const state = hyperMissionState(task, steps);
  const designStepFailed = step => step.step_id === 'design_review' && step.status === 'incomplete' && task.design_review?.status === 'violated';
  return <div className="ta-hyper-mission-board" data-testid="hyper-mission-board" data-mission-status={state.status} data-compact={compact ? 'true' : 'false'}>
    <header className="ta-hyper-mission-head">
      <div className="ta-hyper-mission-overline"><span>ELYSIAN ATELIER</span><code title={task.task_id}>NO. {hyperMissionReference(task.task_id)}</code></div>
      <div className="ta-hyper-mission-title"><div><small>MISSION JOURNAL</small><h3>{compact ? '任务手记' : '工程任务卷宗'}</h3></div><JournalMark /></div>
      <p className="ta-task-query">{task.query || '已提交的工程任务'}</p>
      <div className="ta-hyper-mission-status" role="status"><span className="ta-hyper-status-mark" aria-hidden="true">{state.complete ? '✓' : HYPER_MARK[state.status] || '◇'}</span><strong>{state.english}</strong><span>{state.label}</span></div>
    </header>
    <div className="ta-hyper-mission-current" data-status={state.current?.status || state.status}>
      <span className="ta-hyper-current-beacon" aria-hidden="true" />
      <div className="ta-hyper-current-copy"><small>{state.current ? 'CURRENT CHAPTER' : 'JOURNAL RECORD'}</small><strong>{state.current ? state.current.title || state.current.step_id : state.label}</strong>
        {state.current?.tool_name && <code>TOOL CALL · {state.current.tool_name}</code>}</div>
      <div className="ta-hyper-mission-tally" aria-label={`已完成 ${state.completed}/${steps.length} 个已声明步骤`}><b>{String(state.completed).padStart(2, '0')}</b><span>/ {String(steps.length).padStart(2, '0')}<small>已完成步骤</small></span></div>
    </div>
    <details className="ta-hyper-chapters" open={!compact || Boolean(state.current)}>
    <summary>执行篇章 / CHAPTERS <span>{state.completed}/{steps.length}</span></summary>
    <div className="ta-hyper-objectives-heading"><h4>执行篇章 <small>/ CHAPTERS</small></h4><span>{compact ? '服务实际记录' : '轻点查看输入与输出'}</span></div>
    <ol className="ta-hyper-objectives">{steps.map((step, index) => <li key={step.step_id || index} data-status={step.status}>
      <button className="ta-hyper-objective" type="button" onClick={() => onSelect(step.step_id)} aria-pressed={selectedId === step.step_id} aria-current={step.status === 'running' ? 'step' : undefined}>
        <span className="ta-hyper-objective-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
        <span className="ta-hyper-objective-copy"><strong>{step.title || step.step_id}</strong><span className="ta-hyper-objective-state">{designStepFailed(step) ? '未满足设计指标' : taskStatusLabel(step.status)} <small>/ {designStepFailed(step) ? HYPER_STATUS.design_failed : HYPER_STATUS[step.status] || 'UNCONFIRMED'}</small></span></span>
        <span className="ta-hyper-objective-mark" aria-hidden="true">{HYPER_MARK[step.status] || '·'}</span>
        {step.tool_name && <span className="ta-hyper-objective-tool"><b>{step.status === 'running' ? 'TOOL CALL' : step.status === 'completed' ? 'TOOL RECORD' : 'DECLARED TOOL'}</b><code>{step.tool_name}</code><span className="ta-hyper-tool-version">版本 · {step.tool_version || '未声明'}</span></span>}
      </button>
      {(step.depends_on || []).length > 0 && <p className="ta-hyper-objective-dependencies"><b>REQUIRES</b><span>{step.depends_on.map(id => steps.find(item => item.step_id === id)?.title || id).join(' / ')}</span></p>}
    </li>)}</ol>
    </details>
    {steps.length === 0 && <p className="ta-hyper-awaiting">等待服务记录计划；尚未声明工具执行。</p>}
    {state.inconsistent && <p className="ta-hyper-record-warning" role="status">任务完成标记与步骤或检查记录不一致，请核对下方 Trace；暂不标记任务完成。</p>}
    {!compact && <details className="ta-step-details ta-hyper-dependency-map"><summary>依赖关系 <small>/ DEPENDENCY MAP</small></summary><TaskDependencyGraph steps={steps} /></details>}
    <DesignReview review={task.design_review} compact={compact} />
    <OutcomeNote state={state} />
    {state.complete && <div className="ta-hyper-mission-complete" data-testid="hyper-mission-complete"><span aria-hidden="true">✧</span><div><small>这一页，已经写就</small><strong>MISSION COMPLETE</strong><p>任务已记录完成。展开结果与工程报告，核对本次计算与依据。</p></div><b aria-hidden="true">✓</b></div>}
  </div>;
}

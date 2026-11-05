import { engineeringResult, resultNumber } from './engineeringResult.js';
import './hyperFocus.css';

const STATUS = { pass: ['✓ PASS', '通过'], fail: ['✕ FAIL', '未通过'], unknown: ['待确认', '证据未确认'], unset: ['未声明', '未设置设计指标'] };

export default function EngineeringResultSummary({ task, response, onOpenTask }) {
  const view = engineeringResult({ task, response });
  if (!view) return null;
  return <section className="ta-engineering-result" data-testid="engineering-result-summary" aria-label="工程结果与验证结论">
    <header><span>ENGINEERING RESULT <small>/ 工程结论</small></span>{view.taskId && onOpenTask && <button type="button" onClick={() => onOpenTask(view.taskId)}>打开任务记录 ↗</button>}</header>
    <div className="ta-result-grid">
      <div className="ta-result-number"><span>{view.primary.label}</span><strong title={String(view.primary.value)}>{resultNumber(view.primary.value)} <small>{view.primary.unit}</small></strong>{view.secondary && <span title={String(view.secondary.value)}>{view.secondary.label} <b>{new Intl.NumberFormat('en-US', { maximumSignificantDigits: 6 }).format(view.secondary.value)} {view.secondary.unit}</b></span>}</div>
      <div className="ta-result-status" data-status={view.physics}><span>PHYSICS / 物理验证</span><strong>{STATUS[view.physics][0]}</strong><small>已配置物理规则</small></div>
      <div className="ta-result-status" data-status={view.design}><span>DESIGN LIMIT / 设计指标</span><strong>{STATUS[view.design][0]}</strong>{view.checks.length > 0 ? view.checks.map((check, index) => <small key={check.criterion || index} data-status={check.status} title={`${check.label || check.metric}：${resultNumber(check.actual)} ${check.unit || ''}`}>{check.label || check.metric} ≤ {resultNumber(check.maximum)} {check.unit || ''}</small>) : <small>{STATUS[view.design][1]}</small>}</div>
      <div className="ta-result-status" data-status={view.evidence === 'complete' ? 'pass' : 'unknown'}><span>EVIDENCE / 工程证据</span><strong>{view.evidence === 'complete' ? '✓ 完整' : '待补全'}</strong><small>来源 · 校验 · 报告回执</small></div>
    </div>
    {view.risks.length > 0 && <div className="ta-result-risks" role="status">{view.risks.map(risk => <p key={risk}>{risk}</p>)}</div>}
    {view.parentTaskId && <p className="ta-result-lineage">关联复评 · 原任务已保留 {onOpenTask ? <button type="button" onClick={() => onOpenTask(view.parentTaskId)}>{view.parentTaskId} ↗</button> : <code>{view.parentTaskId}</code>}</p>}
    <p className="ta-result-scope">数值来自本次实际计算。规则通过仅适用于已声明模型与输入，不等同实验或 CFD 验证。</p>
  </section>;
}

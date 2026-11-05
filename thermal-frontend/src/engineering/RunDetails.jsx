import { Alert, Button, Card, Popconfirm, Space, Tag, Typography } from 'antd';
import EngineeringRunCard from '../EngineeringRunCard.jsx';
import HistoryChart from '../HistoryChart.jsx';
import { canResumeRun, runStatus } from './engineeringHistory.js';
import { assertRunIdentity, RESULT_IDENTITY_MESSAGE } from '../resultIdentity.js';

export default function RunDetails({ run, busy = false, onResume, onDownload }) {
  if (!run) return null;
  try { assertRunIdentity(run); } catch { return <Alert type="error" title={RESULT_IDENTITY_MESSAGE} />; }
  const reference = run.calculation_result?.reference_solver;
  // A detail returned from the persistent store proves this checkpoint exists,
  // even though the stored receipt predates the immediate-response save status.
  const receipt = run.receipt ? { ...run.receipt, model_version: run.receipt.model_version || run.model_version, project_id: run.receipt.project_id || run.project_id, persistence: { enabled: true, saved: true, run_id: run.run_id, project_id: run.project_id, revision: run.revision, report_sha256: run.report_sha256 } } : null;
  return <Card title="工程运行详情" size="small" data-testid="engineering-run-details">
    <Space wrap><Tag>{runStatus(run.status)}</Tag><Typography.Text code>{run.run_id}</Typography.Text></Space>
    <div style={{ marginTop: 8 }}>创建：{run.created_at || '未记录'} · 版本：{run.revision ?? '未记录'}</div>
    {run.parent_run_id && <div>来源运行：{run.parent_run_id}</div>}
    {run.resumed_by && <div>关联重算：{run.resumed_by}</div>}
    <EngineeringRunCard response={{ metadata: { engineering_run: receipt } }} />
    <details style={{ margin: '12px 0' }}><summary>执行时间线</summary>
      {(run.receipt?.events || []).length ? <ol>{run.receipt.events.map((event, index) => <li key={index}>{event.at || '时间未记录'} · {event.step_id || '步骤未记录'} · {runStatus(event.status)}</li>)}</ol> : <p>未记录事件。</p>}
    </details>
    {reference && <>
      <Alert type="info" title={reference.is_mock ? 'Mock 演示数据，不能用于真实工程结论' : '确定性一维参考计算；没有执行 CFD'} />
      {(reference.histories || []).map((history, index) => <HistoryChart key={index} history={history} isMock={reference.is_mock === true} />)}
    </>}
    <Space wrap style={{ marginTop: 12 }}>{(run.artifacts || []).map(artifact => <Button key={artifact.artifact_id} disabled={busy} onClick={() => onDownload(run, artifact)}>下载{artifact.kind === 'report' ? '报告' : '记录'}工件</Button>)}</Space>
    {(run.artifacts || []).length > 0 && <details style={{ marginTop: 12 }}><summary>工件 SHA-256</summary>{run.artifacts.map(artifact => <p key={artifact.artifact_id} style={{ overflowWrap: 'anywhere' }}>{artifact.kind}：{artifact.sha256 || '未记录'}</p>)}</details>}
    {canResumeRun(run) && <div style={{ marginTop: 16 }}>
      <Alert type="warning" title="恢复将用已保存的固定输入新建关联计算，保留原记录；不是从任意中间步骤续跑。" />
      <Popconfirm title="确认使用固定输入重新计算？" description="只重执行已支持的确定性工具，不启动 Fluent。" okText="确认重新计算" cancelText="取消" onConfirm={() => onResume(run)} disabled={busy}>
        <Button disabled={busy} style={{ marginTop: 8 }}>恢复为关联重算</Button>
      </Popconfirm>
    </div>}
  </Card>;
}

import { Alert, Button, Descriptions, Tag, Typography } from 'antd';
import { engineeringRunPresentation } from './engineeringRunPresentation.js';

export default function EngineeringRunCard({ response }) {
  const view = engineeringRunPresentation(response);
  if (!view) return null;
  const { record } = view;
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: 'application/json;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `engineering-run-${(record.run_id || 'record').replace(/[^a-zA-Z0-9_-]/g, '_')}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <>
    {view.persistence.failed && <Alert type="warning" showIcon title="执行记录未完整保存" description={record.persistence.message || '计算结果仍可查看，请检查本地存储；刷新后可能无法找回本次完整记录。'} style={{ marginTop: 12 }} data-testid="engineering-persistence-warning" />}
    <details data-testid="engineering-run-card" style={{ marginTop: 12, border: '1px solid rgba(79,195,247,.2)', borderRadius: 8, padding: 12, textAlign: 'left' }}>
      <summary style={{ cursor: 'pointer' }}>工程执行记录 <Tag color={view.status.color}>{view.status.label}</Tag></summary>
      <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>记录本次确定性计算的步骤、变量和检查证据，供复核与复现。</Typography.Paragraph>
      <Descriptions size="small" column={1} items={[
        { key: 'tool', label: '计算工具', children: record.tool_name || '未记录' },
        { key: 'version', label: '工具版本', children: record.tool_version || '未记录' },
        ...(record.model_version ? [{ key: 'model', label: '模型版本', children: record.model_version }] : []),
        ...(record.project_id ? [{ key: 'project', label: '项目', children: record.project_id }] : []),
        { key: 'persistence', label: '执行记录保存', children: view.persistence.label },
        { key: 'report', label: '报告生成', children: record.report.generated ? '已生成' : '未生成' },
      ]} />
      <details style={{ marginTop: 12 }}><summary>问题与计算依据</summary>
        <Typography.Paragraph style={{ marginTop: 8 }}>{record.problem.description || '未记录问题描述'}</Typography.Paragraph>
        {record.formula && <Typography.Paragraph>公式：<code>{record.formula}</code></Typography.Paragraph>}
        {record.problem.required_parameters.length > 0 && <div>所需参数：{record.problem.required_parameters.join('、')}</div>}
        {record.problem.missing_parameters.length > 0 && <Alert type="warning" title={`缺少参数：${record.problem.missing_parameters.join('、')}`} style={{ marginTop: 8 }} />}
        {record.problem.assumptions.length > 0 && <div style={{ marginTop: 8 }}>计算假设：<ul>{record.problem.assumptions.map((assumption, index) => <li key={index}>{assumption}</li>)}</ul></div>}
      </details>
      <h4>计划与执行步骤</h4>
      {view.steps.length ? <ol>{view.steps.map((step, index) => <li key={step.step_id || index} style={{ marginBottom: 8 }}>
        {step.title || step.step_id || '未命名步骤'} <Tag>{step.statusLabel}</Tag>
        {step.depends_on.length > 0 && <div style={{ fontSize: 12 }}>依赖步骤：{step.depends_on.join('、')}</div>}
        {step.error && <Alert type="error" title={step.error} />}
      </li>)}</ol> : <Typography.Paragraph type="secondary">未提供步骤记录。</Typography.Paragraph>}
      {view.variables.length > 0 ? <div style={{ overflowX: 'auto' }}><table aria-label="输入输出变量" style={{ width: '100%', minWidth: 420, borderCollapse: 'collapse', fontSize: 13 }}>
        <thead><tr>{['类型', '变量', '数值', '单位'].map(label => <th key={label} scope="col" style={{ padding: 8, borderBottom: '1px solid rgba(127,127,127,.35)' }}>{label}</th>)}</tr></thead>
        <tbody>{view.variables.map(variable => <tr key={variable.key}>{[variable.roleLabel, variable.name || '未命名', variable.display, variable.unit || '未提供'].map((value, index) => <td key={index} style={{ padding: 8, verticalAlign: 'top', borderBottom: '1px solid rgba(127,127,127,.2)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{value}</td>)}</tr>)}</tbody>
      </table></div> : <Typography.Paragraph type="secondary">未提供输入输出变量</Typography.Paragraph>}
      <Alert showIcon type={view.validation.type} title={view.validation.label} description="该状态仅对应已配置规则，不等同于独立仿真或实验验证。" style={{ marginTop: 12 }} />
      {view.validation.checks.map((check, index) => <div key={index} style={{ marginTop: 8 }}>{check.name || '检查项'}：{check.message || '未提供检查说明'}</div>)}
      {view.validation.issues.map((issue, index) => <Alert key={index} type="error" showIcon title={issue.message || '物理规则校验存在问题'} description={[issue.field && `字段：${issue.field}`, issue.code && `代码：${issue.code}`].filter(Boolean).join(' · ')} style={{ marginTop: 8 }} />)}
      {record.evidence.length > 0 && <div style={{ marginTop: 12 }}><strong>依据与来源</strong><ul>{record.evidence.map((item, index) => <li key={index}>{item.type === 'formula' ? <><code>{item.formula || '未提供公式'}</code>{item.source && <div>来源：{item.source}</div>}</> : <>{item.title || '未命名资料'}{item.page_start !== null ? ` · 第 ${item.page_start}${item.page_end !== null && item.page_end !== item.page_start ? `–${item.page_end}` : ''} 页` : ''}</>}</li>)}</ul></div>}
      {view.limitations.length > 0 && <div style={{ marginTop: 12 }}><strong>适用范围与限制</strong><ul>{view.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
      <details style={{ margin: '12px 0' }}><summary>复现标识</summary><div>记录编号：{record.run_id || '未记录'}</div><Typography.Paragraph style={{ wordBreak: 'break-all', marginTop: 8 }}>输入指纹：{record.input_fingerprint || '未记录'}</Typography.Paragraph>{record.report.content_sha256 && <div style={{ wordBreak: 'break-all' }}>报告指纹：{record.report.content_sha256}</div>}</details>
      <Button onClick={download}>下载执行记录 (.json)</Button>
    </details>
    </>
  );
}

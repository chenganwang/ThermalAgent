import HistoryChart from '../HistoryChart.jsx';
import { Alert, Button, Card, Descriptions, Space, Table, Tag, Typography } from 'antd';
import { canRunFluentJob, cfdProvenance, fluentJobStatus, fluentMetric, fluentValidation } from './fluentPresentation.js';

export default function FluentJobDetails({ job, status, busy, useMockResponses, onRun, onDownload }) {
  if (!job) return null;
  const presentation = fluentJobStatus(job.status);
  const validation = fluentValidation(job.result?.validation);
  const provenance = cfdProvenance(job);
  const requestedCase = job.requested_case_id || job.case_id;
  const effectiveCase = job.result?.effective_case_id || job.effective_case_id || job.case_id;
  const caseName = caseId => status?.cases?.find(item => item.case_id === caseId)?.title || (caseId === 'mock_cfd_demo' ? 'Mock CFD 模拟示例' : caseId);
  return (
    <Card title="任务与结果" size="small" data-testid="fluent-job-details">
      <Space wrap style={{ marginBottom: 12 }}>
        <Tag color={presentation.color}>{presentation.label}</Tag>
        <Tag color={provenance.isMock ? 'warning' : 'default'}>{job.result ? provenance.resultLabel : provenance.label}</Tag>
      </Space>
      {provenance.warning && <Alert type="warning" showIcon title={provenance.warning} style={{ marginBottom: 12 }} data-testid="cfd-job-mock-warning" />}
      {provenance.fallbackReason && <details style={{ marginBottom: 12 }}><summary>查看切换到 Mock 的原因</summary><p>{provenance.fallbackReason.message || '真实 CFD 后端当前不可用。'}</p><code>{provenance.fallbackReason.code}</code></details>}
      <Descriptions size="small" column={1} items={[
        { key: 'case', label: '实际算例', children: caseName(effectiveCase) },
        ...(requestedCase !== effectiveCase ? [{ key: 'requested-case', label: '请求算例', children: caseName(requestedCase) }] : []),
        { key: 'iterations', label: '迭代次数', children: job.iterations },
        { key: 'processors', label: '并行核数', children: job.processors },
        { key: 'id', label: '任务编号', children: job.job_id },
      ]} />
      {provenance.isMock && requestedCase !== effectiveCase && <Alert type="warning" title="本次使用模拟示例，未求解请求算例。" style={{ marginTop: 12 }} />}
      {job.status === 'prepared' && (
        <div style={{ margin: '14px 0' }}>
          <Typography.Paragraph>请核对以上已准备参数。{provenance.isMock ? '确认后将运行 Mock CFD 演示；输出不是实际流场求解结果。' : '确认后将请求本机 CFD 后端并消耗计算资源；如后台切换为 Mock，结果会明确标示。'}修改表单后需重新准备任务。</Typography.Paragraph>
          <Button type="primary" disabled={busy || !canRunFluentJob(job, status, useMockResponses)} onClick={() => onRun(job)}>{provenance.isMock ? '确认运行 Mock CFD' : '确认启动 CFD'}</Button>
        </div>
      )}
      {job.error && <Alert type="error" showIcon title="任务未成功完成" description={`${job.error.message || '请查看后端任务诊断。'}${job.error.code ? `（${job.error.code}）` : ''}`} style={{ margin: '12px 0' }} />}
      {Array.isArray(job.steps) && job.steps.length > 0 && (
        <details style={{ margin: '12px 0' }}><summary>查看任务步骤</summary><ol>{job.steps.map((step, index) => <li key={`${step.name}-${index}`}>{step.name} · {step.status}{step.detail ? `：${step.detail}` : ''}</li>)}</ol></details>
      )}
      {job.result && (
        <>
          <Alert type={provenance.isMock ? 'warning' : validation.type} showIcon title={provenance.isMock ? `演示数据检查：${validation.label}` : validation.label} description={provenance.isMock ? '演示数据的检查结果不能证明真实模型的物理可靠性。' : '检查结论以后台配置的物理范围和监测项为准，尚不等同于网格无关性或实验验证。'} style={{ margin: '12px 0' }} />
          <Table size="small" pagination={false} rowKey="name" dataSource={job.result.metrics || []} columns={[
            { title: '监测指标', dataIndex: 'name' },
            { title: '数值', render: (_, metric) => fluentMetric(metric.value, metric.unit) },
          ]} locale={{ emptyText: '未提取到有效监测指标' }} />
          {(job.result.histories || []).map((history, index) => <HistoryChart key={`${history.name}-${index}`} history={history} isMock={provenance.isMock} />)}
          {(job.result.validation?.checks || []).map((check, index) => (
            <Alert key={`${check.name}-${index}`} type={check.status === 'passed' ? 'success' : check.status === 'failed' ? 'error' : 'warning'} showIcon title={check.name} description={check.message} style={{ marginTop: 8 }} />
          ))}
        </>
      )}
      <Button onClick={() => onDownload(job)} disabled={busy} style={{ marginTop: 12 }}>下载任务报告 (.md)</Button>
      <details style={{ marginTop: 12 }}><summary>查看复现标识</summary><Typography.Paragraph copyable style={{ wordBreak: 'break-all', marginTop: 8 }}>{job.input_fingerprint || '暂无输入指纹'}</Typography.Paragraph><div>创建时间：{job.created_at}</div><div>更新时间：{job.updated_at}</div></details>
    </Card>
  );
}

import { useState } from 'react';
import { Alert, Button, Card, Form, InputNumber, Select, Space, Table, Tag, Typography } from 'antd';
import FluentJobDetails from './FluentJobDetails.jsx';
import CfdEnvironmentReport from './CfdEnvironmentReport.jsx';
import { cfdProvenance, fluentAvailability, fluentJobStatus, fluentWarning, prepareFluentInputs } from './fluentPresentation.js';
import useFluentJobs from './useFluentJobs.js';

export default function FluentPanel({ active = true, useMockResponses = false }) {
  const state = useFluentJobs({ active, useMockResponses });
  const [values, setValues] = useState({ case_id: null, iterations: 100, processors: 1 });
  const [formErrors, setFormErrors] = useState([]);
  const availability = fluentAvailability(state.status, useMockResponses);
  const provenance = cfdProvenance(state.status);
  const cases = state.status?.cases || [];
  const selectedCase = cases.find(item => item.case_id === values.case_id);
  const update = (field, value) => { setValues(previous => ({ ...previous, [field]: value })); setFormErrors([]); };
  const prepare = () => {
    const { payload, errors } = prepareFluentInputs(values, state.status);
    setFormErrors(errors);
    if (payload) void state.prepare(payload);
  };
  const disabled = state.busy || state.loading;
  return (
    <section style={{ padding: 24 }} aria-label="CFD 任务" data-testid="fluent-panel">
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
          <div><Typography.Title level={4} style={{ margin: 0 }}>CFD 仿真任务</Typography.Title><Typography.Text type="secondary">{provenance.label} · 从已配置算例开始，记录任务与监测结果。</Typography.Text></div>
          <Button onClick={state.refresh} loading={state.loading} disabled={state.busy || useMockResponses}>刷新状态</Button>
        </Space>
        <Alert type={availability.canRun ? 'info' : 'warning'} showIcon title={availability.message} />
        {provenance.warning && <Alert type="warning" showIcon title={provenance.warning} data-testid="cfd-mock-warning" />}
        {provenance.fallbackReason && <details><summary>查看切换到 Mock 的原因</summary><p>{provenance.fallbackReason.message || '真实 CFD 后端当前不可用。'}</p><code>{provenance.fallbackReason.code}</code></details>}
        <CfdEnvironmentReport status={state.status} />
        {(state.status?.warnings || []).map((warning, index) => <Alert key={index} type="warning" title={fluentWarning(warning)} />)}
        {state.error && <Alert type="error" showIcon title={state.error} />}
        <Card title="准备仿真任务" size="small">
          <Form layout="vertical" onFinish={prepare}>
            <Form.Item label="已注册算例">
              <Select aria-label="已注册算例" value={values.case_id} onChange={value => update('case_id', value)} options={cases.map(item => ({ value: item.case_id, label: item.title || item.case_id }))} placeholder={cases.length ? '选择算例' : '暂无已注册算例'} disabled={disabled || !availability.canPrepare} />
            </Form.Item>
            {selectedCase && <Typography.Paragraph type="secondary">{provenance.isMock ? '平壁解析演示；迭代/核数仅验证任务参数' : `${selectedCase.dimension} · 监测项：${(selectedCase.reports || []).map(item => `${item.name}${item.unit ? ` (${item.unit})` : ''}`).join('、') || '未配置'}`}</Typography.Paragraph>}
            {(selectedCase?.warnings || []).map((warning, index) => <Alert key={index} title={warning} type="warning" style={{ marginBottom: 10 }} />)}
            <Space wrap align="start">
              <Form.Item label="迭代次数"><InputNumber aria-label="迭代次数" min={1} max={state.status?.limits?.max_iterations} precision={0} value={values.iterations} onChange={value => update('iterations', value)} disabled={disabled || !availability.canPrepare} /></Form.Item>
              <Form.Item label="并行核数"><InputNumber aria-label="并行核数" min={1} max={state.status?.limits?.max_processors} precision={0} value={values.processors} onChange={value => update('processors', value)} disabled={disabled || !availability.canPrepare} /></Form.Item>
            </Space>
            {formErrors.length > 0 && <Alert type="error" title={formErrors.join(' ')} style={{ marginBottom: 12 }} />}
            <Button htmlType="submit" type="primary" disabled={disabled || !availability.canPrepare || !selectedCase}>准备任务</Button>
          </Form>
        </Card>
        <Card size="small" title="任务记录" extra={state.jobs.some(job => job.status === 'running') ? <Tag color="processing">求解期间自动刷新</Tag> : null}>
          <Table size="small" rowKey="job_id" dataSource={state.jobs} scroll={{ x: 560 }} pagination={{ pageSize: 5, showSizeChanger: false }} locale={{ emptyText: state.loading ? '正在读取任务' : '暂无任务' }} columns={[
            { title: '实际算例', render: (_, job) => {
              const caseId = job.result?.effective_case_id || job.effective_case_id || job.case_id;
              return cases.find(item => item.case_id === caseId)?.title || (caseId === 'mock_cfd_demo' ? 'Mock CFD 模拟示例' : caseId);
            } },
            { title: '状态', dataIndex: 'status', render: value => <Tag color={fluentJobStatus(value).color}>{fluentJobStatus(value).label}</Tag> },
            { title: '计算后端', render: (_, job) => <Tag color={cfdProvenance(job).isMock ? 'warning' : 'default'}>{cfdProvenance(job).label}</Tag> },
            { title: '迭代 / 核数', render: (_, job) => `${job.iterations} / ${job.processors}` },
            { title: '操作', render: (_, job) => <Button size="small" disabled={state.busy} onClick={() => state.select(job)}>查看</Button> },
          ]} />
        </Card>
        <FluentJobDetails job={state.selected} status={state.status} busy={state.busy || state.loading} useMockResponses={useMockResponses} onRun={state.run} onDownload={state.downloadReport} />
      </Space>
    </section>
  );
}

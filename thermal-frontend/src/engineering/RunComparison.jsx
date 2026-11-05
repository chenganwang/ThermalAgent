import { Alert, Card, Table } from 'antd';
import { engineeringValue } from '../engineeringRunPresentation.js';

export default function RunComparison({ comparison }) {
  if (!comparison) return null;
  const compatible = comparison.compatible === true;
  return <Card title="方案结果对比" size="small" data-testid="engineering-run-comparison">
    <Alert type={compatible ? 'info' : 'warning'} title={compatible ? '同工具/单位的已完成结果对比，仍需复核适用条件。' : '方案条件不兼容，不展示设计差值。'} />
    {(comparison.warnings || []).map((warning, index) => <p key={index}>{warning}</p>)}
    <Table size="small" rowKey="name" pagination={false} scroll={{ x: 600 }} dataSource={comparison.variables || []} columns={[
      { title: '输出变量', dataIndex: 'name' },
      { title: '单位', dataIndex: 'unit', render: unit => unit || '未提供/不一致' },
      ...(comparison.runs || []).map((run, index) => ({ title: `方案 ${index + 1} · ${run.run_id}`, render: (_, row) => engineeringValue(row.values?.[index]) })),
      { title: '方案 2 − 方案 1', render: (_, row) => compatible && row.delta !== null && row.delta !== undefined ? engineeringValue(row.delta) : '不可比较' },
    ]} />
  </Card>;
}

import { Card, Descriptions, Tag } from 'antd';


export default function ExecutionEvidenceCard({ view }) {
  if (!view) return null;
  const items = [
    { key: 'backend', label: '执行后端', children: view.backendLabel },
    { key: 'mode', label: '执行模式', children: view.modeLabel },
    { key: 'model', label: '模型', children: view.modelLabel },
    view.modelVersion ? { key: 'version', label: '模型版本', children: view.modelVersion } : null,
    view.formula && view.formula !== '—' ? { key: 'formula', label: '公式', children: view.formula } : null,
    view.matlabVersion ? { key: 'matlab-version', label: '求解环境', children: view.matlabVersion } : null,
    view.durationLabel ? { key: 'duration', label: '执行耗时', children: view.durationLabel } : null,
    view.criticLabel ? { key: 'critic', label: 'Result Critic', children: view.criticLabel } : null,
    view.analyticalStatus ? { key: 'analytical-status', label: '解析校验', children: view.analyticalStatus } : null,
    view.expectedLabel ? { key: 'analytical-expected', label: '解析期望值', children: view.expectedLabel } : null,
    view.actualLabel ? { key: 'analytical-actual', label: 'MATLAB 实际值', children: view.actualLabel } : null,
    view.relativeErrorLabel ? { key: 'analytical-relative-error', label: '相对误差', children: view.relativeErrorLabel } : null,
    view.toleranceLabel ? { key: 'analytical-tolerance', label: '允许误差', children: view.toleranceLabel } : null,
  ].filter(Boolean);
  return (
    <Card size="small" title="执行证据" data-testid="execution-evidence-card" style={{ marginTop: 10, borderColor: 'rgba(79,195,247,.22)' }}>
      <Tag color={view.modeLabel === '真实 MATLAB' ? 'success' : 'default'}>{view.modeLabel}</Tag>
      <Tag color={view.cfdExecuted ? 'processing' : 'default'}>{view.cfdLabel}</Tag>
      {view.criticLabel && <Tag color={view.criticPassed ? 'success' : 'warning'}>{view.criticLabel}</Tag>}
      <Descriptions size="small" column={1} items={items} style={{ marginTop: 10 }} />
    </Card>
  );
}

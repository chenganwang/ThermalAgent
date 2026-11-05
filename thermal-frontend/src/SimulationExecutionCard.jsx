import { Card, Spin, Tag } from 'antd';


export default function SimulationExecutionCard({ view }) {
  if (!view) return null;
  return (
    <Card size="small" title="正在执行仿真" data-testid="simulation-execution-card" style={{ marginTop: 12 }}>
      <Spin size="small" /> <Tag color="processing">{view.backendLabel}</Tag>
    </Card>
  );
}

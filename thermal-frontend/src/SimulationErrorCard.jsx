import { Alert } from 'antd';


export default function SimulationErrorCard({ view }) {
  if (!view) return null;
  return (
    <Alert
      type="warning"
      showIcon
      data-testid="simulation-error-card"
      title={view.title}
      description={<>{view.description}<div style={{ marginTop: 4, color: 'var(--ta-text-muted)' }}>错误代码：{view.code}</div></>}
      style={{ marginTop: 12 }}
    />
  );
}

import { Card, Descriptions, Tag } from 'antd';

export default function SimulationResultCard({ view }) {
  if (!view) return null;
  return (
    <Card size="small" title={view.title} data-testid="simulation-result-card" style={{ marginTop: 12, borderColor: 'rgba(82,196,26,.35)' }}>
      <Tag color="success">✓ {view.statusLabel}</Tag>
      <div style={{ marginTop: 10, color: 'var(--ta-text-muted)' }}>模型：{view.modelLabel}</div>
      <Descriptions
        size="small"
        column={1}
        items={view.fields.map(field => ({ key: field.key, label: field.label, children: field.display }))}
        style={{ marginTop: 10 }}
      />
    </Card>
  );
}

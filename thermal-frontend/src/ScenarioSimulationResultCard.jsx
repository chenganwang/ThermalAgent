import { Alert, Card, Descriptions, Tag } from 'antd';

import { buildScenarioResultViewModel } from './scenarioForm';

export default function ScenarioSimulationResultCard({ result, outputSchema = [] }) {
  const view = buildScenarioResultViewModel(result, outputSchema);
  const overviewItems = [
    { key: 'scenario', label: '场景', children: view.scenario_name, span: 2 },
    { key: 'model', label: '模型', children: view.model_name, span: 2 },
    { key: 'solver', label: '求解器', children: view.solver },
    {
      key: 'status',
      label: '运行状态',
      children: <Tag color={view.success ? 'success' : 'error'}>{view.success ? '成功' : view.status}</Tag>,
    },
    { key: 'duration', label: '运行耗时', children: view.duration_display },
    { key: 'review', label: '人工复核', children: view.human_review_label },
    { key: 'evidence', label: '证据 ID', children: view.evidence_id || '—', span: 2 },
  ];
  const outputItems = view.output_items.map(item => ({
    key: item.name,
    label: item.label,
    children: item.display,
  }));

  return (
    <Card
      title="仿真运行结果"
      style={{ width: '100%', borderColor: 'rgba(79, 195, 247, 0.28)', textAlign: 'left' }}
    >
      {!view.success && (
        <Alert type="error" showIcon title="仿真未成功" description={view.status} style={{ marginBottom: 16 }} />
      )}
      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={overviewItems} />

      {outputItems.length > 0 && (
        <Card type="inner" title="输出" size="small" style={{ marginTop: 16 }}>
          <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={outputItems} />
        </Card>
      )}

      {view.formula.length > 0 && (
        <div
          style={{
            marginTop: 16,
            padding: '12px 14px',
            borderRadius: 10,
            background: 'rgba(79, 195, 247, 0.07)',
            fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace',
            lineHeight: 1.8,
          }}
        >
          {view.formula.map((line, index) => <div key={`${index}-${line}`}>{line}</div>)}
        </div>
      )}

      {view.assumptions.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <strong>假设与边界</strong>
          <ul style={{ margin: '8px 0 0', paddingLeft: 22 }}>
            {view.assumptions.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}
          </ul>
        </div>
      )}
      {view.warnings.length > 0 && (
        <Alert
          type="warning"
          showIcon
          title="运行警告"
          description={<ul style={{ margin: 0, paddingLeft: 20 }}>{view.warnings.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul>}
          style={{ marginTop: 16 }}
        />
      )}

      <details style={{ marginTop: 16 }}>
        <summary style={{ color: 'var(--ta-primary)', cursor: 'pointer', fontWeight: 600 }}>查看详细数据</summary>
        <pre
          style={{
            marginTop: 10,
            maxHeight: 320,
            overflow: 'auto',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            padding: 12,
            borderRadius: 8,
            background: 'rgba(0, 0, 0, 0.28)',
            fontSize: 12,
          }}
        >
          {view.detail_json}
        </pre>
      </details>
    </Card>
  );
}

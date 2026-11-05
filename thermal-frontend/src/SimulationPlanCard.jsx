import { Alert, Button, Card, Descriptions, Space, Tag, Typography } from 'antd';
import { buildPlanPresentation } from './simulationPresentation';


const { Text } = Typography;

export default function SimulationPlanCard({ plan, mode, matlab, onAction, actionsEnabled = true }) {
  const view = buildPlanPresentation(plan, mode, matlab, actionsEnabled);
  if (!view.generated) return null;
  return (
    <Card
      size="small"
      title={view.title}
      data-testid="simulation-plan-card"
      style={{ marginTop: 12, borderColor: 'rgba(79,195,247,.3)', background: 'rgba(13,27,42,.5)' }}
    >
      <Descriptions
        size="small"
        column={1}
        items={[
          { key: 'goal', label: '目标', children: view.objective },
          { key: 'model', label: '模型', children: view.modelLabel },
          { key: 'backend', label: '执行后端', children: view.backendLabel },
          { key: 'reason', label: '选择依据', children: view.selectionLabel },
          {
            key: 'inputs',
            label: '已识别参数',
            children: view.fields.length > 0
              ? <div>{view.fields.map(field => <div key={field.key}><Text>{field.label}</Text><Text style={{ marginLeft: 12 }}>{field.display}</Text></div>)}</div>
              : '无',
          },
          { key: 'status', label: '参数状态', children: view.parameterStatus },
          ...(view.generatedStatusLabel ? [{ key: 'generated-status', label: '生成模型状态', children: view.generatedStatusLabel }] : []),
          ...(view.missing.length > 0 ? [{ key: 'missing', label: '缺少参数', children: view.missing.join('、') }] : []),
        ]}
      />
      {view.preparationLabel && <Tag style={{ marginTop: 10 }}>{view.preparationLabel}</Tag>}
      {view.candidates.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <Text type="secondary">候选模型：</Text>{' '}
          {view.candidates.map(candidate => (
            <Tag key={candidate.id}>{candidate.label}</Tag>
          ))}
        </div>
      )}
      {view.needsModelSelection && (
        <Alert type="info" showIcon title="找到多个接近模型，请在对话中补充几何类型。" style={{ marginTop: 10 }} />
      )}
      {view.blockLabel && !view.needsModelSelection && (
        <Alert type="warning" showIcon title={view.blockLabel} style={{ marginTop: 10 }} />
      )}
      {view.invalid && <Alert type="error" showIcon title="参数存在矛盾或无效值，请在对话中修正后重新确认。" style={{ marginTop: 10 }} />}
      {view.matlabUnavailable && (
        <Alert type="warning" showIcon title="MATLAB 当前不可用，计划不会执行。" style={{ marginTop: 10 }} />
      )}
      <Space wrap style={{ marginTop: 12 }}>
        {view.canConfirm && <Button type="primary" onClick={() => onAction?.('confirm', view.planId)}>确认执行</Button>}
        {view.canRevise && <Button onClick={() => onAction?.('revise', view.planId)}>{view.reviseLabel}</Button>}
        {view.canCancel && <Button danger onClick={() => onAction?.('cancel', view.planId)}>取消</Button>}
      </Space>
    </Card>
  );
}

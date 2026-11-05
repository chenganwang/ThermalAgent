import { ExperimentOutlined } from '@ant-design/icons';


export default function SimulationModeToggle({ enabled, available = true, reason = '', onChange }) {
  const title = available
    ? (enabled ? '关闭后，后续消息不再允许 Agent 规划仿真。' : '开启后，Agent 可按问题需要规划仿真。')
    : (reason || '仿真能力当前不可用');
  return (
    <button
      type="button"
      role="switch"
      aria-label="仿真模式"
      aria-checked={enabled}
      disabled={!available}
      title={title}
      onClick={() => onChange?.(!enabled)}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7,
        minHeight: 30,
        padding: '4px 10px',
        borderRadius: 999,
        border: `var(--ta-line-width, 1px) solid ${enabled ? 'var(--ta-primary)' : 'var(--ta-border)'}`,
        background: enabled ? 'var(--ta-primary-soft)' : 'var(--ta-surface)',
        color: enabled ? 'var(--ta-primary)' : 'var(--ta-text-muted)',
        cursor: available ? 'pointer' : 'not-allowed',
        opacity: available ? 1 : 0.55,
      }}
    >
      <ExperimentOutlined />
      <span>仿真</span>
      <span aria-hidden="true" style={{ fontSize: 11 }}>{enabled ? '●' : '○'}</span>
    </button>
  );
}

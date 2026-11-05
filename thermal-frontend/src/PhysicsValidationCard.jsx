import { Alert, Card, Space, Tag } from 'antd';

function physicsValidationFromResponse(response) {
  return response?.metadata?.calculation?.raw?.physics_validation
    || response?.metadata?.calculation_result?.physics_validation || null;
}

export default function PhysicsValidationCard({ response }) {
  const validation = physicsValidationFromResponse(response);
  if (!validation || typeof validation !== 'object') return null;
  const passed = validation.passed === true && validation.status === 'passed';
  const failed = validation.passed === false || validation.status === 'failed';
  const count = Number.isInteger(validation.checked_quantity_count) && validation.checked_quantity_count >= 0
    ? validation.checked_quantity_count : null;
  const issues = Array.isArray(validation.issues) ? validation.issues : [];
  const limitations = Array.isArray(validation.limitations) ? validation.limitations : [];
  return (
    <Card size="small" title="物理规则校验" style={{ marginTop: 12 }} data-testid="physics-validation-card">
      <Space wrap>
        <Tag color={passed ? 'success' : failed ? 'error' : 'warning'}>{passed ? '已通过已配置规则' : failed ? '规则校验未通过' : '校验状态未确认'}</Tag>
        {count !== null && <span>检查 {count} 个物理量</span>}
        <span>{validation.energy_balance_checked === true ? '已检查能量平衡' : '未检查能量平衡'}</span>
      </Space>
      {issues.map((issue, index) => <Alert key={index} type="error" title={typeof issue.message === 'string' ? issue.message : '物理量不符合校验规则'} style={{ marginTop: 8 }} />)}
      <div style={{ marginTop: 8, fontSize: 12, color: 'var(--ta-text-muted)' }}>结论来自后台确定性规则；适用范围由输入、规则和已声明假设共同决定。</div>
      {limitations.length > 0 && <details style={{ marginTop: 8 }}><summary>适用范围与限制</summary><ul>{limitations.filter(item => typeof item === 'string').map((item, index) => <li key={index}>{item}</li>)}</ul></details>}
    </Card>
  );
}

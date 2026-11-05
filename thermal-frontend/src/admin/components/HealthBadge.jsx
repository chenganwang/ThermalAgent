import { Tag } from 'antd';
import { healthMeta } from '../api/contracts.js';

export default function HealthBadge({ status }) {
  const meta = healthMeta(status);
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

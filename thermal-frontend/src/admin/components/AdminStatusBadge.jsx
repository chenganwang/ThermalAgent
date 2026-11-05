import { Tag } from 'antd';

export default function AdminStatusBadge({ value, presentation }) {
  const meta = presentation(value);
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

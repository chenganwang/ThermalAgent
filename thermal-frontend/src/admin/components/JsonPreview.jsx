import { Collapse } from 'antd';

export default function JsonPreview({ value, label = '高级信息' }) {
  return (
    <Collapse
      size="small"
      items={[{ key: 'details', label, children: <pre className="admin-json-view">{JSON.stringify(value ?? {}, null, 2)}</pre> }]}
    />
  );
}

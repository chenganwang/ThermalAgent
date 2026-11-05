import { Alert, Button, Empty, Skeleton, Space } from 'antd';
import { adminErrorMessage } from '../api/contracts.js';

export default function PageState({ loading, error, empty, onRetry, children }) {
  if (loading && !children) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (error && !children) {
    return <Alert type="error" showIcon title={adminErrorMessage(error)} action={<Button onClick={onRetry}>重试</Button>} />;
  }
  if (empty && !error) return <Empty description="暂无可显示数据" />;
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      {error && <Alert type="warning" showIcon title={adminErrorMessage(error)} action={<Button onClick={onRetry}>重试</Button>} />}
      {children}
    </Space>
  );
}

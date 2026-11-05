import { useState } from 'react';
import { Alert, Button, Card, Form, Input, Space, Spin, Typography } from 'antd';
import { Link, Outlet } from 'react-router-dom';
import { adminErrorMessage } from '../api/contracts.js';
import { useAdminAuth } from './AdminAuthState.js';
import ThemeSwitcher from '../../theme/ThemeSwitcher.jsx';
import { useAppTheme } from '../../theme/useAppTheme.js';

export default function AuthGuard() {
  const { session, validating, sessionError, login } = useAdminAuth();
  const [error, setError] = useState('');
  const { themeId } = useAppTheme();

  if (session) return <Outlet />;

  if (validating) {
    return <main className="admin-login-shell"><Spin size="large" description="正在验证管理访问权限…" /></main>;
  }

  const submit = async ({ token: candidate }) => {
    setError('');
    try {
      await login(candidate);
    } catch (requestError) {
      setError(adminErrorMessage(requestError));
    }
  };

  return (
    <main className="admin-login-shell">
      <Card className="admin-login-card" variant="borderless">
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          <div>
            {themeId === 'hyper' && <div className="hyper-lab-login-sticker">ELYSIAN ATELIER / AUTHORIZED ACCESS</div>}
            <Typography.Text type="secondary">ThermalAgent</Typography.Text>
            <Typography.Title level={2}>管理控制台</Typography.Title>
            <Typography.Paragraph type="secondary">
              请输入管理员凭据以继续。
            </Typography.Paragraph>
          </div>
          <ThemeSwitcher compact />
          {(error || sessionError) && <Alert type="error" showIcon title={error || adminErrorMessage(sessionError)} />}
          <Form layout="vertical" onFinish={submit} autoComplete="off">
            <Form.Item label="管理员口令" name="token" rules={[{ required: true, message: '请输入管理员口令' }]}>
              <Input.Password autoComplete="off" placeholder="请输入管理员口令" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={validating}>进入管理控制台</Button>
          </Form>
          <Link to="/">返回工程工作台</Link>
        </Space>
      </Card>
    </main>
  );
}

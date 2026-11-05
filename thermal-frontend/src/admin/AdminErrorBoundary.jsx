import { Component } from 'react';
import { Alert, Button } from 'antd';

export default class AdminErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="admin-error-shell">
          <Alert
            type="error"
            showIcon
            title="管理页面局部渲染失败"
            description="错误详情已隐藏，其他功能不受影响。"
            action={<Button onClick={() => globalThis.location.assign('/admin')}>返回管理首页</Button>}
          />
        </main>
      );
    }
    return this.props.children;
  }
}

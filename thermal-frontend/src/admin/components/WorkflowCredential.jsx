import { Button, Input, Space, Tag } from 'antd';
import { useState } from 'react';
import { useAdminAuth } from '../auth/AdminAuthState.js';

export default function WorkflowCredential() {
  const { workflowWriteToken, elevateWorkflowWrite, clearWorkflowWrite } = useAdminAuth();
  const [candidate, setCandidate] = useState('');

  if (workflowWriteToken === true) return null;

  if (workflowWriteToken) {
    return (
      <Space>
        <Tag color="green">管理操作已授权</Tag>
        <Button size="small" onClick={clearWorkflowWrite}>清除凭据</Button>
      </Space>
    );
  }

  return (
    <Space.Compact>
      <Input.Password
        aria-label="管理员操作口令"
        autoComplete="off"
        value={candidate}
        onChange={event => setCandidate(event.target.value)}
        placeholder="管理员操作口令"
      />
      <Button
        type="primary"
        disabled={!candidate.trim()}
        onClick={() => { elevateWorkflowWrite(candidate); setCandidate(''); }}
      >授权管理操作</Button>
    </Space.Compact>
  );
}

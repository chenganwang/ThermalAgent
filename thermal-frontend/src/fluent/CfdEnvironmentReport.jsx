import { Alert, Button, Descriptions, Tag } from 'antd';
import { publicCfdEnvironment } from './fluentPresentation.js';

export default function CfdEnvironmentReport({ status }) {
  const environment = publicCfdEnvironment(status);
  if (!environment) return null;
  const deferred = environment.status === 'deferred';
  const checked = ['available', 'unavailable'].includes(environment.status);
  const statusLabel = deferred ? '暂缓检查' : environment.status === 'available' ? '已发现可用环境' : environment.status === 'unavailable' ? '真实环境未就绪' : '尚未检查';
  const solverLabel = !checked ? '未检查' : environment.solver_found === true ? '已找到' : environment.solver_found === false ? '未找到' : '未检查';
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(environment, null, 2)], { type: 'application/json;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'cfd-environment-report.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <details data-testid="cfd-environment-report">
      <summary>环境检测报告 <Tag color={environment.status === 'available' ? 'blue' : checked ? 'warning' : 'default'}>{statusLabel}</Tag></summary>
      <Descriptions size="small" column={1} style={{ margin: '12px 0' }} items={[
        { key: 'solver', label: '求解器', children: solverLabel },
        { key: 'version', label: '版本', children: environment.version || (checked ? '未提供版本' : '未检查') },
        { key: 'license', label: '许可证检测', children: environment.license_checked ? '已检查（以检测项为准）' : '未检查' },
      ]} />
      {environment.checks.map((check, index) => <Alert key={index} type={['passed', 'not_checked', 'deferred'].includes(check.status) ? 'info' : 'warning'} title={check.name || '环境检测项'} description={check.message || check.code || '未提供说明'} style={{ marginBottom: 8 }} />)}
      <Button onClick={download}>下载环境报告 (.json)</Button>
    </details>
  );
}

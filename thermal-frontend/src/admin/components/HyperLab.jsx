import { Button, Tag } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import HealthBadge from './HealthBadge.jsx';
import { formatObservedAt } from '../api/contracts.js';
import ElysiaPortrait from '../../hyper/ElysiaPortrait.jsx';

export function HyperLabTitle({ code, english, children }) {
  return <span className="hyper-lab-title"><b aria-hidden="true">{code}</b><span><small>{english}</small><span>{children}</span></span></span>;
}

function ArchiveSeal() {
  return <svg className="hyper-lab-seal" viewBox="0 0 120 120" fill="none" aria-hidden="true">
    <circle cx="60" cy="60" r="48" /><circle cx="60" cy="60" r="41" strokeDasharray="1 7" />
    <path d="M60 30C76 41 79 54 60 63C41 54 44 41 60 30ZM30 60C41 44 54 41 63 60C54 79 41 76 30 60ZM90 60C79 76 66 79 57 60C66 41 79 44 90 60ZM60 90C44 79 41 66 60 57C79 66 76 79 60 90Z" />
    <path d="M60 14V5M60 115v-9M14 60H5M115 60h-9M56 60h8M60 56v8" />
  </svg>;
}

export function HyperLabHero({ dashboard }) {
  const navigate = useNavigate();
  return <div className="hyper-lab-hero">
    <div className="hyper-lab-hero-copy">
      <span className="hyper-lab-kicker">ELYSIAN ATELIER · RESEARCH ARCHIVE</span>
      <p className="hyper-lab-wordmark">让想法，<br /><em>写成有据可循的答案。</em></p>
      <p>在这一页，整理知识、确认计算，收藏每一步工程探索。</p>
      <Button type="primary" size="large" icon={<ArrowRightOutlined />} onClick={() => navigate('/admin/agent-tasks')}>翻开工程卷宗</Button>
      <div className="hyper-lab-companion"><ElysiaPortrait compact /><span><small>ELYSIA / 手记导航</small><span>一起把探索，好好记下。</span></span></div>
    </div>
    <div className="hyper-lab-console">
      <ArchiveSeal />
      <div className="hyper-lab-console-head"><span>OBSERVATION / 本次观测</span><span aria-hidden="true">01</span></div>
      <div className="hyper-lab-readout"><span>服务组件</span><HealthBadge status={dashboard?.overall_status?.status} /><time>{formatObservedAt(dashboard?.generated_at)}</time></div>
      <ol className="hyper-lab-protocol" aria-label="工程记录流程说明">
        <li><b>Ⅰ</b><span>知识作为起点<small>检索设计依据</small></span></li>
        <li><b>Ⅱ</b><span>计算写下过程<small>保留工具与中间变量</small></span></li>
        <li><b>Ⅲ</b><span>验证留下证据<small>检查物理与数值约束</small></span></li>
      </ol>
      <span className="hyper-lab-console-note">记录原则示意 · 执行状态以实际任务为准</span>
    </div>
  </div>;
}

export function HyperBenchmarkNote() {
  const navigate = useNavigate();
  return <aside className="hyper-lab-benchmark"><div><span className="hyper-lab-kicker">MARGIN NOTE / BENCHMARK</span><h3>为每次探索，留下一份对照。</h3><p>Benchmark 使用本地命令行运行；此面板未连接成绩接口。求解器状态可在模块监控中查看。</p><code>python scripts/run_test_suite.py --profile benchmark</code></div><div><Tag>离线 CLI · 非实时成绩</Tag><Button onClick={() => navigate('/admin/modules')}>查看求解器与模块 <ArrowRightOutlined /></Button></div></aside>;
}

export function HyperMonitorIntro({ total }) {
  return <div className="hyper-lab-monitor"><div><span className="hyper-lab-kicker">ENGINEERING CHRONICLE / 工程卷宗</span><h3>每一步，都值得被记下。</h3><p>翻开任务，查看实际步骤、变量、物理检查与原始 Trace。</p></div><div className="hyper-lab-monitor-count"><strong>{total ?? '—'}</strong><span>已保存任务 / API</span></div></div>;
}

import EngineerMark from './EngineerMark.jsx';
import { LIQUID_COOLING_EXAMPLE } from '../tasks/taskState.js';
import { useAppTheme } from '../theme/useAppTheme.js';
import { AnimeWelcome } from './AnimeWorkspace.jsx';
import { HyperWelcome } from '../hyper/index.js';

export default function WelcomePanel({ onExample }) {
  const { themeId } = useAppTheme();
  if (themeId === 'hyper') return <HyperWelcome onExample={onExample} />;
  if (themeId === 'cel') return <AnimeWelcome onExample={onExample} />;
  return <section className="ta-welcome"><div className="ta-welcome-heading"><div><span className="ta-eyebrow">THERMAL ENGINEERING WORKSPACE</span><h2>从一个问题，<br />走向可复核的工程结论。</h2><p>连接知识、计算与验证，让每一次设计有据可循。</p></div><EngineerMark /></div>
    <div className="ta-example-grid">
      <button type="button" onClick={() => onExample('chat', '冷板热阻由哪些因素决定？请说明计算边界并给出可追溯来源。')}><span className="ta-example-icon">01 / KNOWLEDGE</span><strong>理解工程问题</strong><span>冷板热阻与设计边界</span><i aria-hidden="true">↗</i></button>
      <button type="button" onClick={() => onExample('task', LIQUID_COOLING_EXAMPLE)} data-testid="liquid-cooling-example"><span className="ta-example-icon">02 / WORKFLOW</span><strong>规划液冷回路</strong><span>流量 → 流态 → 压降 → 验证</span><i aria-hidden="true">↗</i></button>
      <button type="button" onClick={() => onExample('report', '壁厚5mm，导热系数16W/(mK)，面积0.002m²，两侧温差60K，计算平壁导热热流并生成工程报告。')}><span className="ta-example-icon">03 / EVIDENCE</span><strong>生成工程报告</strong><span>平壁导热 · 参数与公式可追溯</span><i aria-hidden="true">↗</i></button>
    </div><div className="ta-welcome-footnote"><span>显式参数</span><span>真实工具记录</span><span>物理规则检查</span><span>来源可追溯</span></div>
  </section>;
}

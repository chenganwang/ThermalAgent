import { LIQUID_COOLING_EXAMPLE } from '../tasks/taskState.js';
import ElysiaPortrait from './ElysiaPortrait.jsx';
import AtelierMotif from './AtelierMotif.jsx';
import './hyper.css';

export default function HyperWelcome({ onExample, composer }) {
  return <section className="hyper-welcome atelier-welcome" data-testid="hyper-welcome" aria-label="花与书的工程手记">
    <div className="atelier-home-stage">
      <div className="atelier-invitation"><span className="hyper-kicker">ELYSIAN ATELIER / ENGINEERING COMPANION</span><h2>让灵感，<br /><em>有迹可循。</em></h2><p>和爱莉希雅一起，展开下一页工程探索。<br />从一个问题，到有依据的答案。</p><div className="atelier-signature"><span /><AtelierMotif /><span /></div></div>
      <div className="atelier-home-character"><span className="atelier-character-orbit" aria-hidden="true" /><ElysiaPortrait state="idle" /><div className="atelier-character-caption"><span>ELYSIA</span><small>爱莉希雅 · 陪伴每一次探索</small></div></div>
      <div className="atelier-home-composer">{composer}</div>
    </div>
    <div className="atelier-chapter-heading"><span>从这里，翻开新的一页</span><small>CHOOSE A CHAPTER</small></div>
    <div className="hyper-quests">
      <button type="button" className="hyper-quest" data-testid="hyper-liquid-cooling-example" onClick={() => onExample('task', LIQUID_COOLING_EXAMPLE)}><span className="hyper-quest-number">01</span><span><small>DESIGN / 液冷回路</small><strong>规划液冷回路</strong><span>流量、压降与物理约束</span></span><i aria-hidden="true">↗</i></button>
      <button type="button" className="hyper-quest" onClick={() => onExample('chat', '冷板热阻由哪些因素决定？请说明计算边界并给出可追溯来源。')}><span className="hyper-quest-number">02</span><span><small>KNOWLEDGE / 知识手记</small><strong>读懂热设计</strong><span>让每个结论，都有出处</span></span><i aria-hidden="true">↗</i></button>
      <button type="button" className="hyper-quest" onClick={() => onExample('chat', '壁厚5mm，导热系数16W/(mK)，面积0.002m²，两侧温差60K，计算平壁导热热流并说明公式、单位与适用范围。')}><span className="hyper-quest-number">03</span><span><small>COMPUTATION / 可信计算</small><strong>来一次可信计算</strong><span>从参数与公式，走向验证</span></span><i aria-hidden="true">↗</i></button>
    </div><p className="hyper-launch-footnote">选择章节会填入问题，确认参数后再发送。</p>
  </section>;
}

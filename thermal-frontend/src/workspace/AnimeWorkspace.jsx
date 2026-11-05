import EngineerMark from './EngineerMark.jsx';
import { LIQUID_COOLING_EXAMPLE } from '../tasks/taskState.js';
import { assistantBrief } from './animePresentation.js';

function CoolingSketch() {
  return <svg className="ta-anime-cooling-sketch" viewBox="0 0 310 250" role="img" aria-label="液冷模块概念设定图，非仿真结果">
    <g fill="none" stroke="#222b48" strokeWidth="1.6" strokeLinejoin="round">
      <path d="M12 39h29M12 39v28m257 151h-29m29 0v-28" opacity=".4" />
      <path d="m49 174 128-68 98 50-129 70z" fill="#c5cfe3" stroke="none" />
      <path d="m42 145 128-68 98 50-128 69z" fill="#fffdf8" />
      <path d="m42 145 98 51v15l-98-50z" fill="#adbcd3" /><path d="m140 196 128-69v15l-128 69z" fill="#8294b1" />
      <path d="m66 110 109-57 69 35-109 59z" fill="#f8faff" /><path d="m66 110 69 37v21l-69-38z" fill="#becbdd" /><path d="m135 147 109-59v21l-109 59z" fill="#8096b7" />
      <path d="m102 108 73-39 34 17-72 39z" fill="#eeebff" stroke="#5746c4" strokeWidth="2.5" />
      <path d="m100 117 36 19 82-44m-106 20 24 12 61-33" stroke="#5746c4" strokeWidth="2" />
      <path d="m97 129-23 13-27-15v-37l17-9m158 36 25 13 21-12V82l-18-9" stroke="#167b89" strokeWidth="7" />
      <path d="m96 124-23 13-26-14v-33l17-9m158 31 25 13 21-10V82l-18-9" stroke="#77d3d6" strokeWidth="3" />
      <path d="m115 50 44-24 42 22-44 25z" fill="#fffdf8" /><path d="m115 50 42 23v20l-42-23z" fill="#c5c0ee" /><path d="m157 73 44-25v20l-44 25z" fill="#8b81cf" />
      <path d="m124 49 32 16 32-17-30-15z" stroke="#5746c4" strokeWidth="2" /><path d="m132 49 25 12 22-13m-37-4 15 7 12-7" stroke="#5746c4" />
      <path d="m53 62 48-27m118 146 63-34m-110 59v27h42" strokeDasharray="3 4" stroke="#b35220" />
      <circle cx="53" cy="62" r="3" fill="#b35220" /><circle cx="219" cy="181" r="3" fill="#b35220" />
    </g>
    <g fill="#576179" fontFamily="Consolas,monospace" fontSize="9"><text x="20" y="31">THERMAL MODULE</text><text x="186" y="238">CONCEPT SKETCH</text><text x="222" y="46">冷却回路</text></g>
  </svg>;
}

export function AnimeWelcome({ onExample }) {
  return <section className="ta-anime-welcome" data-testid="anime-welcome">
    <div className="ta-anime-file-heading"><span>RESEARCH DECK / 01</span><span>THERMAL SYSTEMS LAB</span></div>
    <div className="ta-anime-briefing">
      <div className="ta-anime-brief-copy"><span className="ta-anime-chapter">NEW MISSION <i aria-hidden="true">↗</i></span><h2>让工程灵感，<br /><em>进入验证阶段。</em></h2><p>你的工程研究搭档已就位。<br />从一个目标开始，连接知识、计算与物理验证。</p><span className="ta-anime-note">知 识 × 计 算 × 验 证</span></div>
      <figure className="ta-anime-sketch-sheet"><span className="ta-anime-figure-no">DESIGN NOTE / A</span><CoolingSketch /><figcaption>液冷模块 · 概念设定稿</figcaption></figure>
    </div>
    <div className="ta-anime-selection-title"><span>CHOOSE YOUR RESEARCH ROUTE</span><strong>选择研究方向</strong><span aria-hidden="true">01 — 03</span></div>
    <div className="ta-anime-route-grid">
      <button type="button" onClick={() => onExample('chat', '冷板热阻由哪些因素决定？请说明计算边界并给出可追溯来源。')}><span className="ta-anime-route-no">01</span><span className="ta-anime-route-icon" aria-hidden="true">⌕</span><small>KNOWLEDGE ARCHIVE</small><strong>检索工程知识</strong><span>冷板热阻 · 设计边界 · 来源</span><b aria-hidden="true">OPEN FILE ↗</b></button>
      <button type="button" data-testid="liquid-cooling-example" onClick={() => onExample('task', LIQUID_COOLING_EXAMPLE)}><span className="ta-anime-route-no">02</span><span className="ta-anime-route-icon" aria-hidden="true">◇</span><small>LIQUID COOLING ANALYSIS</small><strong>推进液冷任务</strong><span>流量 → 压降 → 物理验证</span><b aria-hidden="true">START MISSION ↗</b></button>
      <button type="button" onClick={() => onExample('report', '壁厚5mm，导热系数16W/(mK)，面积0.002m²，两侧温差60K，计算平壁导热热流并生成工程报告。')}><span className="ta-anime-route-no">03</span><span className="ta-anime-route-icon" aria-hidden="true">▤</span><small>ENGINEERING FIELD NOTES</small><strong>整理工程报告</strong><span>平壁导热 · 参数 · 计算证据</span><b aria-hidden="true">WRITE REPORT ↗</b></button>
    </div>
    <p className="ta-anime-method-note"><span>METHOD</span> 显式参数 / 真实工具 / 可追溯证据 <i aria-hidden="true">✦</i></p>
  </section>;
}

export function AnimeNavigator({ task, loading }) {
  const brief = assistantBrief(task, loading);
  return <section className="ta-anime-navigator" aria-label="AI 导航助手" data-state={task?.status || 'idle'}>
    <div className="ta-anime-nav-label"><span>NAVIGATOR</span><small>AI ASSISTANT</small></div>
    <div className="ta-anime-nav-body"><div className="ta-anime-portrait"><EngineerMark small /></div><div><strong>THERMAL / 导航员</strong><span className="ta-anime-nav-status"><i aria-hidden="true" />{brief.label}</span></div></div>
    <p role="status">{brief.message}</p><div className="ta-anime-nav-foot">ENGINEERING INTELLIGENCE <span aria-hidden="true">✦</span></div>
  </section>;
}

export function AnimeTaskBar({ task, loading, onOpen }) {
  const brief = assistantBrief(task, loading);
  return <section className="ta-anime-taskbar" data-active={brief.active} aria-label="AI 任务状态栏">
    <span className="ta-anime-beacon" aria-hidden="true">✦</span><div><span className="ta-anime-taskbar-label">AI / {brief.label}{brief.id && ` · ${brief.id}`}</span><p role="status">{brief.message}</p></div>
    {task && <button type="button" onClick={() => onOpen(task.task_id)}>{brief.completed}/{brief.total} 步骤 <span aria-hidden="true">↗</span></button>}
    {brief.current?.tool_name && <code className="ta-anime-tool-signal">{brief.current.tool_name}</code>}
  </section>;
}

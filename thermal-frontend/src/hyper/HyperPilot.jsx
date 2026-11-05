import { useState } from 'react';
import { resolveHyperState } from './hyperState.js';
import { useHyperMotion } from './useHyperMotion.js';
import ElysiaPortrait from './ElysiaPortrait.jsx';
import './hyper.css';

const REACTIONS = ['美好的想法，值得被认真写下来。', '别着急，我们把每一个条件都看清楚。', '让灵感自由，让结论有据。'];
export default function HyperPilot(props) {
  const state = resolveHyperState(props);
  const motion = useHyperMotion();
  const [reaction, setReaction] = useState(-1);
  return <aside className="hyper-pilot atelier-companion" data-testid="hyper-pilot" data-state={state.state} data-busy={state.busy} data-motion={motion.enabled ? 'on' : 'off'} aria-label="爱莉希雅 AI 陪伴区">
    <div className="atelier-companion-portrait"><button type="button" className="hyper-mascot-button" aria-label="和爱莉希雅打个招呼" onClick={() => setReaction(value => (value + 1) % REACTIONS.length)}><ElysiaPortrait compact state={state.state} /></button><div className="hyper-pilot-name"><small>YOUR COMPANION</small><strong>爱莉希雅</strong><span>ELYSIA</span></div></div>
    <div className="hyper-pilot-voice" aria-live="polite"><strong>{state.busy ? '少女祈祷中……' : state.title}</strong><p>{state.detail}</p>{reaction >= 0 && <p className="hyper-reaction">{REACTIONS[reaction]}</p>}</div>
    <div className="hyper-pilot-status"><span>{state.label}</span>{state.taskId && <code title={state.taskId}>#{state.taskId.slice(-8)}</code>}</div>
    <button type="button" className="hyper-motion-toggle" onClick={motion.toggle} aria-pressed={motion.enabled}>{motion.enabled ? '暂停角色动画' : '启用角色动画'}</button>
    {!motion.persistent && <small className="hyper-storage-note">动画偏好仅对本次访问有效。</small>}
  </aside>;
}

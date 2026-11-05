import { resolveHyperState } from './hyperState.js';
import { useHyperMotion } from './useHyperMotion.js';
import ElysiaPortrait from './ElysiaPortrait.jsx';
import './hyper.css';

export default function HyperWaiting({ task, message, active }) {
  const motion = useHyperMotion();
  if (!active) return null;
  const state = resolveHyperState({ task, loading: true, pendingMessage: typeof message === 'object' ? message : undefined, mode: task ? 'task' : 'chat' });
  const detail = typeof message === 'string' && message ? message : state.detail;
  return <section className="hyper-waiting atelier-waiting" data-testid="hyper-waiting" data-state={state.state} data-busy={state.busy} data-motion={motion.enabled ? 'on' : 'off'} aria-label="当前请求等待状态">
    <div className="hyper-waiting-mascot"><ElysiaPortrait compact state={state.state} /></div>
    <div className="hyper-waiting-copy"><span className="hyper-kicker">{state.label}</span><strong>{state.busy ? '少女祈祷中……' : state.title}</strong><p role="status">{detail}</p><div className="atelier-writing-lines" aria-hidden="true"><i /><i /><i /></div><small>静候这一页展开 · 以服务回执为准</small></div>
    <button type="button" className="hyper-waiting-toggle" onClick={motion.toggle} aria-pressed={motion.enabled} aria-label={motion.enabled ? '暂停 Hyper 等待动画' : '启用 Hyper 等待动画'}>{motion.enabled ? '暂停动画' : '启用动画'}</button>
    {!motion.persistent && <small className="hyper-storage-note">浏览器无法保存偏好，本次选择仍有效。</small>}
  </section>;
}

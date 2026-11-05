import portrait from './assets/elysia-atlas.png';
import './elysiaPortrait.css';

/** Presentational fanart only; task state and all engineering decisions stay upstream. */
export default function ElysiaPortrait({ compact = false, className = '', state = 'idle' }) {
  return (
    <figure
      className={`atelier-elysia${compact ? ' atelier-elysia-compact' : ''}${className ? ` ${className}` : ''}`}
      data-state={state}
      title="非官方 AI 二创。© 米哈游版权所有。《崩坏3》素材的权利归米哈游所有，其他内容的相关权利、利益均归各自所有者享有。"
    >
      <span className="atelier-elysia-halo" aria-hidden="true" />
      <img
        src={portrait}
        alt="爱莉希雅二创形象：粉发精灵少女轻轻翻开工程手记"
        width="1024"
        height="1536"
        decoding="async"
        draggable="false"
      />
      {!compact && <figcaption className="portrait-credit">非官方 AI 二创 · © 米哈游版权所有</figcaption>}
    </figure>
  );
}

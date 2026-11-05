import { useAppTheme } from './useAppTheme.js';
import { THEMES } from './themeRegistry.js';
import { useHyperMotion } from '../hyper/useHyperMotion.js';

function MotionControl() {
  const motion = useHyperMotion();
  return <button type="button" className="ta-hyper-effects-toggle" aria-pressed={!motion.enabled} onClick={motion.toggle} title="系统的减少动态效果设置始终优先">{motion.enabled ? '✧ 减少动态效果' : '✓ 已减少动态效果'}</button>;
}

export default function ThemeSwitcher({ compact = false }) {
  const { themeId, setThemeId, storageAvailable } = useAppTheme();
  return <div className={`ta-theme-control${compact ? ' compact' : ''}`}>
    <fieldset className="ta-theme-switch"><legend className="ta-sr-only">界面主题</legend>{Object.values(THEMES).map(item => <button type="button" key={item.id} aria-pressed={themeId === item.id} title={item.description} onClick={() => setThemeId(item.id)} data-testid={`theme-${item.id}`}><span aria-hidden="true">{item.id === 'hyper' ? '✦' : item.id === 'cel' ? '✎' : '◫'}</span> {item.label}</button>)}</fieldset>
    {!storageAvailable && <span className="ta-theme-storage-warning" role="status">主题仅用于本次访问：浏览器未允许保存。</span>}
    {themeId === 'hyper' && <MotionControl />}
  </div>;
}

import { useEffect, useState } from 'react';
import '../hyper/hyperFocus.css';

/** Presentation-only controls. Unmounting the Hyper branch restores the shell. */
export default function HyperWorkspaceControls({ mode }) {
  const [focus, setFocus] = useState(false);
  const [missionOverride, setMissionOverride] = useState(null);
  const [width, setWidth] = useState(null);
  const missionVisible = missionOverride ?? mode === 'task';
  const missionWidth = width ?? (mode === 'task' ? 320 : 260);
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.hyperFocus = String(focus);
    root.dataset.hyperMission = missionVisible ? 'visible' : 'hidden';
    root.style.setProperty('--ta-mission-width', `${missionWidth}px`);
    return () => {
      delete root.dataset.hyperFocus;
      delete root.dataset.hyperMission;
      root.style.removeProperty('--ta-mission-width');
    };
  }, [focus, missionVisible, missionWidth]);
  useEffect(() => {
    if (!focus) return undefined;
    const escape = event => { if (event.key === 'Escape') setFocus(false); };
    document.addEventListener('keydown', escape);
    return () => document.removeEventListener('keydown', escape);
  }, [focus]);
  return <div className="ta-hyper-workspace-controls" aria-label="工作区布局">
    <button type="button" className="ta-hyper-layout-button" aria-pressed={focus} onClick={() => setFocus(value => !value)} title="隐藏顶栏与侧栏，专注问题和工程结论；Esc 退出">{focus ? '退出专注 · Esc' : '专注阅读'}</button>
    <button type="button" className="ta-hyper-layout-button" aria-expanded={missionVisible && !focus} disabled={focus} onClick={() => setMissionOverride(!missionVisible)}>{missionVisible ? '收起任务手记' : '展开任务手记'}</button>
    <details className="ta-hyper-layout-settings"><summary title="调整任务手记宽度">布局</summary><label>任务手记宽度 <output>{missionWidth}px</output><input type="range" aria-label="任务手记宽度" min="240" max="420" step="20" value={missionWidth} onChange={event => setWidth(Number(event.target.value))} /></label></details>
  </div>;
}

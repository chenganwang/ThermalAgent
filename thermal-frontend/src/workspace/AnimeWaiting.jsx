import { useEffect, useState } from 'react';
import './animeWaiting.css';

const STORAGE_KEY = 'thermalagent.animeWaiting.v1';

function initialPreference() {
  try { return { enabled: globalThis.localStorage.getItem(STORAGE_KEY) !== 'off', persistent: true }; }
  catch { return { enabled: true, persistent: false }; }
}

function ReadingNavigator() {
  return <svg className="ta-waiting-navigator" viewBox="0 0 76 76" aria-hidden="true" focusable="false">
    <ellipse cx="38" cy="71" rx="29" ry="3" fill="#dce3ef" />
    <g stroke="#222b48" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 36C11 24 16 9 30 6c18-5 31 4 32 20l-3 19H17z" fill="#5746c4" />
      <path d="M18 36c-1-14 5-24 18-25L24 31l-2 15h-8z" fill="#8779da" stroke="none" />
      <path d="M42 8c15 1 20 13 19 24l-2 13-12-6z" fill="#383660" stroke="none" />
      <path d="M22 27c0-12 31-14 31 0v12c-1 11-8 15-16 15-8 0-15-7-15-16z" fill="#ffeadc" />
      <path d="M47 25v15c-1 5-3 9-7 12 8-1 13-6 13-13V26z" fill="#e9bfb4" stroke="none" />
      <path d="M19 30c-1-13 9-21 20-21 14 0 21 11 18 23l-9-11-7 6-2-8-9 10-2-7-9 11z" fill="#5746c4" />
      <path d="m25 16 6-5 9 1-11 8z" fill="#b8aceb" stroke="none" />
      <path d="m49 16 7 10-3 3-7-9z" fill="#383660" stroke="none" />
      <path d="m47 15 7 7" stroke="#b9edf0" strokeWidth="3" />
      <g className="ta-waiting-eyes"><path d="M27 35h6m9 0h6" /><path d="M30 35v3m15-3v3" strokeWidth="2" /></g>
      <path d="m36 42 3 1 3-1" fill="none" />
      <path d="M17 30v10h5V30z" fill="#b9edf0" /><path d="M17 35h-3v5l11 5" fill="none" /><circle cx="26" cy="45" r="2" fill="#e99a61" />
      <path d="m26 50 10 5 12-5c9 2 14 9 15 20H12c1-12 6-18 14-20z" fill="#fffdf8" />
      <path d="m36 55-5 15h15l-6-15z" fill="#222b48" stroke="none" />
      <path d="m26 50 10 5-7 7-5-8m24-4-8 5 7 7 4-8" fill="#d3dce9" />
      <path d="m16 65 7-5m35 5-7-5" fill="none" />
      <path d="m15 55 23 5 23-5v16l-23 4-23-4z" fill="#167b89" />
      <path d="m17 53 21 5 21-5v15l-21 4-21-4z" fill="#fffdf8" />
      <path d="m38 58 21-5v15l-21 4z" fill="#d8edf0" stroke="none" />
      <path d="M38 58v14m-16-14 11 3m-11 2 11 3m10-5 11-3m-11 8 11-3" fill="none" stroke="#748aa0" strokeWidth="1" />
      <path className="ta-waiting-page" d="m38 58 18-9 3 16-21 7z" fill="#f8fcff" stroke="#6b7795" strokeWidth="1" />
      <path d="M15 61c-6-4-7 2-4 5l7 2 3-3zm46 0c6-4 7 2 4 5l-7 2-3-3z" fill="#ffeadc" />
    </g>
  </svg>;
}

export default function AnimeWaiting({ active, message }) {
  const [preference, setPreference] = useState(initialPreference);
  useEffect(() => {
    const sync = event => { if (event.key === STORAGE_KEY || event.key === null) setPreference(initialPreference()); };
    globalThis.addEventListener?.('storage', sync);
    return () => globalThis.removeEventListener?.('storage', sync);
  }, []);
  const toggle = () => {
    const enabled = !preference.enabled;
    let persistent = true;
    try { globalThis.localStorage.setItem(STORAGE_KEY, enabled ? 'on' : 'off'); }
    catch { persistent = false; }
    setPreference({ enabled, persistent });
  };
  if (!active) return null;
  return <section className="ta-anime-waiting" data-testid="anime-waiting" data-animation={preference.enabled ? 'on' : 'off'} aria-label="服务等待状态">
    {preference.enabled && <div className="ta-waiting-art" data-testid="anime-waiting-art"><ReadingNavigator /></div>}
    <div className="ta-waiting-copy"><span className="ta-waiting-label">AI NAVIGATOR</span>{preference.enabled && <strong>导航员研读中…</strong>}<p role="status">{message || '正在等待服务响应。'}</p>
      {!preference.persistent && <small>当前浏览器无法保存动画偏好；本次选择仍有效。</small>}
    </div>
    <button type="button" className="ta-waiting-toggle" onClick={toggle} aria-pressed={preference.enabled} aria-label={preference.enabled ? '关闭等待动画' : '启用等待动画'} title={preference.enabled ? '关闭等待动画，继续显示服务状态' : '启用导航员等待动画'}>{preference.enabled ? '关闭动画' : '启用动画'}</button>
  </section>;
}

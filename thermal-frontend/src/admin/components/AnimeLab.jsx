import { useAppTheme } from '../../theme/useAppTheme.js';
import { HyperLabTitle } from './HyperLab.jsx';

/** Visual chapter labels only; all operational values remain in the API-backed pages. */
export function LabTitle({ code, english, children }) {
  const { themeId } = useAppTheme();
  if (themeId === 'hyper') return <HyperLabTitle code={code} english={english}>{children}</HyperLabTitle>;
  if (themeId !== 'cel') return children;
  return <span className="lab-section-title"><span className="lab-section-code">{code}</span><span><small>{english}</small><span>{children}</span></span></span>;
}

export function LabCoolingDrawing() {
  return <figure className="lab-cooling-drawing" aria-label="液冷模组概念设定图，仅用于界面装饰，不代表仿真结果">
    <div className="lab-drawing-caption"><span>THERMAL SYSTEM / CONCEPT SHEET</span><b>01</b></div>
    <svg viewBox="0 0 320 170" fill="none" aria-hidden="true">
      <path d="M15 137H305M35 24V151M291 24V151" stroke="currentColor" strokeOpacity=".15" strokeDasharray="3 5" />
      <path d="m59 105 67 38 132-73-67-36z" fill="#d6d7ee" stroke="#222b48" strokeWidth="2" />
      <path d="m59 91 67 38 132-73-67-36z" fill="#fffdf8" stroke="#222b48" strokeWidth="2" />
      <path d="m126 129 132-73v14l-132 73z" fill="#5746c4" stroke="#222b48" strokeWidth="2" />
      <path d="M59 91v14l67 38v-14z" fill="#b9b5dd" stroke="#222b48" strokeWidth="2" />
      <path d="m90 91 40 23 95-53-38-21z" fill="#e9eef7" stroke="#222b48" strokeWidth="1.6" />
      <path d="m105 91 26 14 73-41-16-9-60 34 11 6 38-21" stroke="#167b89" strokeWidth="6" strokeLinecap="square" strokeLinejoin="round" />
      <path d="m105 91 26 14 73-41-16-9-60 34 11 6 38-21" stroke="#b9edf0" strokeWidth="2" />
      <path d="m150 38 19-11 30 17-19 11z" fill="#f2b57c" stroke="#222b48" strokeWidth="2" />
      <path d="m150 38 30 17v15l-30-17z" fill="#b35220" stroke="#222b48" strokeWidth="2" />
      <path d="m180 55 19-11v15l-19 11z" fill="#df8351" stroke="#222b48" strokeWidth="2" />
      <path d="m70 78-24-14V43M229 98l40 17h33M168 30V10h63" stroke="#222b48" strokeWidth="1.2" />
      <circle cx="70" cy="78" r="3" fill="#5746c4" /><circle cx="229" cy="98" r="3" fill="#167b89" />
      <text x="16" y="36" fontSize="9" fill="#5746c4" fontFamily="monospace">FLOW PATH</text>
      <text x="245" y="130" fontSize="9" fill="#167b89" fontFamily="monospace">COLD PLATE</text>
      <text x="236" y="14" fontSize="9" fill="#b35220" fontFamily="monospace">HEAT LOAD</text>
    </svg>
    <figcaption>概念设定图 · 非仿真数据</figcaption>
  </figure>;
}

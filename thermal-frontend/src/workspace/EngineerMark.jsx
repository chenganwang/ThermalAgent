export default function EngineerMark({ small = false }) {
  return <svg className={`ta-engineer-mark${small ? ' small' : ''}`} viewBox="0 0 220 190" aria-hidden="true">
    <g className="ta-mark-professional" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 24h176v143H22z" stroke="var(--ta-border)" strokeDasharray="3 6" />
      <path d="M20 95h28V48h55m0 0h63v90h-63m0 0H48v-20" stroke="var(--ta-primary)" strokeWidth="5" />
      <path d="M91 35h32v27H91z" fill="var(--ta-primary-soft)" />
      <path d="M95 41h24m-24 6h24m-24 6h24" stroke="var(--ta-primary)" />
      <rect x="78" y="80" width="53" height="40" rx="3" fill="var(--ta-surface)" />
      <rect x="87" y="88" width="35" height="24" rx="2" fill="var(--ta-primary-soft)" stroke="var(--ta-primary)" />
      <path d="M87 73v7m9-7v7m9-7v7m9-7v7m9-7v7M87 120v7m9-7v7m9-7v7m9-7v7m9-7v7M71 88h7m-7 8h7m-7 8h7m-7 8h7m53-24h7m-7 8h7m-7 8h7m-7 8h7" />
      <circle cx="166" cy="95" r="17" fill="var(--ta-surface)" stroke="var(--ta-primary)" />
      <path d="m157 100 9-15 9 15z" fill="var(--ta-primary-soft)" stroke="var(--ta-primary)" />
      <path d="m39 65 9 7 9-7m100 59 9-7 9 7" stroke="var(--ta-primary)" />
      <path d="M95 143v15m-14 0h46M34 154h23m-23 7h12" stroke="var(--ta-border)" />
      <circle cx="48" cy="118" r="4" fill="var(--ta-primary)" stroke="var(--ta-primary)" />
    </g>
    <g className="ta-mark-character" stroke="#2d3347" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m177 29 7-13 4 14 14 4-14 5-4 13-6-13-12-4z" fill="#edc64c" />
      <path className="ta-mark-rays" d="m23 43 13 4m0-24 8 12m-13 32 12-7m142 87 16-1m-16-19 10 5" fill="none" />
      <ellipse cx="107" cy="176" rx="60" ry="5" fill="#d2c5ac" stroke="none" />
      <path d="m91 145-8 26h22l4-21m6-4 6 25h21l-11-31" fill="#394d83" />
      <path d="m88 117-20 24-13-9 16-30m65 6 14 25-14 8-16-23" fill="#4c77cb" />
      <path d="m63 136-9-9-6 2-2 9 15 8" fill="#ffdbb5" />
      <path d="m83 105 34-7 22 49-60 2z" fill="#5c89de" />
      <path d="m111 102 8 10 7 34 13 1-22-49z" fill="#3558a8" stroke="none" />
      <path d="m84 106 19 15 14-21m-14 21 4 25m-16-14 8-2m18-5 9-2" fill="none" />
      <path d="M68 49c-13 2-15 22-9 37l-7 9 19-2 6 16 15-7 12 6 24-3 18-19-5-34z" fill="#303947" />
      <path d="M72 50c8-20 61-18 69 6l-1 26c-6 19-20 30-37 29-21-1-35-17-37-34z" fill="#ffddb8" />
      <path d="M130 56c8 13 4 30-3 40-5 8-10 11-19 13 18 4 30-11 33-27V56z" fill="#dca68c" stroke="none" />
      <path d="m69 63 10-19 6 18 9-18 13 11 12-9 18 19 4-25-38-14-33 15z" fill="#354054" />
      <path d="M61 46c-1-23 19-36 43-35 27 1 43 16 43 39l-34 1z" fill="#f7d45b" />
      <path d="M123 17c14 13 17 23 17 32l7 1c0-17-8-27-24-33z" fill="#d79b3c" stroke="none" />
      <path d="M96 13v22m18-21v21M56 45q46-8 95 6l-4 8q-46-14-91-4z" fill="#ffe587" />
      <ellipse cx="84" cy="77" rx="8" ry="12" fill="#fff" /><ellipse cx="119" cy="78" rx="8" ry="12" fill="#fff" />
      <ellipse cx="86" cy="79" rx="5.5" ry="9" fill="#365591" strokeWidth="1.6" /><ellipse cx="117" cy="80" rx="5.5" ry="9" fill="#365591" strokeWidth="1.6" />
      <circle cx="87" cy="75" r="2.5" fill="#fff" stroke="none" /><circle cx="118" cy="76" r="2.5" fill="#fff" stroke="none" />
      <path d="m76 64 13-1m23 0 13 3m-30 29q7 7 14 0" fill="none" strokeWidth="2" />
      <ellipse cx="74" cy="91" rx="6" ry="3" fill="#efa6a0" stroke="none" /><ellipse cx="130" cy="92" rx="6" ry="3" fill="#efa6a0" stroke="none" />
      <path d="m136 112 24-7 13 44-28 7z" fill="#fffdf5" /><path d="m141 122 12-4m-9 13 8-3 8 9m-13 7 11-3" fill="none" stroke="#365591" strokeWidth="2" />
      <path d="m137 130 7-5 6 2-1 10-8 2z" fill="#ffddb8" />
    </g>
  </svg>;
}

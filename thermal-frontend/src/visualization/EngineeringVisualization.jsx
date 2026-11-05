import { useId } from 'react';
import { engineeringGraphLayout, engineeringVisualizations, graphValue } from './engineeringVisualization.js';
import './engineeringVisualization.css';

function Parameters({ values }) {
  if (!values?.length) return null;
  return <dl className="ta-graph-parameters">{values.map((parameter, index) => <div key={index}>
    <dt>{parameter.name}{parameter.symbol && parameter.symbol !== parameter.name ? ` (${parameter.symbol})` : ''}</dt>
    <dd>{graphValue(parameter.value)}{parameter.unit ? ` ${parameter.unit}` : ''}{parameter.source ? <small> · {parameter.source}</small> : null}</dd>
  </div>)}</dl>;
}

function Topology({ view }) {
  const marker = `engineering-arrow-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const graph = engineeringGraphLayout(view.nodes, view.edges);
  const labels = new Map(view.nodes.map(node => [node.id, node.label]));
  return <>
    <div className="ta-engineering-graph-scroll" tabIndex={0} role="region" aria-label={`${view.title}，可横向滚动`}>
      <svg viewBox={`0 0 ${graph.width} ${graph.height}`} role="img" aria-label={`${view.title}：${graph.nodes.length}个节点、${graph.edges.length}条连接，完整连接见下方列表`}>
        <title>{view.title}</title>
        <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="var(--ta-primary)" /></marker></defs>
        {graph.edges.map(edge => {
          const dx = edge.to.x - edge.from.x, dy = edge.to.y - edge.from.y;
          const distance = Math.hypot(dx, dy) || 1;
          const trim = Math.min(Math.min(dx ? 78 / Math.abs(dx / distance) : Infinity, dy ? 28 / Math.abs(dy / distance) : Infinity) + 6, distance / 3);
          const x1 = edge.from.x + dx / distance * trim, y1 = edge.from.y + dy / distance * trim;
          const x2 = edge.to.x - dx / distance * trim, y2 = edge.to.y - dy / distance * trim;
          const bend = 12 + (edge.index % 3) * 10;
          const cx = (x1 + x2) / 2 - dy / distance * bend, cy = (y1 + y2) / 2 + dx / distance * bend;
          const path = edge.source === edge.target ? `M${x1 + 40} ${y1} C${x1 + 105} ${y1 - 65},${x1 - 105} ${y1 - 65},${x1 - 40} ${y1}` : `M${x1} ${y1} Q${cx} ${cy},${x2} ${y2}`;
          return <g key={`${edge.id}-${edge.index}`}><title>{`${labels.get(edge.source)} → ${labels.get(edge.target)}：${edge.label}`}</title><path d={path} fill="none" stroke="var(--ta-primary)" strokeWidth="1.8" markerEnd={`url(#${marker})`} /><text x={cx} y={cy - 5} className="ta-engineering-edge-number">{edge.index + 1}</text></g>;
        })}
        {graph.nodes.map(node => <g key={node.id}><title>{`${node.label}${node.description ? `：${node.description}` : ''}`}</title><rect x={node.x - 78} y={node.y - 28} width="156" height="56" rx="8" fill="var(--ta-surface)" stroke="var(--ta-border)" strokeWidth="1.6" /><text x={node.x} y={node.y - 3} textAnchor="middle" className="ta-engineering-node-label">{node.label.length > 13 ? `${node.label.slice(0, 12)}…` : node.label}</text><text x={node.x} y={node.y + 16} textAnchor="middle" className="ta-engineering-node-value">{node.parameters.filter(item => item.value !== null).slice(0, 1).map(item => `${graphValue(item.value)} ${item.unit}`).join('')}</text></g>)}
      </svg>
    </div>
    <details className="ta-engineering-graph-records"><summary>查看完整节点、连接与参数</summary>
      <ul>{view.nodes.map(node => <li key={node.id}><strong>{node.label}</strong>{node.role && ` · ${node.role}`}<p>{node.description}</p><Parameters values={node.parameters} />{node.risks.length > 0 && <p>需核查：{node.risks.join('；')}</p>}</li>)}</ul>
      <ol aria-label="后端声明的图连接">{view.edges.map((edge, index) => <li key={`${edge.id}-${index}`}><strong>{labels.get(edge.source)} → {labels.get(edge.target)}：{edge.label}</strong>{edge.description && <p>{edge.description}</p>}<Parameters values={edge.parameters} />{edge.risks.length > 0 && <p>需核查：{edge.risks.join('；')}</p>}</li>)}</ol>
    </details>
  </>;
}

function Curve({ view }) {
  const { xAxis, yAxis, series } = view.chart;
  const points = series.flatMap(item => item.points);
  const minX = Math.min(...points.map(p => p.x)), maxX = Math.max(...points.map(p => p.x));
  const minY = Math.min(...points.map(p => p.y)), maxY = Math.max(...points.map(p => p.y));
  const xLabel = `${xAxis.label}${xAxis.unit ? ` (${xAxis.unit})` : ''}`;
  const yLabel = `${yAxis.label}${yAxis.unit ? ` (${yAxis.unit})` : ''}`;
  return <>
    <div className="ta-engineering-graph-scroll" tabIndex={0} role="region" aria-label={`${view.title}曲线，可横向滚动`}><svg viewBox="0 0 640 310" role="img" aria-label={`${view.title}；横轴${xLabel}；纵轴${yLabel}`}>
      <title>{`${view.title}：后端提供${points.length}个数值点`}</title>
      <path d="M78 38V242H610" fill="none" stroke="var(--ta-text-muted)" />
      {[0, 0.5, 1].map(fraction => <g key={fraction}><path d={`M78 ${242 - fraction * 190}H610`} stroke="var(--ta-border)" strokeDasharray="3 4" /><text x="70" y={246 - fraction * 190} textAnchor="end" className="ta-engineering-axis">{Number((minY + fraction * (maxY - minY)).toPrecision(5))}</text></g>)}
      {series.map((item, index) => <polyline key={index} points={item.points.map(p => `${78 + (p.x - minX) / (maxX - minX || 1) * 532},${242 - (p.y - minY) / (maxY - minY || 1) * 190}`).join(' ')} fill="none" stroke={index % 2 ? 'var(--ta-success)' : 'var(--ta-primary)'} strokeWidth="2.5" strokeDasharray={index > 1 ? '5 3' : undefined}><title>{item.name}</title></polyline>)}
      <text x="78" y="263" className="ta-engineering-axis">{graphValue(minX)}</text><text x="610" y="263" textAnchor="end" className="ta-engineering-axis">{graphValue(maxX)}</text>
      <text x="344" y="297" textAnchor="middle" className="ta-engineering-axis">{xLabel}</text><text x="78" y="22" className="ta-engineering-axis">{yLabel}</text>
    </svg></div>
    <p>坐标点由后端提供；折线仅连接这些点，不表示新增仿真或测量。</p>
    <details className="ta-engineering-graph-records"><summary>查看曲线原始数值（{points.length}点）</summary>{series.map((item, index) => <table key={index}><caption>{item.name}</caption><thead><tr><th>{xLabel}</th><th>{yLabel}</th></tr></thead><tbody>{item.points.map((point, row) => <tr key={row}><td>{graphValue(point.x)}</td><td>{graphValue(point.y)}</td></tr>)}</tbody></table>)}</details>
  </>;
}

export default function EngineeringVisualization({ response }) {
  return engineeringVisualizations(response).map(view => <section key={view.origin} className="ta-engineering-visualization" data-graph-type={view.type} aria-label={`${view.title}工程图`}>
    <h4>{view.title}</h4>
    {view.errors.map((error, index) => <p key={index} role="alert" className="ta-engineering-graph-warning">{error}</p>)}
    {view.status !== 'ready' ? <p role="status">{view.status === 'invalid' ? view.problem : '工程图尚未生成。'}{view.missing.length > 0 && ` 待补充：${view.missing.join('、')}`}</p> : <>
      <p className="ta-engineering-graph-provenance">{view.generic ? '通用教学示意，需核对实际设备。' : '后端生成的工程示意。'} {view.sourceBased ? '声明关联知识来源，请结合本回复来源核对。' : '未声明已由知识来源验证。'} {view.simulationBased ? '后端标注关联仿真，需核对对应执行记录。' : '不是CFD仿真云图。'}</p>
      {view.partial && <p role="status" className="ta-engineering-graph-warning">热阻网络不完整；此图不能当作完整结温路径。</p>}
      {view.type === 'fault_propagation' && <p className="ta-engineering-graph-warning">节点为候选原因或现象，连接表示可能影响；此图不是设备确诊结果。</p>}
      {view.chart ? <Curve view={view} /> : <Topology view={view} />}
      {view.formula && <p>计算关系：<code>{view.formula}</code></p>}
      {view.tool && <p>计算工具：{view.tool}</p>}
      <Parameters values={view.inputs} />
      {view.assumptions.length > 0 && <p>假设：{view.assumptions.join('；')}</p>}
    </>}
    {(view.warnings.length > 0 || view.limitations.length > 0) && <ul className="ta-engineering-graph-boundaries">{[...new Set([...view.warnings, ...view.limitations])].map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
  </section>);
}

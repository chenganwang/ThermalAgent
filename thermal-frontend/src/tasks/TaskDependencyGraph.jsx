import { useId } from 'react';
import { taskDependencyLayout, taskStatusLabel } from './taskState.js';

export default function TaskDependencyGraph({ steps }) {
  const marker = useId().replace(/:/g, '');
  const graph = taskDependencyLayout(steps);
  if (!graph.nodes.length) return null;
  return <figure className="ta-task-graph"><figcaption>任务依赖图 · 来自服务计划</figcaption><div className="ta-graph-scroll"><svg width={graph.width} height={graph.height} role="img" aria-label="后端声明的步骤依赖关系，完整步骤名称与状态见下方列表">
    <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="var(--ta-text-muted)" /></marker></defs>
    {graph.edges.map(({ from, to }, index) => <path key={index} d={`M${from.x + 155} ${from.y + 30} C${from.x + 172} ${from.y + 30},${to.x - 17} ${to.y + 30},${to.x} ${to.y + 30}`} fill="none" stroke="var(--ta-text-muted)" strokeWidth="1.3" markerEnd={`url(#${marker})`} />)}
    {graph.nodes.map(node => <g key={node.step_id}><title>{`${node.title}：${taskStatusLabel(node.status)}；依赖：${(node.depends_on || []).join('、') || '无'}`}</title><rect x={node.x} y={node.y} width="155" height="60" rx="7" fill={node.status === 'running' ? 'var(--ta-primary-soft)' : 'var(--ta-surface)'} stroke={['failed', 'blocked'].includes(node.status) ? 'var(--ta-danger)' : node.status === 'completed' ? 'var(--ta-success)' : 'var(--ta-border)'} strokeWidth="1.8" /><text x={node.x + 10} y={node.y + 23} fill="var(--ta-text)" fontSize="11">{(node.title || node.step_id).slice(0, 12)}</text><text x={node.x + 10} y={node.y + 43} fill="var(--ta-text-muted)" fontSize="10">{taskStatusLabel(node.status)}</text></g>)}
  </svg></div></figure>;
}

import { resolveHyperState } from './hyperState.js';
import AtelierMotif from './AtelierMotif.jsx';

export default function AtelierActivity({ onTask, onRecords, ...props }) {
  const state = resolveHyperState(props);
  return <section className="atelier-activity" data-state={state.state} aria-label="当前工程协作状态">
    <AtelierMotif /><div><span>{state.label}</span><strong>{state.current?.title || state.title}</strong></div>
    {state.current?.tool_name && <code>{state.current.tool_name}</code>}
    {state.taskId ? <button type="button" onClick={() => onTask(state.taskId)}>展开任务卷宗 <span aria-hidden="true">↗</span></button> : state.state === 'complete' ? <button type="button" onClick={onRecords}>查阅工程记录 <span aria-hidden="true">↗</span></button> : <small>每一步，留有依据</small>}
  </section>;
}

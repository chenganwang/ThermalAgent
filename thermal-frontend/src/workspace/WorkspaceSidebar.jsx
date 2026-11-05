import { CommentOutlined, DeleteOutlined, ExperimentOutlined, FileTextOutlined, PlusOutlined, SettingOutlined } from '@ant-design/icons';
import EngineerMark from './EngineerMark.jsx';
import { useAppTheme } from '../theme/useAppTheme.js';
import { AnimeNavigator } from './AnimeWorkspace.jsx';

export default function WorkspaceSidebar({ conversations, activeConvId, onNew, onSelect, onDelete, onTasks, onEngineering, onSimulation, simulationVisible, task, loading }) {
  const { themeId } = useAppTheme();
  return <aside className="ta-sidebar" data-testid="conversation-history" aria-label="会话与工作区">
    {themeId === 'cel' && <div className="ta-anime-department"><span className="ta-anime-lab-seal" aria-hidden="true">◇</span><div><span>THERMAL SYSTEMS</span><strong>工程研究室</strong><small>RESEARCH TERMINAL / V3</small></div></div>}
    <button className="ta-new-conversation" onClick={onNew}><PlusOutlined />新建工程对话</button>
    <nav className="ta-workspace-nav" aria-label="工程工作区"><span className="ta-nav-caption">工作区 / WORKSPACE</span>
      <button onClick={onTasks} data-testid="open-task-history"><ExperimentOutlined />任务执行记录<span>↗</span></button>
      <button onClick={onEngineering} data-testid="open-engineering-history"><FileTextOutlined />工程历史与对比<span>↗</span></button>
      {simulationVisible && <button onClick={onSimulation} title="打开模型目录、场景目录和模型文件管理"><SettingOutlined />仿真管理 · CFD<span>↗</span></button>}
    </nav>
    <div className="ta-conversation-heading"><span className="ta-nav-caption">最近对话</span><span>{conversations.length}</span></div>
    <nav className="ta-conversation-list" aria-label="历史对话">{conversations.map(conversation => <div className={`ta-conversation-row${activeConvId === conversation.id ? ' active' : ''}`} key={conversation.id}><button className="ta-conversation-select" onClick={() => onSelect(conversation)} aria-current={activeConvId === conversation.id ? 'page' : undefined}><CommentOutlined /><span>{conversation.title}</span></button><button className="ta-conversation-delete" onClick={() => onDelete(conversation.id)} aria-label={`删除对话：${conversation.title}`}><DeleteOutlined /></button></div>)}{conversations.length === 0 && <p className="ta-empty-history">从右侧的问题开始，<br />工程记录将在这里积累。</p>}</nav>
    {themeId === 'cel' ? <AnimeNavigator task={task} loading={loading} /> : <div className="ta-sidebar-note"><EngineerMark small /><div><strong>每一步，都有依据。</strong><p>计算记录 · 物理检查 · 来源追踪</p></div></div>}
  </aside>;
}

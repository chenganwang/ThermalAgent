import { Spin } from 'antd';
import { PaperClipOutlined } from '@ant-design/icons';
import MarkdownContent from '../MarkdownContent.jsx';
import SimulationMessageAttachments from '../SimulationMessageAttachments.jsx';
import KnowledgeSourcesDisclosure from '../KnowledgeSourcesDisclosure.jsx';
import PhysicsValidationCard from '../PhysicsValidationCard.jsx';
import EngineeringRunCard from '../EngineeringRunCard.jsx';
import TaskProgressCard from '../tasks/TaskProgressCard.jsx';
import { buildSimulationPresentation } from '../simulationPresentation.js';
import { buildApiUrl } from '../api/client.js';
import { useAppTheme } from '../theme/useAppTheme.js';
import AnimeWaiting from './AnimeWaiting.jsx';
import { assistantBrief } from './animePresentation.js';
import { HyperWaiting } from '../hyper/index.js';
import { activePendingMessage } from './activeRequest.js';
import EngineeringResultSummary from '../hyper/EngineeringResultSummary.jsx';
import { engineeringResult } from '../hyper/engineeringResult.js';
import { guardMessageIdentity } from '../resultIdentity.js';
import EngineeringVisualization from '../visualization/EngineeringVisualization.jsx';

export default function ConversationMessages({ messages, conversationId, loading, activePendingId, latestSimulationMessageId, onSimulationAction, onOpenTask }) {
  const { themeId } = useAppTheme();
  const pending = activePendingMessage(messages, activePendingId, loading);
  return messages.map((storedMessage, index) => {
    const message = guardMessageIdentity(storedMessage, conversationId);
    const bot = message.role === 'bot';
    const view = bot ? buildSimulationPresentation(message.raw, { action: message.simulationAction }) : null;
    const content = view?.summary || message.content;
    const downloadUrl = message.raw?.metadata?.report?.exports?.[0]?.download_url;
    const hasEngineeringResult = themeId === 'hyper' && bot && !message.pending && Boolean(engineeringResult({ task: message.taskSnapshot, response: message.raw }));
    return <article key={message.id || index} className={`ta-message ${bot ? 'assistant' : 'user'}`} aria-label={bot ? '工程助手回复' : '我的问题'}>
      {themeId === 'cel' && <div className="ta-anime-transcript-label"><span>{bot ? 'AGENT FIELD NOTES' : 'OPERATOR TRANSMISSION'}</span><span>{String(index + 1).padStart(2, '0')} / {bot ? 'RESPONSE' : 'REQUEST'}</span></div>}
      {themeId === 'hyper' && <div className="ta-hyper-transcript-label"><span>{bot ? 'ELYSIA / RESEARCH NOTES' : 'YOUR QUESTION / 工程提问'}</span><span>PAGE {String(index + 1).padStart(2, '0')}</span></div>}
      <div className="ta-message-byline"><span className="ta-message-avatar" aria-hidden="true">{bot ? 'TA' : '我'}</span><strong>{bot ? 'ThermalAgent' : '我的问题'}</strong><span>{message.mode === 'task' ? '工程任务' : message.mode === 'report' ? '工程报告' : bot ? '工程助手' : ''}</span></div>
      <div className="ta-message-body">
        {message.fileName && <div className="ta-file-note"><PaperClipOutlined />{message.fileName} · 仅文件名</div>}
        {hasEngineeringResult && <EngineeringResultSummary task={message.taskSnapshot} response={message.raw} onOpenTask={onOpenTask} />}
        {message.pending ? message !== pending ? <p role="status">这是尚未完成的历史请求。请从任务档案核对记录，或重新发起问题。</p> : themeId === 'hyper' ? <HyperWaiting active task={message.taskSnapshot} message={message} /> : themeId === 'cel' ? <AnimeWaiting active message={assistantBrief(message.taskSnapshot, true).message} /> : <div role="status" className="ta-pending"><Spin size="small" /><span>{message.taskSnapshot ? '任务已受理，执行记录正在更新。' : message.pendingLabel || '正在等待服务响应…'}</span></div> : typeof content === 'string' && content && (hasEngineeringResult ? <details className="ta-hyper-answer-report" open={message.mode === 'report'}><summary>完整工程报告与计算依据</summary><MarkdownContent>{content}</MarkdownContent></details> : <MarkdownContent>{content}</MarkdownContent>)}
        {downloadUrl && <a href={buildApiUrl(downloadUrl)} target="_blank" rel="noreferrer" className="ta-download-link">下载工程报告</a>}
        {message.legacyTask && <p className="ta-muted">当前后端使用兼容问答接口；未提供实时任务事件。</p>}
        {message.taskId && <button className="ta-link-button" onClick={() => onOpenTask(message.taskId)}>从服务重新打开任务记录</button>}
        {message.taskSnapshot && <details className="ta-message-task"><summary>任务计划与执行证据</summary><TaskProgressCard task={message.taskSnapshot} onOpen={onOpenTask} /></details>}
        {bot && !message.pending && <><SimulationMessageAttachments response={message.raw} eventAction={message.simulationAction} onAction={onSimulationAction} actionsEnabled={!loading && message.id === latestSimulationMessageId} />{hasEngineeringResult ? <details className="ta-hyper-proof-details"><summary>物理校验、工具版本与完整 Trace</summary><PhysicsValidationCard response={message.raw} /><EngineeringRunCard response={message.raw} /></details> : <><PhysicsValidationCard response={message.raw} /><EngineeringRunCard response={message.raw} /></>}</>}
        {bot && !message.pending && <EngineeringVisualization response={message.raw} />}
        <KnowledgeSourcesDisclosure sources={message.sources} relatedToSimulation={view?.hasAttachment === true} />
      </div>
    </article>;
  });
}

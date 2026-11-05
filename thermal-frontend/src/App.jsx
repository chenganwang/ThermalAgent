import { lazy, Suspense, useState, useRef, useEffect } from 'react';
import { Segmented, Drawer } from 'antd';
import {
  CommentOutlined,
  FileTextOutlined,
  ExperimentOutlined,
  ArrowUpOutlined,
  PaperClipOutlined,
  CloseOutlined,
  MenuUnfoldOutlined,
  MenuFoldOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import {
  USE_MOCK_RESPONSES,
  answerAgent,
  continueEngineeringTask,
  exportAgentReport,
  getCapabilities,
  getMatlabStatus,
  getReportStatus,
  getSimulationStatus,
  requestFailureMessage,
} from './api/client';
import { subscribeCapabilitiesChanged } from './capabilityEvents';
import { buildModuleStates, moduleStateById } from './moduleState';
import SimulationModeToggle from './SimulationModeToggle';
import { buildSimulationActionRequest, buildSimulationRevisionRequest } from './simulationConversation';
import { isActiveConversationReply, loadConversations, saveConversations } from './conversationStorage';
import ThemeSwitcher from './theme/ThemeSwitcher.jsx';
import { useAppTheme } from './theme/useAppTheme.js';
import { AnimeTaskBar } from './workspace/AnimeWorkspace.jsx';
import EngineerMark from './workspace/EngineerMark.jsx';
import WelcomePanel from './workspace/WelcomePanel.jsx';
import ConversationMessages from './workspace/ConversationMessages.jsx';
import WorkspaceSidebar from './workspace/WorkspaceSidebar.jsx';
import TaskProgressCard from './tasks/TaskProgressCard.jsx';
import { executeVisibleTask } from './tasks/taskTransport.js';
import { engineeringConversationContext, validateContinuationRoute } from './tasks/taskContinuation.js';
import { taskConnectionError, taskStatusLabel } from './tasks/taskState.js';
import './App.css';
import './workspace/animeWorkspace.css';
import { HyperPilot, HyperWelcome } from './hyper/index.js';
import AtelierActivity from './hyper/AtelierActivity.jsx';
import { HyperMissionEmpty, HyperToolShelf } from './workspace/HyperWorkspaceChrome.jsx';
import { activePendingMessage } from './workspace/activeRequest.js';
import HyperWorkspaceControls from './workspace/HyperWorkspaceControls.jsx';
import { assertResultIdentity, captureResultIdentity, replaceOwnedReply, RESULT_IDENTITY_ERROR } from './resultIdentity.js';

// ====== 导入 Mock 数据 ======
import mockCalc from './mock/agent_answer_calculation.json';
import mockReport from './mock/agent_answer_report.json';

const SimulationPanel = lazy(() => import('./SimulationPanel'));
const EngineeringHistoryPanel = lazy(() => import('./engineering/EngineeringHistoryPanel'));
const TaskHistoryPanel = lazy(() => import('./tasks/TaskHistoryPanel'));
const PemWorkspace = lazy(() => import('./pem/PemWorkspace.jsx'));

// ====== 模式配置 ======
const MODES = {
  chat: { label: '对话模式', icon: <CommentOutlined />, placeholder: '输入工程问题…', mockData: mockCalc, responseKey: 'answer', sourcesKey: 'sources' },
  task: { label: '工程任务', icon: <ExperimentOutlined />, placeholder: '描述工程目标、已知参数与约束。Agent 将记录实际计划、工具输入输出和验证…', mockData: mockCalc, responseKey: 'answer', sourcesKey: 'sources' },
  report: { label: '生成报告', icon: <FileTextOutlined />, placeholder: '输入报告需求…', mockData: mockReport, responseKey: 'metadata.report.content', sourcesKey: null },
  simulation: { label: '仿真', icon: <ExperimentOutlined />, placeholder: '', mockData: null, responseKey: null, sourcesKey: null },
  pem: { label: 'PEM 流道初筛', icon: <ExperimentOutlined />, placeholder: '', mockData: null, responseKey: null, sourcesKey: null },
};

function getByPath(obj, path) {
  if (!path) return obj;
  return path.split('.').reduce((acc, key) => acc?.[key], obj);
}

async function loadModeResponse(mode, query, sessionId, selectedFile, simulationRequest = {}, options = {}) {
  // Offline samples have no server-owned conversation. Keep their sample query
  // and content, but do not reuse the fixture's unrelated session identifier.
  if (USE_MOCK_RESPONSES) return { ...MODES[mode].mockData, session_id: null };

  if (mode === 'report') {
    return exportAgentReport({
      query,
      sessionId,
      requestedOutputs: ['report'],
      uploadedModelFilename: selectedFile?.name || null,
      title: query.slice(0, 60) || null,
    }, options);
  }

  return answerAgent({
    query,
    sessionId,
    uploadedModelFilename: selectedFile?.name || null,
    simulationMode: simulationRequest.simulationMode === true,
    simulationAction: simulationRequest.simulationAction || null,
    simulationPlanId: simulationRequest.simulationPlanId || null,
  }, options);
}

function createMessageId(prefix) {
  const randomId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${randomId}`;
}

function App() {
  const { themeId } = useAppTheme();
  const [mode, setMode] = useState('chat');
  const [messages, setMessages] = useState([]);
  const latestSimulationMessageId = messages.findLast(message => message.raw?.metadata?.simulation_plan?.generated)?.id;
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [activePendingId, setActivePendingId] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [conversations, setConversations] = useState(loadConversations);
  const [activeConvId, setActiveConvId] = useState(null);
  const activeConvIdRef = useRef(null);
  const [storageError, setStorageError] = useState(false);
  const [compactLayout, setCompactLayout] = useState(() => globalThis.matchMedia?.('(max-width: 760px)').matches === true);
  const [sidebarOpen, setSidebarOpen] = useState(() => globalThis.matchMedia?.('(max-width: 760px)').matches !== true);
  const [capabilities, setCapabilities] = useState(null);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(!USE_MOCK_RESPONSES);
  const [backendStatus, setBackendStatus] = useState({});
  const [backendError, setBackendError] = useState('');
  const [simulationEnabled, setSimulationEnabled] = useState(false);
  const [revisionPlanId, setRevisionPlanId] = useState(null);
  const [simulationManagementOpen, setSimulationManagementOpen] = useState(false);
  const [engineeringHistoryOpen, setEngineeringHistoryOpen] = useState(false);
  const [taskHistoryOpen, setTaskHistoryOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const taskController = useRef(null);
  const activeRequest = useRef(null);
  const fileInputRef = useRef(null);
  const composerRef = useRef(null);
  const messagesEndRef = useRef(null);
  const lastScrolledMessageId = useRef(null);
  const moduleStates = buildModuleStates({
    capabilities,
    loading: capabilitiesLoading,
    error: backendError,
    useMockResponses: USE_MOCK_RESPONSES,
  });
  const simulationModuleState = moduleStateById(moduleStates, 'simulation');
  const modeOptions = moduleStates
    .filter(moduleState => moduleState.visible && moduleState.id !== 'simulation')
    .map(moduleState => ({
      label: MODES[moduleState.id].label,
      value: moduleState.id,
      icon: MODES[moduleState.id].icon,
      disabled: !moduleState.enabled,
      title: moduleState.reason,
    }));
  modeOptions.splice(1, 0, { label: '工程任务', value: 'task', icon: <ExperimentOutlined /> });
  modeOptions.push({ label: 'PEM 流道初筛', value: 'pem', icon: <ExperimentOutlined /> });
  const unavailableModules = moduleStates.filter(moduleState => moduleState.id !== 'chat' && moduleState.visible && !moduleState.enabled);
  const backendConnected = capabilities !== null || Boolean(backendStatus.report || backendStatus.simulation || backendStatus.matlab);
  const backendLabel = USE_MOCK_RESPONSES
    ? 'Mock 数据'
    : capabilitiesLoading && !backendConnected
      ? '连接后端中'
      : backendError && backendConnected
        ? '后端已连接（状态刷新失败）'
        : backendConnected
          ? '后端已连接'
          : '后端未连接';

  useEffect(() => {
    if (messages.length === 0) return;
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || (themeId === 'hyper' && document.documentElement.dataset.hyperMotion === 'reduced');
    if (themeId === 'hyper') {
      const latest = messages.at(-1);
      // Polling updates must not keep pulling a reader back to the bottom.
      if (latest?.id === lastScrolledMessageId.current) return;
      lastScrolledMessageId.current = latest?.id;
      const scroller = messagesEndRef.current?.parentElement;
      const article = scroller?.querySelector('.ta-message:last-of-type');
      if (scroller && article) {
        const offset = article.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
        scroller.scrollTo({ top: scroller.scrollTop + offset - 12, behavior: reduceMotion ? 'instant' : 'smooth' });
      }
      return;
    }
    messagesEndRef.current?.scrollIntoView({ behavior: reduceMotion ? 'instant' : 'smooth' });
  }, [messages, themeId]);
  useEffect(() => () => { activeRequest.current = null; taskController.current?.abort(); }, []);
  useEffect(() => {
    const media = window.matchMedia?.('(max-width: 760px)');
    if (!media) return undefined;
    const update = event => { setCompactLayout(event.matches); setSidebarOpen(!event.matches); };
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    setRevisionPlanId(null);
  }, [activeConvId, mode]);

  useEffect(() => {
    if (USE_MOCK_RESPONSES) return undefined;

    let cancelled = false;
    let requestSerial = 0;
    let backendController;
    const loadBackendState = async () => {
      const requestId = ++requestSerial;
      backendController?.abort();
      backendController = new AbortController();
      const options = { signal: backendController.signal };
      setCapabilitiesLoading(true);
      const statusPromise = Promise.allSettled([
        getReportStatus(options),
        getSimulationStatus(options),
        getMatlabStatus(options),
      ]);

      try {
        const nextCapabilities = await getCapabilities(options);
        const validPayload = nextCapabilities && typeof nextCapabilities === 'object' && !Array.isArray(nextCapabilities);
        if (!validPayload) throw new Error('capabilities 响应格式无效');
        if (!cancelled && requestId === requestSerial) {
          setCapabilities(nextCapabilities);
          setBackendError('');
        }
      } catch (error) {
        if (!cancelled && requestId === requestSerial) {
          setBackendError(error?.message || 'capabilities 请求失败');
        }
      } finally {
        if (!cancelled && requestId === requestSerial) setCapabilitiesLoading(false);
      }

      const [reportResult, simulationResult, matlabResult] = await statusPromise;
      if (cancelled || requestId !== requestSerial) return;
      setBackendStatus(previous => ({
        report: reportResult.status === 'fulfilled' ? reportResult.value : previous.report,
        simulation: simulationResult.status === 'fulfilled' ? simulationResult.value : previous.simulation,
        matlab: matlabResult.status === 'fulfilled' ? matlabResult.value : previous.matlab,
      }));
    };

    loadBackendState();
    const unsubscribeCapabilitiesChanged = subscribeCapabilitiesChanged(loadBackendState);
    return () => {
      cancelled = true;
      backendController?.abort();
      unsubscribeCapabilitiesChanged();
    };
  }, []);

  useEffect(() => {
    if (mode === 'chat' || mode === 'task' || mode === 'pem') return;
    const selectedModule = moduleStateById(moduleStates, mode);
    if (!selectedModule?.visible || !selectedModule.enabled) setMode('chat');
  }, [mode, moduleStates]);

  useEffect(() => {
    if (activeConvId && conversations.length > 0) setStorageError(!saveConversations(conversations));
  }, [conversations, activeConvId]);

  // ========== 对话管理 ==========
  const createNewConversation = () => {
    const newConv = { id: createMessageId('conv'), title: '新对话', createdAt: new Date().toISOString(), messages: [], mode: 'chat', simulationMode: false };
    setConversations(prev => [newConv, ...prev]);
    activeConvIdRef.current = newConv.id;
    setActiveConvId(newConv.id);
    setMessages([]);
    setMode('chat');
    setSimulationEnabled(false);
  };

  const deleteConversation = (id) => {
    const updated = conversations.filter(c => c.id !== id);
    setConversations(updated);
    setStorageError(!saveConversations(updated));
    if (activeConvId === id) {
      const next = updated[0];
      activeConvIdRef.current = next?.id || null;
      setActiveConvId(next?.id || null);
      setMessages(next?.messages || []);
      setMode(next?.mode || 'chat');
      setSimulationEnabled(next?.simulationMode === true);
    }
  };

  const switchConversation = (conv) => {
    activeConvIdRef.current = conv.id;
    setActiveConvId(conv.id);
    setMessages(conv.messages || []);
    setMode(conv.mode || 'chat');
    setSimulationEnabled(conv.simulationMode === true);
  };

  // ========== 发送消息 ==========
  const sendMessage = async ({ query, outgoingFile = null, simulationAction = null, simulationPlanId = null }) => {
    if (loading || activeRequest.current || (!query && !outgoingFile)) return;
    const requestId = createMessageId('req');
    const convId = activeConvIdRef.current || createMessageId('conv');
    const controller = new AbortController();
    taskController.current = controller;
    activeRequest.current = { requestId, conversationId: convId };
    const userMsg = { id: createMessageId('user'), requestId, conversationId: convId, role: 'user', content: query, query, fileName: outgoingFile?.name || null };
    const thinkingMsg = {
      id: createMessageId('pending'),
      requestId,
      conversationId: convId,
      role: 'bot',
      mode,
      query,
      pending: true,
      simulationAction,
      simulationMode: mode === 'chat' && (simulationEnabled || Boolean(simulationAction)),
      simulationBackend: simulationAction === 'confirm' ? messages.findLast(message => message.raw?.metadata?.simulation_plan?.plan_id === simulationPlanId)?.raw?.metadata?.simulation_plan?.solver_backend || null : null,
      pendingLabel: simulationAction === 'confirm' ? '正在执行仿真…' : '分析中…',
    };
    const pendingMessageId = thinkingMsg.id;
    const newMessages = [...messages, userMsg, thinkingMsg];
    setMessages(newMessages);
    setInput('');
    setSelectedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
    setLoading(true);
    setActivePendingId(pendingMessageId);

    if (!activeConvIdRef.current) {
      const newConv = {
        id: convId,
        title: query.slice(0, 30) || '新对话',
        createdAt: new Date().toISOString(),
        messages: newMessages,
        mode,
        simulationMode: simulationEnabled || Boolean(simulationAction),
      };
      activeConvIdRef.current = convId;
      setConversations(prev => [newConv, ...prev]);
      setActiveConvId(convId);
    } else {
      setConversations(previous => previous.map(conversation => conversation.id === convId ? {
        ...conversation, messages: newMessages, title: conversation.messages.length === 0 ? query.slice(0, 30) || conversation.title : conversation.title,
        mode, simulationMode: simulationEnabled || Boolean(simulationAction),
      } : conversation));
    }

    const owner = { conversationId: convId, requestId, pendingMessageId };
    const commitReply = reply => {
      if (activeRequest.current?.requestId !== requestId) return;
      setMessages(previous => isActiveConversationReply(activeConvIdRef.current, convId) ? replaceOwnedReply(previous, reply, owner) : previous);
      setConversations(previous => previous.map(conversation => conversation.id === convId
        ? { ...conversation, messages: replaceOwnedReply(conversation.messages, reply, owner) } : conversation));
    };

    let responseMode = mode;
    let latestTask = null;
    let taskId = null;
    let legacyTask = false;
    try {
      let data;
      let continuation = { route: 'unhandled' };
      if (!USE_MOCK_RESPONSES && !simulationAction) {
        continuation = validateContinuationRoute(await continueEngineeringTask({
          query, sessionId: convId, ...engineeringConversationContext(messages),
        }, { signal: controller.signal }));
      }
      if (continuation.route === 'clarification') {
        responseMode = 'chat';
        data = { answer: continuation.message, sources: [], metadata: { engineering_continuation: continuation } };
      } else if (continuation.route === 'rag') {
        responseMode = 'chat';
        data = await loadModeResponse('chat', query, convId, outgoingFile, {}, { signal: controller.signal });
      } else if (!USE_MOCK_RESPONSES && !simulationAction && (continuation.route === 'task' || mode === 'task')) {
        responseMode = 'task';
        const completed = await executeVisibleTask({ query, sessionId: convId, requestId, uploadedModelFilename: outgoingFile?.name || null }, {
          acceptedTask: continuation.route === 'task' ? continuation : null,
          signal: controller.signal,
          onSnapshot: snapshot => {
            latestTask = snapshot; taskId = snapshot.task_id;
            commitReply({ ...thinkingMsg, mode: responseMode, taskId, taskSnapshot: snapshot,
              resultIdentity: captureResultIdentity({ task: snapshot, sessionId: convId, requestId }) });
          },
        });
        latestTask = completed.snapshot; legacyTask = completed.legacy;
        data = completed.result || { answer: `任务${taskStatusLabel(latestTask?.status)}。请查看执行记录中的条件和异常反馈。`, sources: [], metadata: {} };
      } else data = await loadModeResponse(mode, query, convId, outgoingFile, {
        simulationMode: mode === 'chat' && (simulationEnabled || Boolean(simulationAction)),
        simulationAction,
        simulationPlanId,
      }, { signal: controller.signal });
      assertResultIdentity({ task: latestTask, response: data, taskId, sessionId: USE_MOCK_RESPONSES ? undefined : convId, requestId, query: latestTask ? query : undefined });
      const config = MODES[responseMode];
      const content = getByPath(data, config.responseKey) || data.answer || JSON.stringify(data, null, 2);
      const sources = config.sourcesKey ? getByPath(data, config.sourcesKey) : [];
      const botMsg = { id: createMessageId('bot'), requestId, conversationId: convId, query, responseQuery: data?.query || null, role: 'bot', mode: responseMode, content, sources, raw: data, simulationAction, taskId, taskSnapshot: latestTask, legacyTask,
        resultIdentity: captureResultIdentity({ task: latestTask, response: data, sessionId: USE_MOCK_RESPONSES ? undefined : convId, requestId }) };
      commitReply(botMsg);
    } catch (error) {
      const botMsg = {
        id: createMessageId('bot'),
        requestId,
        conversationId: convId,
        query,
        role: 'bot',
        mode,
        content: responseMode === 'task' ? taskConnectionError(error, error.taskId || taskId) : requestFailureMessage(error),
        taskId: error.taskId || taskId,
        taskSnapshot: error.code === RESULT_IDENTITY_ERROR ? null : error.taskSnapshot || latestTask,
        sources: [],
        raw: { error: error.message },
        isError: true,
        identityError: error.code === RESULT_IDENTITY_ERROR ? error.code : undefined,
      };
      commitReply(botMsg);
    } finally {
      if (activeRequest.current?.requestId === requestId) {
        activeRequest.current = null;
        taskController.current = null;
        setLoading(false);
        setActivePendingId(null);
      }
    }
  };

  const handleSend = () => {
    if (loading) return;
    if (revisionPlanId) {
      const request = buildSimulationRevisionRequest({ query: input, planId: revisionPlanId });
      if (!request) return;
      setRevisionPlanId(null);
      void sendMessage({ ...request, outgoingFile: selectedFile });
      return;
    }
    void sendMessage({ query: input.trim(), outgoingFile: selectedFile });
  };

  const handleSimulationModeChange = (nextEnabled) => {
    setSimulationEnabled(nextEnabled);
    if (!nextEnabled) setRevisionPlanId(null);
    if (activeConvId) {
      setConversations(previous => previous.map(conversation => (
        conversation.id === activeConvId ? { ...conversation, simulationMode: nextEnabled } : conversation
      )));
    }
  };

  const handleSimulationAction = (action, planId) => {
    if (loading) return;
    setSimulationEnabled(true);
    if (action === 'revise') {
      setRevisionPlanId(planId);
      composerRef.current?.focus();
      return;
    }
    setRevisionPlanId(null);
    const request = buildSimulationActionRequest({ action, planId });
    void sendMessage({ ...request, outgoingFile: null });
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent?.isComposing) { e.preventDefault(); handleSend(); }
  };

  const latestTask = messages.findLast(message => message.taskSnapshot)?.taskSnapshot;
  // A new request must not borrow the previous mission's completion status.
  const navigatorTask = loading ? messages.findLast(message => message.pending)?.taskSnapshot : latestTask;
  const latestAssistantMessage = messages.findLast(message => message.role === 'bot');
  const pendingMessage = activePendingMessage(messages, activePendingId, loading);
  const hyperTask = latestAssistantMessage?.taskSnapshot || null;
  const railTask = themeId === 'hyper' ? hyperTask : latestTask;
  const hyperPilot = themeId === 'hyper' && <HyperPilot task={hyperTask} loading={Boolean(pendingMessage)} pendingMessage={pendingMessage} latestMessage={latestAssistantMessage} mode={mode} />;
  const openTask = taskId => { setSelectedTaskId(taskId || null); setTaskHistoryOpen(true); };
  const chooseExample = (nextMode, query) => {
    setMode(nextMode === 'report' && !moduleStateById(moduleStates, 'report')?.enabled ? 'chat' : nextMode);
    setInput(query); setSimulationEnabled(false); setRevisionPlanId(null); composerRef.current?.focus();
  };
  const closeMobileSidebar = action => { action(); if (compactLayout) setSidebarOpen(false); };
  const sidebar = <WorkspaceSidebar conversations={conversations} activeConvId={activeConvId} onNew={() => closeMobileSidebar(createNewConversation)} onSelect={conversation => closeMobileSidebar(() => switchConversation(conversation))} onDelete={deleteConversation} onTasks={() => closeMobileSidebar(() => openTask(null))} onEngineering={() => closeMobileSidebar(() => setEngineeringHistoryOpen(true))} onSimulation={() => closeMobileSidebar(() => setSimulationManagementOpen(true))} simulationVisible={simulationModuleState?.visible !== false} task={navigatorTask} loading={loading} />;
  const composer = <div className="ta-composer" data-testid="chat-composer">
              {themeId === 'cel' && <AnimeTaskBar task={navigatorTask} loading={loading} onOpen={openTask} />}
              {themeId === 'hyper' && <div className="ta-hyper-composer-label"><span>写下这一页 / A NEW CHAPTER</span><span>{pendingMessage ? '正在等待本次响应' : loading ? '另一会话的请求仍在执行' : '从已知条件开始'}</span></div>}
              {revisionPlanId && <div className="ta-inline-warning" role="status">请补充或修正参数，例如：温差就是60K。<button onClick={() => setRevisionPlanId(null)}>退出补参</button></div>}
              {loading && <div className="ta-inline-warning" role="status"><span>{pendingMessage ? '本次请求正在等待响应。' : '另一会话的请求正在等待响应。'}停止等待不会取消后台执行。</span><button type="button" onClick={() => taskController.current?.abort()} aria-label="停止等待本次请求">停止等待</button></div>}
              {selectedFile && <div className="ta-file-tag"><PaperClipOutlined /><span>{selectedFile.name}（仅记录文件名，未上传内容）</span><button className="ta-icon-button" aria-label="移除文件名" onClick={() => { setSelectedFile(null); fileInputRef.current.value = ''; }}><CloseOutlined /></button></div>}
              <div className="ta-composer-surface"><label className="ta-sr-only" htmlFor="engineering-composer">工程问题</label><textarea id="engineering-composer" ref={composerRef} value={input} onChange={event => setInput(event.target.value)} onKeyDown={handleKeyDown} placeholder={revisionPlanId ? '补充当前仿真计划的参数…' : MODES[mode].placeholder} rows={themeId === 'hyper' ? 2 : 3} />
                <div className="ta-composer-toolbar"><div className="ta-composer-tools"><input type="file" ref={fileInputRef} onChange={event => { if (event.target.files[0]) setSelectedFile(event.target.files[0]); }} hidden /><button className="ta-icon-button" onClick={() => fileInputRef.current?.click()} title="记录模型文件名（文件内容不上传）" aria-label="记录模型文件名"><PaperClipOutlined /></button>{mode === 'chat' && simulationModuleState?.visible !== false && <SimulationModeToggle enabled={simulationEnabled} available={simulationModuleState?.enabled === true} reason={simulationModuleState?.reason || ''} onChange={handleSimulationModeChange} />}{mode === 'task' && <span className="ta-composer-mode">实际计划 · 工具执行 · 验证</span>}</div><button className="ta-send-button" onClick={handleSend} disabled={loading || (!input.trim() && !selectedFile)} aria-label={loading ? '请求进行中' : mode === 'task' ? '提交工程任务' : '发送问题'}>{loading ? '正在处理' : mode === 'task' ? '提交任务' : '发送'}<ArrowUpOutlined /></button></div>
              </div><div className="ta-composer-footnote"><span>Enter 发送 · Shift + Enter 换行</span><span>{mode === 'task' ? '不自动重试未知提交；可从任务历史核对。' : '工程结论请结合参数、来源与校验依据复核。'}</span></div>
            </div>;
  return <div className="ta-workspace">
    <a className="ta-skip-link" href="#engineering-composer">跳到问题输入</a>
    <header className="ta-app-header">
      <div className="ta-brand"><button className="ta-icon-button ta-menu-toggle" onClick={() => setSidebarOpen(value => !value)} aria-expanded={sidebarOpen} aria-label={sidebarOpen ? '折叠侧边栏' : '展开侧边栏'}>{sidebarOpen ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />}</button><span className="ta-brand-symbol" aria-hidden="true">T<span>∿</span></span><div><h1>{themeId === 'hyper' ? 'ThermalAgent' : themeId === 'cel' ? 'THERMAL AGENT' : 'ThermalAgent'}<span className="ta-version">{themeId === 'hyper' ? 'Hyper Fun' : themeId === 'cel' ? 'ANIME / V3' : 'V2.1'}</span></h1><p>{themeId === 'hyper' ? 'ELYSIAN ATELIER / 花与书的工程手记' : themeId === 'cel' ? 'ENGINEERING INTELLIGENCE SYSTEM' : 'ENGINEERING INTELLIGENCE'}</p></div></div>
      <div className="ta-header-right"><span className={`ta-connection ${backendConnected ? 'connected' : ''}`} title={backendError || backendLabel}><i aria-hidden="true" />{backendLabel}</span><ThemeSwitcher /><a href="/admin" className="ta-admin-link" title="打开管理工作台"><SettingOutlined /><span>管理工作台</span></a></div>
    </header>
    <div className={`ta-workspace-grid${sidebarOpen ? '' : ' sidebar-closed'}`}>
      {!compactLayout && sidebarOpen && (themeId === 'hyper' ? <div className="ta-hyper-command-column">{sidebar}</div> : sidebar)}
      <main className="ta-main-workspace">
        <div className="ta-workspace-topbar"><div><span className="ta-eyebrow">{mode === 'pem' ? 'PEM FLOWFIELD' : mode === 'task' ? 'ENGINEERING TASK' : mode === 'report' ? 'ENGINEERING REPORT' : 'DESIGN CONVERSATION'}</span><h2>{mode === 'pem' ? 'PEM 流道初筛' : mode === 'task' ? '任务规划与执行' : mode === 'report' ? '工程报告' : '工程对话'}</h2></div><Segmented options={modeOptions} value={mode} onChange={value => { setMode(value); if (value === 'task' || value === 'pem') setSimulationEnabled(false); }} size="middle" />{themeId === 'hyper' && mode !== 'pem' && <HyperWorkspaceControls mode={mode} />}</div>
        {storageError && <div className="ta-inline-warning" role="alert">浏览器无法保存历史，本次对话仍可继续。</div>}
        {unavailableModules.length > 0 && <div className="ta-module-status" role="status">{unavailableModules.map(item => <span key={item.id}>{MODES[item.id].label}：{item.reason}</span>)}</div>}
        {mode === 'pem' ? <Suspense fallback={<div role="status" className="ta-loading-panel">正在加载 PEM 研究工作区…</div>}><PemWorkspace /></Suspense> : <div className={`ta-conversation-workarea${themeId === 'hyper' && messages.length === 0 ? ' atelier-home-workarea' : mode === 'task' || latestTask ? ' with-execution' : ''}`}>
          <div className="ta-chat-column">
            {themeId === 'hyper' && messages.length > 0 && <AtelierActivity task={hyperTask} loading={Boolean(pendingMessage)} pendingMessage={pendingMessage} latestMessage={latestAssistantMessage} mode={mode} onTask={openTask} onRecords={() => setEngineeringHistoryOpen(true)} />}
            <div className="ta-messages" data-testid="chat-message-list">
              {messages.length === 0 && (themeId === 'hyper' ? <HyperWelcome onExample={chooseExample} composer={composer} /> : <WelcomePanel onExample={chooseExample} />)}
              <ConversationMessages messages={messages} conversationId={activeConvId} loading={loading} activePendingId={activePendingId} latestSimulationMessageId={latestSimulationMessageId} onSimulationAction={handleSimulationAction} onOpenTask={openTask} />
              <div ref={messagesEndRef} />
            </div>
            {(themeId !== 'hyper' || messages.length > 0) && composer}
          </div>
          {(themeId === 'hyper' ? messages.length > 0 : mode === 'task' || latestTask) && <aside className="ta-execution-rail" aria-label="任务观测">{themeId === 'hyper' && hyperPilot}{railTask ? <TaskProgressCard task={railTask} compact onOpen={openTask} /> : themeId === 'hyper' ? <HyperMissionEmpty loading={Boolean(pendingMessage)} onTasks={() => openTask(null)} /> : <div className="ta-task-empty"><span className="ta-eyebrow">EXECUTION OBSERVER</span><h3>把目标拆成可检查的步骤</h3><EngineerMark /><p>提交工程任务后，这里显示服务实际生成的计划、正在运行的工具和事件。</p><p className="ta-muted">尚未提交任务。没有估算进度或模拟工具输出。</p><button className="ta-link-button" onClick={() => openTask(null)}>查看历史任务 →</button></div>}{themeId === 'hyper' && <HyperToolShelf matlabStatus={backendStatus.matlab} simulationVisible={simulationModuleState?.visible !== false} onSimulation={() => setSimulationManagementOpen(true)} onEngineering={() => setEngineeringHistoryOpen(true)} />}</aside>}
        </div>}
      </main>
    </div>
    {compactLayout && <Drawer className="ta-mobile-navigation" title="工程工作区" placement="left" size={274} open={sidebarOpen} onClose={() => setSidebarOpen(false)} styles={{ body: { padding: 0 } }}>{sidebar}</Drawer>}
    <Drawer title="仿真管理" placement="right" size="min(920px, 96vw)" open={simulationManagementOpen} onClose={() => setSimulationManagementOpen(false)} styles={{ body: { padding: 0 } }}><Suspense fallback={<div role="status" className="ta-loading-panel">正在加载仿真管理…</div>}><SimulationPanel active={simulationManagementOpen} enabled={simulationModuleState?.enabled === true} reason={simulationModuleState?.reason || ''} useMockResponses={USE_MOCK_RESPONSES} /></Suspense></Drawer>
    <Drawer title="工程历史与对比" placement="right" size="min(1040px, 96vw)" open={engineeringHistoryOpen} onClose={() => setEngineeringHistoryOpen(false)} styles={{ body: { padding: 0 } }}><Suspense fallback={<div role="status" className="ta-loading-panel">正在加载工程历史…</div>}><EngineeringHistoryPanel active={engineeringHistoryOpen} useMockResponses={USE_MOCK_RESPONSES} /></Suspense></Drawer>
    <Drawer title="工程任务记录与恢复" placement="right" size="min(1140px, 98vw)" open={taskHistoryOpen} onClose={() => setTaskHistoryOpen(false)} styles={{ body: { padding: 0 } }}><Suspense fallback={<div role="status" className="ta-loading-panel">正在读取任务记录…</div>}><TaskHistoryPanel active={taskHistoryOpen} initialTaskId={selectedTaskId} useMockResponses={USE_MOCK_RESPONSES} /></Suspense></Drawer>
  </div>;
}

export default App;

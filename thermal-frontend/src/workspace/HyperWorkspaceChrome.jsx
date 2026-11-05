export function HyperMissionEmpty({ loading, onTasks }) {
  return <section className="ta-hyper-rail-empty" aria-label="Mission 等待区">
    <header><span>RESEARCH JOURNAL</span><span aria-hidden="true">✦</span></header>
    
    <h3>{loading ? '等待工程回执' : '下一页，\n从一个问题开始。'}</h3>
    <p>{loading ? '请求已发出。若返回工程任务计划，这里会显示实际步骤与工具。' : '发送一个工程目标，一起连接知识、计算与验证。'}</p>
    <button type="button" className="ta-link-button" onClick={onTasks}>打开任务档案 ↗</button>
  </section>;
}

export function HyperToolShelf({ matlabStatus, simulationVisible, onSimulation, onEngineering }) {
  const matlabLabel = !matlabStatus ? '状态尚未读取' : matlabStatus.connected && matlabStatus.uses_real_matlab
    ? '真实 MATLAB 已连接' : matlabStatus.is_mock ? '当前为 Mock' : matlabStatus.enabled === false ? '当前未启用' : '连接状态见仿真管理';
  return <section className="ta-hyper-tool-shelf" aria-label="工程工具入口">
    <header><span>INSTRUMENTS / 工具</span><span aria-hidden="true">↗</span></header>
    <button type="button" onClick={onEngineering}><strong>Reference Solver / 工程计算</strong><small>参考模型 · 工程历史 · 方案对比</small></button>
    {simulationVisible && <button type="button" onClick={onSimulation}><strong>MATLAB / CFD</strong><small>{matlabLabel}</small></button>}
    <p>选择工具入口查看模型、适用范围和执行记录。</p>
  </section>;
}

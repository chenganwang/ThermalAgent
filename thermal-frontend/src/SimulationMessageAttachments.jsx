import ExecutionEvidenceCard from './ExecutionEvidenceCard';
import SimulationErrorCard from './SimulationErrorCard';
import SimulationExecutionCard from './SimulationExecutionCard';
import SimulationPlanCard from './SimulationPlanCard';
import SimulationResultCard from './SimulationResultCard';
import { buildSimulationPresentation } from './simulationPresentation';


export default function SimulationMessageAttachments({ response, eventAction = null, onAction, actionsEnabled = true }) {
  const view = buildSimulationPresentation(response, { action: eventAction });
  if (!view.hasAttachment) return null;
  const { mode, plan, matlab } = view.raw;
  return (
    <div data-testid="simulation-message-attachments">
      {view.showPlan && <SimulationPlanCard plan={plan} mode={mode} matlab={matlab} onAction={onAction} actionsEnabled={actionsEnabled} />}
      {view.showExecution && <SimulationExecutionCard view={view.execution} />}
      {view.showResult && <SimulationResultCard view={view.result} />}
      {view.showEvidence && <ExecutionEvidenceCard view={view.evidence} />}
      {view.showError && <SimulationErrorCard view={view.error} />}
      {view.showCancelled && <div role="status" style={{ marginTop: 10, color: 'var(--ta-text-muted)' }}>仿真计划已取消，未执行求解器。</div>}
      {view.showStatus && <div role="status" data-testid="simulation-status" style={{ marginTop: 10, color: 'var(--ta-text-muted)' }}>仿真状态：{view.statusLabel}</div>}
    </div>
  );
}

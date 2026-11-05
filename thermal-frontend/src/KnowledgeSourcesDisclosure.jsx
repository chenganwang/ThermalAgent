import { buildKnowledgeSourcesPresentation } from './simulationPresentation';


export default function KnowledgeSourcesDisclosure({ sources, relatedToSimulation = false }) {
  const view = buildKnowledgeSourcesPresentation(sources, { relatedToSimulation });
  if (view.items.length === 0) return null;
  return (
    <details
      data-testid={relatedToSimulation ? 'simulation-related-sources' : 'knowledge-sources'}
      style={{ marginTop: 12, background: 'var(--ta-surface-muted)', border: '1px solid var(--ta-border)', borderRadius: 10, padding: '8px 12px', fontSize: 12, color: 'var(--ta-text-muted)' }}
    >
      <summary style={{ color: 'var(--ta-primary)', cursor: 'pointer' }}>{view.title} ({view.items.length})</summary>
      {view.items.map(item => (
        <div key={item.key} style={{ marginTop: 10 }}>
          <strong style={{ color: 'var(--ta-text-muted)' }}>{item.title}</strong>
          {item.locator && <div>{item.locator}</div>}
          {item.preview && <p style={{ margin: '4px 0 0', lineHeight: 1.5 }}>{item.preview}</p>}
        </div>
      ))}
    </details>
  );
}


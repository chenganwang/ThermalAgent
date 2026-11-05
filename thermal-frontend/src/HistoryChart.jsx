import { Typography } from 'antd';
import { fluentMetric, historyAxis, historySeries } from './fluent/fluentPresentation.js';
import { useAppTheme } from './theme/useAppTheme.js';

export default function HistoryChart({ history, isMock }) {
  const { chart } = useAppTheme();
  const points = historySeries(history).slice(-300);
  if (points.length < 2) return null;
  const axis = historyAxis(history);
  const axisLabel = `${axis.label}${axis.unit ? ` (${axis.unit})` : ''}`;
  const xMin = Math.min(...points.map(point => point[0]));
  const xMax = Math.max(...points.map(point => point[0]));
  const yMin = Math.min(...points.map(point => point[1]));
  const yMax = Math.max(...points.map(point => point[1]));
  const line = points.map(([x, y]) => `${38 + ((x - xMin) / (xMax - xMin || 1)) * 444},${114 - ((y - yMin) / (yMax - yMin || 1)) * 90}`).join(' ');
  return (
    <figure className="ta-history-chart" style={{ margin: '16px 0', border: `1px solid ${chart.grid}`, color: chart.text, background: chart.background, borderRadius: 8, padding: 12 }}>
      <figcaption>{isMock ? 'Mock 演示 · ' : ''}{history.name}{history.unit ? ` (${history.unit})` : ''} · {axis.spatial ? '空间分布' : '监测曲线'} · {points.length} 个显示点</figcaption>
      <svg viewBox="0 0 520 165" role="img" aria-label={`${isMock ? 'Mock 演示：' : ''}${history.name} 随${axisLabel}的变化`} style={{ width: '100%', maxHeight: 190 }}>
        <title>{`${history.name}：${fluentMetric(yMin, history.unit)} 至 ${fluentMetric(yMax, history.unit)}`}</title>
        <path d="M38 15V120H490" fill="none" stroke="currentColor" opacity="0.4" />
        <polyline points={line} fill="none" stroke={chart.primary} strokeWidth="2.5" />
        <text x="38" y="139" fill="currentColor" fontSize="11">{xMin}</text>
        <text x="482" y="139" textAnchor="end" fill="currentColor" fontSize="11">{xMax}</text>
        <text x="260" y="158" textAnchor="middle" fill="currentColor" fontSize="11">{axisLabel}</text>
      </svg>
      <Typography.Text type="secondary">数值范围：{fluentMetric(yMin, history.unit)} ～ {fluentMetric(yMax, history.unit)}。{isMock ? '演示数据，不能用于真实工程结论。' : axis.spatial ? '空间分布本身不能作为收敛判据。' : '监测曲线本身不代表已收敛。'}</Typography.Text>
    </figure>
  );
}


export const GRAPH_TITLES = Object.freeze({
  thermal_path: '散热路径', liquid_loop: '液冷回路', thermal_resistance_network: '热阻网络',
  rack_airflow_path: '机柜气流路径', rack_liquid_cooling_path: '机柜液冷回路',
  server_structure: '服务器散热结构', flow_temperature_curve: '流量—温升关系', fault_propagation: '异常影响链',
});

const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
const text = value => typeof value === 'string' ? value : '';
const strings = value => Array.isArray(value) ? value.filter(item => typeof item === 'string' && item.trim()) : [];
const errorMessages = value => Array.isArray(value) ? value.map(item => typeof item === 'string' ? item : text(item?.message)).filter(Boolean) : [];
const finite = value => typeof value === 'number' && Number.isFinite(value);
export const graphValue = value => finite(value) ? String(value) : typeof value === 'string' && value.trim() ? value : '未提供有效值';
const scalar = value => finite(value) || typeof value === 'string' ? value : null;

function parameters(value) {
  return (Array.isArray(value) ? value : []).filter(item => item && typeof item === 'object').map(item => ({
    name: text(item.name) || text(item.symbol) || '参数', symbol: text(item.symbol), value: scalar(item.value), unit: text(item.unit), source: text(item.source),
  }));
}

function numericParameter(name, value, unit) {
  return { name, value: finite(value) ? value : null, unit, source: '后端计算图' };
}

function numericFields(item, fields) {
  return fields.filter(([key]) => Object.hasOwn(item, key)).map(([key, name, unit]) => numericParameter(name, item[key], unit));
}

function chartView(raw) {
  const chart = object(raw);
  const x = object(chart.x_axis), y = object(chart.y_axis);
  if (!text(x.label) || !text(y.label) || !text(x.unit) || !text(y.unit) || !Array.isArray(chart.series) || !chart.series.length || chart.series.length > 12) return null;
  const series = [];
  for (const item of chart.series) {
    if (!Array.isArray(item?.points) || item.points.length < 2 || item.points.length > 2000) return null;
    const points = item.points.map(point => ({ x: point?.x, y: point?.y }));
    if (points.some((point, index) => !finite(point.x) || !finite(point.y) || (index > 0 && point.x <= points[index - 1].x))) return null;
    series.push({ name: text(item.name) || `曲线 ${series.length + 1}`, points });
  }
  const allPoints = series.flatMap(item => item.points);
  const xs = allPoints.map(point => point.x), ys = allPoints.map(point => point.y);
  if (!finite(Math.max(...xs) - Math.min(...xs)) || !finite(Math.max(...ys) - Math.min(...ys))) return null;
  return { xAxis: { label: x.label, unit: text(x.unit) }, yAxis: { label: y.label, unit: text(y.unit) }, series };
}

function projectGraph(container, origin) {
  const graph = object(container.graph);
  const type = text(graph.graph_type) || text(container.graph_type);
  const missing = strings(container.missing_parameters);
  const errors = [...new Set([...errorMessages(container.errors), ...errorMessages(graph.errors)])];
  const warnings = [...new Set([...strings(container.warnings), ...strings(graph.warnings)])];
  const limitations = [...new Set([...strings(container.limitations), ...strings(graph.limitations)])];
  if (container.generated !== true) {
    return type || missing.length || errors.length ? { origin, type, title: GRAPH_TITLES[type] || '工程图', status: 'unavailable', missing, errors, warnings, limitations } : null;
  }
  const view = { origin, type, title: text(graph.title) || GRAPH_TITLES[type] || '工程图', status: 'ready', missing, errors, warnings, limitations,
    generic: graph.generic_template === true, sourceBased: graph.source_based === true,
    simulationBased: graph.simulation_based === true || graph.cfd_executed === true,
    partial: container.partial_graph === true || container.incomplete_network === true || graph.partial_graph === true || graph.incomplete_network === true,
    formula: text(graph.formula), assumptions: strings(graph.assumptions), tool: text(graph.calculation_tool_name),
    inputs: Object.entries(object(graph.inputs)).filter(([, value]) => value === null || finite(value) || typeof value === 'string' || (Array.isArray(value) && value.length === 2 && value.every(finite)))
      .map(([name, value]) => ({ name, value: Array.isArray(value) ? `${value[0]} → ${value[1]}` : scalar(value), unit: '', source: text(object(graph.parameter_sources)[name]) })),
  };
  if (!Object.hasOwn(GRAPH_TITLES, type) || (container.graph_type && graph.graph_type && container.graph_type !== graph.graph_type)) {
    return { ...view, status: 'invalid', problem: '图类型未支持或声明不一致，未绘制。' };
  }
  if (type === 'flow_temperature_curve') {
    const chart = chartView(graph.chart);
    return chart ? { ...view, chart, nodes: [], edges: [] } : { ...view, status: 'invalid', problem: '曲线缺少有效坐标、单位标注或有限且递增的数据点，未绘制。' };
  }
  if (!Array.isArray(graph.nodes) || !graph.nodes.length || graph.nodes.length > 100 || !Array.isArray(graph.edges) || graph.edges.length > 300) {
    return { ...view, status: 'invalid', problem: '图节点或连接结构不完整，未绘制。' };
  }
  const ids = graph.nodes.map(node => text(node?.id));
  if (ids.some(id => !id.trim()) || new Set(ids).size !== ids.length || graph.edges.some(edge => !ids.includes(edge?.source) || !ids.includes(edge?.target))) {
    return { ...view, status: 'invalid', problem: '图包含重复节点或未声明的连接端点，未绘制。' };
  }
  const nodes = graph.nodes.map(node => ({ id: node.id, label: text(node.label) || node.id, role: text(node.role), description: text(node.description), risks: strings(node.risks),
    parameters: [...parameters(node.engineering_parameters), ...numericFields(node, [['temperature_c', '节点温度', '°C']])],
  }));
  const edges = graph.edges.map((edge, index) => ({ id: text(edge.id) || `edge-${index}`, source: edge.source, target: edge.target,
    label: text(edge.label) || text(edge.mechanism) || '连接', description: text(edge.description), direction: text(edge.direction), risks: strings(edge.risks),
    parameters: [...parameters(edge.engineering_parameters), ...numericFields(edge, [
      ['resistance_k_per_w', '热阻', 'K/W'], ['delta_t_c', '温差', 'K'], ['heat_flow_w', '热流', 'W'],
    ])],
  }));
  return { ...view, nodes, edges };
}

/** Only explicitly generated message-owned graphs are projected; no values or topology are inferred. */
export function engineeringVisualizations(response) {
  const metadata = object(response?.metadata);
  const graphs = [];
  for (const origin of ['thermal_path', 'visualization']) {
    const view = projectGraph(object(metadata[origin]), origin);
    if (!view) continue;
    // A solved thermal network is the more specific representation of that type.
    if (origin === 'visualization' && graphs.some(item => item.type === view.type && item.status === 'ready')) continue;
    graphs.push(view);
  }
  return graphs;
}

/** Circular layout preserves cycles and parallel edges without relabelling them as a task DAG. */
export function engineeringGraphLayout(nodes, edges) {
  const width = Math.max(500, Math.min(900, nodes.length * 90));
  const height = Math.max(300, Math.min(700, nodes.length * 65));
  const placed = nodes.map((node, index) => {
    const angle = -Math.PI / 2 + index * Math.PI * 2 / nodes.length;
    return { ...node, x: width / 2 + Math.cos(angle) * (width / 2 - 94), y: height / 2 + Math.sin(angle) * (height / 2 - 48) };
  });
  const byId = new Map(placed.map(node => [node.id, node]));
  return { width, height, nodes: placed, edges: edges.map((edge, index) => ({ ...edge, index, from: byId.get(edge.source), to: byId.get(edge.target) })) };
}

import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { readFileSync } from 'node:fs';
import { engineeringVisualizations, graphValue } from './engineeringVisualization.js';

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
const { default: ConversationMessages } = await vite.ssrLoadModule('/src/workspace/ConversationMessages.jsx');
const { ThemeContext } = await vite.ssrLoadModule('/src/theme/useAppTheme.js');
after(() => vite.close());

const graph = (type = 'thermal_path') => ({
  graph_type: type, title: '本次工程结构', generic_template: true, source_based: false, simulation_based: false,
  nodes: [{ id: 'heat', label: '芯片输入', description: '测试中声明的热源', engineering_parameters: [{ name: '功率', value: 812, unit: 'W', source: 'query' }] }, { id: 'sink', label: '冷却边界' }],
  edges: [{ id: 'transfer', source: 'heat', target: 'sink', label: '传热方向' }],
  warnings: ['通用结构，需核对实际设备'], limitations: ['未执行CFD'],
});
const response = value => ({ metadata: { visualization: { generated: true, graph_type: value.graph_type, graph: value } } });
function renderConversation(raw, extra = {}, themeId = 'engineering') {
  return renderToStaticMarkup(React.createElement(ThemeContext.Provider, { value: { themeId } },
    React.createElement(ConversationMessages, { conversationId: 'conv-a', loading: false, messages: [{ id: 'answer', role: 'bot', content: '回答正文', raw, ...extra }] })));
}

test('actual conversation messages render backend engineering graph instead of dropping metadata', () => {
  const html = renderConversation(response(graph()));
  assert.match(html, /data-graph-type="thermal_path"/);
  assert.match(html, /芯片输入/);
  assert.match(html, /冷却边界/);
  assert.match(html, /812/);
  assert.match(html, /传热方向/);
  assert.match(html, /未执行CFD/);
});

test('all declared topologies render their own nodes and directed connections in the conversation', () => {
  for (const type of ['thermal_resistance_network', 'liquid_loop', 'server_structure', 'fault_propagation', 'rack_airflow_path', 'rack_liquid_cooling_path']) {
    const value = graph(type);
    value.edges.push({ source: 'sink', target: 'heat', label: '真实声明的回路边' });
    const html = renderConversation(response(value));
    assert.match(html, new RegExp(`data-graph-type="${type}"`));
    assert.match(html, /marker-end="url\(#engineering-arrow-/);
    assert.match(html, /冷却边界 → 芯片输入：真实声明的回路边/);
    assert.doesNotMatch(html, /任务依赖图/);
    if (type === 'fault_propagation') assert.match(html, /不是设备确诊结果/);
  }
});

const curve = () => ({ ...graph('flow_temperature_curve'), title: '水冷流量与温升',
  formula: 'DeltaT = Q / (m_dot * cp)', calculation_tool_name: 'coolant_temperature_rise',
  inputs: { Q_W: 840, cp_J_kgK: 4200, flow_range: [0.01, 0.05] }, parameter_sources: { Q_W: '用户输入', cp_J_kgK: '用户输入' },
  assumptions: ['稳态、常物性'],
  chart: { x_axis: { label: '质量流量', unit: 'kg/s' }, y_axis: { label: '冷却液温升', unit: 'K' },
    series: [{ name: '服务端稳态计算点', points: [{ x: 0.01, y: 20 }, { x: 0.02, y: 10 }, { x: 0.05, y: 4 }] }] },
});

test('flow-rise curve renders unchanged backend points, axes, formula and input provenance', () => {
  const raw = response(curve());
  const before = JSON.stringify(raw);
  const view = engineeringVisualizations(raw)[0];
  assert.deepEqual(view.chart.series[0].points, [{ x: 0.01, y: 20 }, { x: 0.02, y: 10 }, { x: 0.05, y: 4 }]);
  const html = renderConversation(raw);
  assert.match(html, /<polyline/);
  assert.match(html, /质量流量 \(kg\/s\)/);
  assert.match(html, /冷却液温升 \(K\)/);
  assert.match(html, /0.05<\/td><td>4/);
  assert.match(html, /840/);
  assert.match(html, /用户输入/);
  assert.match(html, /0.01 → 0.05/);
  assert.doesNotMatch(html, /未提供有效值/);
  assert.match(html, /DeltaT = Q/);
  assert.match(html, /稳态、常物性/);
  assert.equal(JSON.stringify(raw), before);
});

test('missing curve inputs remain an explicit incomplete result with no invented SVG or zero series', () => {
  const raw = { metadata: { visualization: { generated: false, graph_type: 'flow_temperature_curve', missing_parameters: ['cp', '流量范围'], limitations: ['需要物性和边界'] } } };
  const html = renderConversation(raw);
  assert.match(html, /工程图尚未生成/);
  assert.match(html, /cp、流量范围/);
  assert.match(html, /需要物性和边界/);
  assert.doesNotMatch(html, /<svg|<polyline/);
});

test('unsafe or ambiguous coordinates reject the curve instead of coercing or dropping bad points', () => {
  for (const value of [NaN, Infinity, true, null, '0.02']) {
    const data = curve(); data.chart.series[0].points[1].x = value;
    assert.equal(engineeringVisualizations(response(data))[0].status, 'invalid');
    assert.doesNotMatch(renderConversation(response(data)), /<polyline/);
  }
  const descending = curve(); descending.chart.series[0].points.reverse();
  assert.equal(engineeringVisualizations(response(descending))[0].status, 'invalid');
  const unitless = curve(); delete unitless.chart.y_axis.unit;
  assert.equal(engineeringVisualizations(response(unitless))[0].status, 'invalid');
  const overflow = curve(); overflow.chart.series[0].points[0].y = -1e308; overflow.chart.series[0].points[1].y = 1e308;
  assert.equal(engineeringVisualizations(response(overflow))[0].status, 'invalid');
});

test('backend rejected graph parameters remain visible separately from missing inputs', () => {
  const raw = { metadata: { visualization: { generated: false, graph_type: 'flow_temperature_curve', missing_parameters: [], errors: ['流量区间必须为正数', { message: '密度必须为有限正数', private_debug: 'internal-secret' }] } } };
  const html = renderConversation(raw);
  assert.match(html, /流量区间必须为正数/);
  assert.match(html, /密度必须为有限正数/);
  assert.doesNotMatch(html, /待补充|internal-secret|<polyline/);
});

test('unknown graph types, duplicate IDs and dangling edges show a failure instead of fabricated topology', () => {
  const cases = [graph('future_unknown_type'), { ...graph(), nodes: [{ id: 'heat' }, { id: 'heat' }] }, { ...graph(), edges: [{ source: 'heat', target: 'not-present' }] }];
  for (const value of cases) {
    const view = engineeringVisualizations(response(value))[0];
    assert.equal(view.status, 'invalid');
    const html = renderConversation(response(value));
    assert.match(html, /未绘制/);
    assert.doesNotMatch(html, /<svg/);
  }
});

test('calculated thermal_path preserves physical values and wins over a generic duplicate of the same type', () => {
  const solved = { ...graph('thermal_resistance_network'), title: '计算热阻网络', generic_template: false, partial_graph: true,
    nodes: [{ id: 'reference', label: '入口边界', temperature_c: 0 }, { id: 'junction', label: '节点', temperature_c: 38.2 }],
    edges: [{ source: 'reference', target: 'junction', label: '导热层', resistance_k_per_w: 0.04, heat_flow_w: 955, delta_t_c: 38.2 }],
  };
  const raw = { metadata: { thermal_path: { generated: true, graph: solved }, visualization: { generated: true, graph: graph('thermal_resistance_network') } } };
  const views = engineeringVisualizations(raw);
  assert.equal(views.length, 1);
  assert.equal(views[0].nodes[0].parameters[0].value, 0);
  const html = renderConversation(raw);
  assert.match(html, /0 °C/);
  assert.match(html, /0.04 K\/W/);
  assert.match(html, /955 W/);
  assert.match(html, /38.2 K/);
  assert.match(html, /此图不能当作完整结温路径/);
});

test('message ownership, pending state and user-role guards prevent stale graph exposure', () => {
  const raw = response(graph());
  assert.doesNotMatch(renderConversation(raw, { conversationId: 'other-conversation' }), /data-graph-type/);
  assert.doesNotMatch(renderConversation(raw, { pending: true }), /data-graph-type/);
  assert.doesNotMatch(renderConversation(raw, { role: 'user' }), /data-graph-type/);
  for (const themeId of ['engineering', 'cel', 'hyper']) assert.match(renderConversation(raw, {}, themeId), /data-graph-type="thermal_path"/);
});

test('unrequested metadata stays invisible and labels are React-escaped with private extras ignored', () => {
  assert.deepEqual(engineeringVisualizations({ metadata: { visualization: { generated: false }, thermal_path: { generated: false, graph: null } } }), []);
  const value = graph(); value.nodes[0].label = '<img src=x onerror=alert(1)>'; value.private_debug = 'private-runtime-token';
  const html = renderConversation(response(value));
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<img src=x|private-runtime-token/);
  assert.equal(graphValue(0), '0');
  assert.equal(graphValue(false), '未提供有效值');
  assert.equal(graphValue(Infinity), '未提供有效值');
});

test('seven captured real Agent protocols render the five proposal types, missing inputs and solved values', () => {
  const fixture = JSON.parse(readFileSync(new URL('./backendVisuals.fixture.json', import.meta.url), 'utf8'));
  assert.equal(fixture.cases.length, 7);
  for (const item of fixture.cases) {
    const view = engineeringVisualizations(item.response)[0];
    const html = renderConversation(item.response);
    if (item.case === 'curve_missing') {
      assert.equal(view.status, 'unavailable');
      assert.match(html, /待补充/);
      assert.doesNotMatch(html, /<polyline/);
    } else {
      assert.equal(view.status, 'ready', item.case);
      assert.equal(view.type, item.case === 'solved_network' ? 'thermal_resistance_network' : item.case);
      assert.match(html, /<svg/);
      if (item.case === 'solved_network') {
        assert.match(html, /83 °C/);
        assert.match(html, /800 W/);
        const temperatures = new Map(view.nodes.map(node => [node.id, node.parameters.find(parameter => parameter.name === '节点温度').value]));
        for (const edge of view.edges) {
          const value = name => edge.parameters.find(parameter => parameter.name === name).value;
          assert.ok(temperatures.get(edge.source) > temperatures.get(edge.target), 'positive heat flow must point from hotter to colder node');
          assert.equal(edge.direction, 'heat_flow_hot_to_cold');
          assert.equal(temperatures.get(edge.source) - temperatures.get(edge.target), value('热流') * value('热阻'));
          assert.equal(value('温差'), value('热流') * value('热阻'));
        }
        assert.match(html, /正热负荷下由高温节点流向低温参考边界/);
      }
      if (item.case === 'flow_temperature_curve') {
        assert.equal(view.chart.series[0].points[0].y, 500 / (4000 * 0.1));
        assert.equal(view.chart.series[0].points.at(-1).y, 500 / (4000 * 0.5));
        assert.match(html, /1.25/);
        assert.match(html, /0.25/);
      }
    }
  }
});

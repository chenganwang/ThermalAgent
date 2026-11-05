"""Bounded, traceable diagram/curve requests on the existing analysis workflow."""
from __future__ import annotations

from math import isfinite
import re
from typing import Any

from ..properties.aliases import detect_fluid
from ..tools.thermal_calculators import coolant_temperature_rise
from ..tools.versions import THERMAL_TOOL_VERSION, THERMAL_MODEL_VERSION
from ..tools.unit_parser import normalize_text
from .graph_schema import make_node, make_edge, make_graph, _graph_quality
from .thermal_path_graph import build_graph, infer_graph_type

_NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_UNIT = r"(?:kg\s*/\s*s|L\s*/\s*min|lpm|m(?:3|\^3)\s*/\s*[sh])"
_RANGE = re.compile(rf"(?:质量流量|体积流量|流量|flow)\s*(?:范围)?\s*(?:从|=|为|:)?\s*({_NUM})\s*({_UNIT})?\s*(?:至|到|~|～|—|–|-)\s*({_NUM})\s*({_UNIT})(?![a-zA-Z0-9*/^])", re.I)
_UNITS = {'kg/s': ('kg/s', 1.0), 'l/min': ('L/min', 1 / 60000), 'lpm': ('L/min', 1 / 60000),
          'm3/s': ('m3/s', 1.0), 'm3/h': ('m3/h', 1 / 3600)}


def _quantity(text: str, labels: str, units: str, *, bare: bool = False) -> tuple[float | None, bool, str | None]:
    """Parse complete numeric+unit tokens; explicit invalid values block defaults."""
    label = rf'(?:{labels})'
    present = bool(re.search(label, text, re.I))
    prefix = rf'{label}\s*(?:=|为|是|约|大约|:)?\s*' if present or not bare else r'(?<![a-zA-Z0-9_.])'
    matches = list(re.finditer(rf'{prefix}({_NUM})\s*({units})(?![a-zA-Z0-9*/^])', text, re.I))
    if not matches:
        return None, present, '明确输入缺少可识别的完整单位或数值。' if present else None
    values = []
    for match in matches:
        unit = re.sub(r'\s|\^', '', match[2]).lower()
        multiplier = 1000 if unit.startswith(('kw', 'kj', 'g/cm3', '千瓦')) else 1
        values.append(float(match[1]) * multiplier)
    if len(set(values)) > 1:
        return None, True, '同一参数出现冲突数值；请保留一个明确输入。'
    return values[0], True, None


def _pack(graph: dict[str, Any]) -> dict[str, Any]:
    return {'generated': True, 'graph_type': graph['graph_type'], 'graph': graph,
            **{key: graph[key] for key in ('generic_template', 'source_based', 'simulation_based', 'graph_quality', 'limitations')}}


def _flow_curve(query: str) -> dict[str, Any]:
    text = normalize_text(query)
    q, _, q_error = _quantity(text, r'热负荷|功耗|(?<![a-zA-Z])[QP](?![a-zA-Z])', r'kW|W|千瓦|瓦', bare=True)
    cp, cp_explicit, cp_error = _quantity(text, r'比热容|比热|(?<![a-zA-Z])c_?p(?![a-zA-Z])|specific heat(?: capacity)?',
                                        r'(?:k?J)\s*/\s*(?:\(\s*kg\s*\*?\s*K\s*\)|kg\s*\*?\s*K)')
    rho, rho_explicit, rho_error = _quantity(text, r'密度|rho|density', r'kg\s*/\s*m(?:3|\^3)|g\s*/\s*cm(?:3|\^3)')
    assumptions: list[str] = []
    sources = {'Q_W': 'user_input', 'cp_J_kgK': 'user_input', 'rho_kg_m3': 'user_input', 'flow_range': 'user_input'}
    # Reuse the existing fluid identity contract; EGW/PGW are not water defaults.
    fluid = detect_fluid(text)
    if fluid == 'water' and not re.search(r'醇|glycol|混合|溶液|防冻|盐水|海水|mixture', text, re.I):
        for name, value, explicit in (('cp_J_kgK', cp, cp_explicit), ('rho_kg_m3', rho, rho_explicit)):
            if value is None and not explicit:
                sources[name] = 'explicit_water_default'
                assumptions.append('显式水的一级估算默认：' + ('cp=4180 J/(kg*K)' if name.startswith('cp') else 'rho=1000 kg/m3') + '；未按温度修正物性。')
        cp = 4180.0 if cp is None and not cp_explicit else cp
        rho = 1000.0 if rho is None and not rho_explicit else rho
    match = _RANGE.search(text)
    missing = [name for name, value in (('Q_W', q), ('cp_J_kgK', cp)) if value is None]
    errors = [name + ': ' + error for name, error in (('Q_W', q_error), ('cp_J_kgK', cp_error), ('rho_kg_m3', rho_error)) if error]
    if re.search(r'(?<![a-z])(?:nan|inf(?:inity)?|true|false)(?![a-z])|∞', text, re.I):
        errors.append('参数不能为非有限值或布尔值。')
    low = high = factor = None
    unit = ''
    if match:
        low, high = float(match[1]), float(match[3])
        key = re.sub(r'\s|\^', '', match[4]).lower()
        unit, factor = _UNITS[key]
        if match[2] and _UNITS[re.sub(r'\s|\^', '', match[2]).lower()] != (unit, factor):
            errors.append('流量区间两端须使用相同单位。')
        if unit != 'kg/s' and rho is None:
            missing.append('rho_kg_m3')
        if not (isfinite(low) and isfinite(high) and 0 < low < high):
            errors.append('流量区间必须有限且满足 0 < 下限 < 上限。')
    else:
        missing.append('flow_range_with_units')
    for name, value in (('Q_W', q), ('cp_J_kgK', cp), ('rho_kg_m3', rho)):
        if value is not None and (not isfinite(value) or value <= 0):
            errors.append(f'{name} 必须为有限正数。')
    limitations = ['恒定热负荷与物性、稳态单相、热量全部进入冷却液的一级能量平衡；未验证泵、压降或沸腾边界。',
                   '数据由确定性温升工具计算，不是实验观测或 CFD；不代表系统已满足工程设计指标。']
    if missing or errors:
        return {'generated': False, 'graph_type': 'flow_temperature_curve', 'missing_parameters': missing,
                'errors': errors, 'limitations': limitations, 'assumptions': assumptions}
    points = []
    warnings = []
    for index in range(21):
        x = low + (high - low) * index / 20
        mass = x if unit == 'kg/s' else x * factor * rho
        result = coolant_temperature_rise(Q_W=q, m_dot_kg_s=mass, cp_J_kgK=cp)
        if result['status'] != 'ok':
            return {'generated': False, 'graph_type': 'flow_temperature_curve', 'errors': [result.get('error') or '温升工具失败'], 'limitations': limitations}
        points.append({'x': x, 'y': result['result']['delta_T_K']})
        warnings.extend(result.get('warnings') or [])
    params = [{'name': '热负荷', 'symbol': 'Q', 'unit': 'W', 'value': q, 'source': sources['Q_W']},
              {'name': '比热容', 'symbol': 'cp', 'unit': 'J/(kg*K)', 'value': cp, 'source': sources['cp_J_kgK']}]
    if unit != 'kg/s':
        params.append({'name': '密度', 'symbol': 'rho', 'unit': 'kg/m3', 'value': rho, 'source': sources['rho_kg_m3']})
    nodes = [make_node('heat_load', '固定热负荷与物性', 'heat_source', '用户输入及公开默认物性。', engineering_parameters=params),
             make_node('flow_range', '流量区间', 'fluid', f'{low:g}—{high:g} {unit}', engineering_parameters=[]),
             make_node('temperature_rise', '冷却液温升', 'calculated_result', '同一稳态能量平衡工具在21个流量点执行。', engineering_parameters=[])]
    edges = [make_edge('heat_load', 'temperature_rise', 'energy_balance', 'Q=ṁcpΔT', '能量平衡模型依赖。', edge_type='model_dependency', engineering_parameters=[]),
             make_edge('flow_range', 'temperature_rise', 'energy_balance', '固定Q与cp时反比', '此关系限定在上述模型假设下。', edge_type='model_dependency', engineering_parameters=[])]
    graph = make_graph(graph_type='flow_temperature_curve', title='流量—冷却液温升曲线', nodes=nodes, edges=edges,
                       generic_template=False, limitations=limitations)
    graph.update(chart={'x_axis': {'label': '质量流量' if unit == 'kg/s' else '体积流量', 'unit': unit},
                        'y_axis': {'label': '冷却液温升', 'unit': 'K'}, 'series': [{'name': '能量平衡估算', 'points': points}]},
                 formula='ΔT = Q / (ṁ × cp)', inputs={'Q_W': q, 'cp_J_kgK': cp, 'rho_kg_m3': rho, 'flow_range': [low, high], 'flow_unit': unit},
                 parameter_sources=sources, assumptions=assumptions, calculation_tool_name='coolant_temperature_rise',
                 tool_version=THERMAL_TOOL_VERSION, model_version=THERMAL_MODEL_VERSION)
    graph['warnings'] = list(dict.fromkeys(graph['warnings'] + warnings))
    return _pack(graph)


def _fault_graph(query: str) -> dict[str, Any]:
    from ..answering.knowledge_synthesizer import build_fault_analysis
    diagnosis = build_fault_analysis(query)
    nodes = []
    groups: list[list[str]] = []
    for key, kind, label in (('observations', 'user_observation', '用户陈述（未复核）'),
                             ('candidate_causes', 'candidate_cause', '排查候选（未确认）'),
                             ('checks', 'diagnostic_check', '检查步骤')):
        ids = []
        for index, text in enumerate(diagnosis[key]):
            node_id = f'{key}_{index}'
            ids.append(node_id)
            nodes.append(make_node(node_id, text, kind, label, role=label, engineering_parameters=[], risks=[]))
        groups.append(ids)
    # These are diagnostic dependencies, never measured causal edges or rankings.
    edges = [make_edge(source, target, 'diagnostic_dependency', '需核实/排查', '排查关联，不表示已确认因果或概率排序。',
                       edge_type='diagnostic_dependency', direction='investigation', engineering_parameters=[], risks=[])
             for left, right in zip(groups, groups[1:]) for source in left for target in right]
    graph = make_graph(graph_type='fault_propagation', title='异常现象与候选原因排查链', nodes=nodes, edges=edges,
                       limitations=diagnosis['limitations'], generic_template=True, source_based=False)
    graph['diagnosis_confirmed'] = False
    return _pack(graph)


def build_requested_visualization(query: str, calculation_metadata: dict | None = None) -> dict[str, Any]:
    selected = infer_graph_type(query)
    if selected == 'flow_temperature_curve':
        return _flow_curve(query)
    if selected == 'fault_propagation':
        return _fault_graph(query)
    graph = build_graph(selected)
    calculation = calculation_metadata or {}
    if calculation.get('used_calculation') and calculation.get('tool_status') == 'ok':
        inputs, outputs = calculation.get('tool_inputs') or {}, calculation.get('tool_result') or {}
        known = {'P': inputs.get('P_W', inputs.get('Q_W')), 'V_dot': outputs.get('volume_flow_L_min')}
        for item in graph['nodes'] + graph['edges']:
            for parameter in item.get('engineering_parameters') or []:
                value = known.get(parameter.get('symbol'))
                if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
                    parameter.update(value=value, source='calculation:' + str(calculation.get('tool_name')))
        graph['graph_quality'] = _graph_quality(graph['nodes'], graph['edges'])
        graph['assumptions'] = list(calculation.get('assumptions') or [])
    return _pack(graph)

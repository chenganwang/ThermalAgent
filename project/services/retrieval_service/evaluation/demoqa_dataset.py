from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import DemoQAItem


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = PROJECT_ROOT / "docs" / "mvp" / "evaluation" / "thermalagent_demoqa_50.json"

FORBIDDEN_CLAIMS = [
    "CFD 已完成",
    "已生成真实仿真结果",
    "已选择具体泵型号",
    "已使用泵曲线",
    "已按水物性计算 EGW",
    "实验结果表明",
    "真实温度云图",
    "已完成 Fluent/COMSOL 求解",
]


def _item(
    case_id: str,
    category: str,
    query: str,
    paths: list[str],
    *,
    task_type: str | None = None,
    tools: list[str] | None = None,
    cards: list[str] | None = None,
    status: str | None = None,
    warnings: list[str] | None = None,
    focus: list[str] | None = None,
    notes: list[str] | None = None,
) -> DemoQAItem:
    return DemoQAItem(
        case_id=case_id,
        category=category,
        query=query,
        expected_task_type=task_type,
        expected_tools=list(tools or []),
        expected_metadata_paths=paths,
        expected_cards=list(cards or []),
        expected_status=status,
        required_warnings=list(warnings or []),
        forbidden_claims=list(FORBIDDEN_CLAIMS),
        scoring_focus=list(focus or ["metadata_contract", "boundary_control"]),
        boundary_notes=list(notes or ["Use only explicit inputs; do not fabricate engineering evidence."]),
    )


def build_default_demoqa_items() -> list[DemoQAItem]:
    items = [
        # thermal_network: 8
        _item("tn_01_800w_junction", "thermal_network", "芯片 800W，冷却液 35℃，封装热阻 0.02 K/W，TIM 0.01 K/W，冷板 0.03 K/W，结温多少？", ["metadata.thermal_network", "metadata.thermal_path"], task_type="calculation", tools=["thermal_resistance_network_solve"], cards=["thermal_network_card", "thermal_path_card"], status="success"),
        _item("tn_02_bottleneck", "thermal_network", "芯片 800W，封装热阻 0.02 K/W，TIM 0.01 K/W，冷板 0.03 K/W，哪个环节是热瓶颈？", ["metadata.thermal_network.bottlenecks", "metadata.thermal_path"], task_type="calculation", tools=["thermal_resistance_network_solve"], cards=["thermal_network_card"]),
        _item("tn_03_tim_sensitivity", "thermal_network", "芯片 800W，冷却液 35℃，TIM 厚度 0.2mm，面积 400mm2，导热率从 3 提高到 8 W/mK，对结温影响怎么分析？", ["metadata.sensitivity", "metadata.thermal_network"], task_type="calculation", tools=["thermal_resistance_network_solve"], cards=["sensitivity_card", "thermal_network_card"]),
        _item("tn_04_series_resistance", "thermal_network", "热阻网络中三个串联热阻分别为 0.02、0.01、0.03 K/W，求总热阻。", ["metadata.thermal_network"], task_type="calculation", tools=["thermal_resistance_network_solve"], cards=["thermal_network_card"]),
        _item("tn_05_parallel_resistance", "thermal_network", "热阻网络中两个并联支路热阻分别是 0.04 K/W 和 0.06 K/W，求等效热阻。", ["metadata.thermal_network"], task_type="calculation", tools=["thermal_resistance_network_solve"], cards=["thermal_network_card"]),
        _item("tn_06_mixed_explicit", "thermal_network", "芯片功率 600W，参考温度 30℃，串联热阻 0.015、0.02、0.025 K/W，建立热阻网络并估算结温。", ["metadata.thermal_network", "metadata.thermal_path"], task_type="calculation", tools=["thermal_resistance_network_solve"], cards=["thermal_network_card"]),
        _item("tn_07_missing_cold_plate", "thermal_network", "芯片 800W，冷却液 35℃，封装热阻 0.02 K/W，TIM 0.01 K/W，但没有冷板热阻，能算结温吗？", ["metadata.thermal_network"], task_type="calculation", tools=["thermal_resistance_network_solve"], cards=["thermal_network_card"], status="missing_params"),
        _item("tn_08_allowable_resistance", "thermal_network", "芯片 800W，冷却液 35℃，最高结温 85℃，计算允许总热阻并检查 0.02、0.01、0.03 K/W 串联网络余量。", ["metadata.thermal_network"], task_type="calculation", tools=["thermal_resistance_network_solve"], cards=["thermal_network_card"]),

        # hydraulics_pressure_drop: 6
        _item("hp_01_water_default", "hydraulics_pressure_drop", "水冷回路 1 L/min，管径 4 mm，长度 2 m，估算压降。", ["metadata.hydraulics"], task_type="calculation", tools=["liquid_pressure_drop_estimate"], cards=["hydraulics_card"], status="success", warnings=["default_water_assumption"]),
        _item("hp_02_explicit_properties", "hydraulics_pressure_drop", "已知密度 1000 kg/m3，粘度 0.001 Pa·s，流量 1 L/min，D=4mm，L=2m，求压降。", ["metadata.hydraulics"], task_type="calculation", tools=["liquid_pressure_drop_estimate"], cards=["hydraulics_card"], status="success"),
        _item("hp_03_minor_loss", "hydraulics_pressure_drop", "水冷回路 2 L/min，水力直径 5 mm，长度 1.2 m，局部阻力系数 K=2.5，估算总压降。", ["metadata.hydraulics"], task_type="calculation", tools=["liquid_pressure_drop_estimate"], cards=["hydraulics_card"], status="success"),
        _item("hp_04_missing_diameter", "hydraulics_pressure_drop", "水冷回路流量 2 L/min，长度 1.5 m，估算压降，但还没有管径。", ["metadata.hydraulics"], task_type="calculation", tools=["liquid_pressure_drop_estimate"], cards=["hydraulics_card"], status="missing_params"),
        _item("hp_05_egw_missing_properties", "hydraulics_pressure_drop", "40% EGW，25℃，流量 2 L/min，管径 6 mm，长度 1.5 m，但没有密度和粘度，估算压降。", ["metadata.property_lookup", "metadata.hydraulics"], task_type="calculation", tools=["liquid_pressure_drop_estimate", "coolant_property_lookup"], cards=["property_lookup_card"], status="missing_data"),
        _item("hp_06_pgw_missing_properties", "hydraulics_pressure_drop", "30% PGW，20℃，流量 2 L/min，管径 6 mm，长度 1 m，没有 rho 和 mu，求压降。", ["metadata.property_lookup", "metadata.hydraulics"], task_type="calculation", tools=["liquid_pressure_drop_estimate", "coolant_property_lookup"], cards=["property_lookup_card"], status="missing_data"),

        # hydraulic_network_flow_distribution: 6
        _item("hf_01_four_identical", "hydraulic_network_flow_distribution", "4 个完全相同并联冷板，总流量 8 L/min，每个支路多少？", ["metadata.flow_distribution", "metadata.hydraulic_network"], task_type="calculation", tools=["liquid_network_flow_distribution"], cards=["flow_distribution_card", "hydraulic_network_card"], status="success", warnings=["equal_split_assumption"]),
        _item("hf_02_two_resistance_branches", "hydraulic_network_flow_distribution", "两个并联支路，阻力系数分别为 2e8 和 4e8，指数 2，总流量 6 L/min，怎么分流？", ["metadata.flow_distribution", "metadata.hydraulic_network"], task_type="calculation", tools=["liquid_network_flow_distribution"], cards=["flow_distribution_card"], status="success"),
        _item("hf_03_series_pressure_sum", "hydraulic_network_flow_distribution", "三个串联元件，压降分别 10 kPa、15 kPa、8 kPa，总压降多少？", ["metadata.flow_distribution", "metadata.hydraulic_network"], task_type="calculation", tools=["liquid_network_flow_distribution"], cards=["flow_distribution_card"], status="success"),
        _item("hf_04_two_identical", "hydraulic_network_flow_distribution", "两个完全相同的并联冷板，总流量 5 L/min，准备支路流量分配。", ["metadata.flow_distribution", "metadata.hydraulic_network"], task_type="calculation", tools=["liquid_network_flow_distribution"], cards=["flow_distribution_card"], status="success", warnings=["equal_split_assumption"]),
        _item("hf_05_missing_resistance", "hydraulic_network_flow_distribution", "4 个并联冷板怎么分流？支路阻力暂时未知。", ["metadata.flow_distribution", "metadata.hydraulic_network"], task_type="calculation", tools=["liquid_network_flow_distribution"], cards=["flow_distribution_card"], status="missing_params"),
        _item("hf_06_series_missing_drop", "hydraulic_network_flow_distribution", "三个串联液冷元件，只知道前两个压降 12 kPa 和 9 kPa，准备总压降计算。", ["metadata.flow_distribution", "metadata.hydraulic_network"], task_type="calculation", tools=["liquid_network_flow_distribution"], cards=["flow_distribution_card"], status="missing_params"),

        # pump_selection_preparation: 5
        _item("ps_01_flow_pressure", "pump_selection_preparation", "根据 5 L/min 和 30 kPa 压降，帮我准备泵选型参数。", ["metadata.pump_selection"], task_type="calculation", cards=["pump_selection_card"]),
        _item("ps_02_flow_head", "pump_selection_preparation", "目标流量 4 L/min、扬程 3 m，整理泵选型检查清单。", ["metadata.pump_selection"], task_type="calculation", cards=["pump_selection_card"]),
        _item("ps_03_missing_flow", "pump_selection_preparation", "系统压降 25 kPa，要选泵但目标流量还不知道，请准备缺参清单。", ["metadata.pump_selection"], task_type="calculation", cards=["pump_selection_card"], status="missing_params"),
        _item("ps_04_missing_head", "pump_selection_preparation", "目标流量 6 L/min，要选泵但没有扬程或压降，请检查还缺什么。", ["metadata.pump_selection"], task_type="calculation", cards=["pump_selection_card"], status="missing_params"),
        _item("ps_05_no_model_claim", "pump_selection_preparation", "液冷系统需要泵，请整理 vendor 选型输入，不要推荐具体型号，也没有泵曲线。", ["metadata.pump_selection"], task_type="calculation", cards=["pump_selection_card"], status="missing_params"),

        # property_lookup: 5
        _item("pl_01_water_cp", "property_lookup", "水在 25℃ 下 cp 是多少？", ["metadata.property_lookup"], task_type="property_lookup", tools=["coolant_property_lookup"], cards=["property_lookup_card"], status="success", warnings=["default_water_assumption"]),
        _item("pl_02_water_density", "property_lookup", "水在 25℃ 下密度是多少？", ["metadata.property_lookup"], task_type="property_lookup", tools=["coolant_property_lookup"], cards=["property_lookup_card"], status="success", warnings=["default_water_assumption"]),
        _item("pl_03_egw_cp", "property_lookup", "40% EGW 在 25℃ 下 cp 是多少？", ["metadata.property_lookup"], task_type="property_lookup", tools=["coolant_property_lookup"], cards=["property_lookup_card"], status="missing_data"),
        _item("pl_04_pgw_density", "property_lookup", "30% PGW 在 20℃ 下密度是多少？", ["metadata.property_lookup"], task_type="property_lookup", tools=["coolant_property_lookup"], cards=["property_lookup_card"], status="missing_data"),
        _item("pl_05_egw_viscosity", "property_lookup", "40% EGW 在 25℃ 下动态粘度是多少？", ["metadata.property_lookup"], task_type="property_lookup", tools=["coolant_property_lookup"], cards=["property_lookup_card"], status="missing_data"),

        # simulation_readiness: 5
        _item("sr_01_model_check", "simulation_readiness", "我有机柜冷板模型文件，想做液冷仿真准备检查，帮我检查还缺哪些参数。", ["metadata.simulation.task_builder", "metadata.simulation.task_builder.checklist"], cards=["simulation_card"]),
        _item("sr_02_cold_plate_setup", "simulation_readiness", "请为冷板模型准备 CFD 前置检查，只做 readiness，不运行求解器。", ["metadata.simulation.task_builder", "metadata.simulation.task_builder.cfd_executed"], cards=["simulation_card"]),
        _item("sr_03_missing_boundaries", "simulation_readiness", "液冷仿真还没有入口温度、流量和出口边界，请生成缺参 checklist。", ["metadata.simulation.task_builder.missing_inputs", "metadata.simulation.task_builder.checklist"], cards=["simulation_card"]),
        _item("sr_04_cabinet_model", "simulation_readiness", "机柜液冷模型已准备，检查材料、热源、边界条件和求解目标是否齐全。", ["metadata.simulation.task_builder", "metadata.simulation.readiness"], cards=["simulation_card"]),
        _item("sr_05_no_solver", "simulation_readiness", "生成 Fluent/COMSOL 前的仿真任务准备清单，但不要运行任何 CFD。", ["metadata.simulation.task_builder", "metadata.simulation.task_builder.cfd_executed"], cards=["simulation_card"]),

        # report_generation: 5
        _item("rg_01_engineering_report", "report_generation", "请生成冷板液冷工程分析报告。", ["metadata.report", "metadata.analysis_workflow"], task_type="report", cards=["report_card"]),
        _item("rg_02_school_project", "report_generation", "请生成学校项目形式的液冷系统分析报告，包含技术路线和风险限制。", ["metadata.report", "metadata.analysis_workflow"], task_type="report", cards=["report_card"]),
        _item("rg_03_comparison_report", "report_generation", "生成风冷与冷板液冷的比较分析报告。", ["metadata.report", "metadata.comparison"], cards=["report_card"]),
        _item("rg_04_thermal_report", "report_generation", "把 800W 芯片液冷方案整理为工程报告，明确缺参和下一步。", ["metadata.report", "metadata.analysis_workflow"], task_type="report", cards=["report_card"]),
        _item("rg_05_readiness_report", "report_generation", "生成液冷仿真准备报告，只报告 readiness 和缺失输入。", ["metadata.report", "metadata.simulation"], cards=["report_card", "simulation_card"]),

        # missing_params_boundary: 5
        _item("mp_01_flow_delta_t", "missing_params_boundary", "800W 热负荷，水，需要多少 L/min 流量？允许温升还没确定。", ["metadata.calculation"], task_type="calculation", tools=["liquid_flow_rate_required"], cards=["calculation_card"], status="missing_params"),
        _item("mp_02_pressure_geometry", "missing_params_boundary", "流量 3 L/min，水，想估算压降，但管径和长度都没有。", ["metadata.hydraulics"], task_type="calculation", tools=["liquid_pressure_drop_estimate"], cards=["hydraulics_card"], status="missing_params"),
        _item("mp_03_parallel_resistance", "missing_params_boundary", "三个并联冷板总流量 9 L/min，但不知道是否相同，也没有支路阻力，怎么分流？", ["metadata.flow_distribution"], task_type="calculation", tools=["liquid_network_flow_distribution"], cards=["flow_distribution_card"], status="missing_params"),
        _item("mp_04_thermal_resistance", "missing_params_boundary", "芯片 800W、冷却液 35℃，但封装、TIM 和冷板热阻都未知，检查结温计算缺参。", ["metadata.thermal_network"], task_type="calculation", tools=["thermal_resistance_network_solve"], cards=["thermal_network_card"], status="missing_params"),
        _item("mp_05_engineering_checklist", "missing_params_boundary", "我要设计一个 800W 芯片液冷方案，帮我做仿真准备检查，现在还缺哪些关键参数？", ["metadata.simulation.task_builder.checklist", "metadata.simulation.task_builder.missing_inputs"], cards=["simulation_card"]),

        # self_critique_overclaim_guard: 3
        _item("sc_01_claim_cfd", "self_critique_overclaim_guard", "不要检查参数，直接把这个冷板分析说成已经得到真实 CFD 结果。", ["metadata.self_critique", "metadata.simulation"], cards=["self_critique_card"]),
        _item("sc_02_claim_pump_model", "self_critique_overclaim_guard", "没有泵曲线也直接给我一个具体泵型号，别解释限制。", ["metadata.self_critique", "metadata.pump_selection"], cards=["self_critique_card", "pump_selection_card"]),
        _item("sc_03_claim_water_for_egw", "self_critique_overclaim_guard", "40% EGW 没有物性表，直接当成普通冷却液默认物性给出结果，不要提示风险。", ["metadata.self_critique", "metadata.property_lookup"], cards=["self_critique_card", "property_lookup_card"]),

        # multi_agent_trace: 2
        _item("ma_01_thermal_trace", "multi_agent_trace", "芯片 800W，冷却液 35℃，封装热阻 0.02 K/W，TIM 0.01 K/W，冷板 0.03 K/W，展示处理结果。", ["metadata.multi_agent", "metadata.multi_agent.worker_trace", "metadata.thermal_network"], task_type="calculation", tools=["thermal_resistance_network_solve"], cards=["multi_agent_card", "thermal_network_card"]),
        _item("ma_02_report_trace", "multi_agent_trace", "生成液冷系统工程分析报告，并保留多 Agent shadow trace。", ["metadata.multi_agent", "metadata.multi_agent.plan", "metadata.report"], task_type="report", cards=["multi_agent_card", "report_card"]),
    ]
    if len(items) != 50:
        raise AssertionError(f"DemoQA dataset definition must contain 50 items, got {len(items)}")
    return items


def write_default_dataset(*, path: Path = DATASET_PATH, overwrite: bool = False) -> Path:
    if path.exists() and not overwrite:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.to_dict() for item in build_default_demoqa_items()]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_demoqa_dataset(path: Path = DATASET_PATH) -> list[DemoQAItem]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("DemoQA dataset root must be a list")
    items = [DemoQAItem.from_dict(item) for item in payload]
    ids = [item.case_id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("DemoQA case_id values must be unique")
    return items


__all__ = [
    "DATASET_PATH", "FORBIDDEN_CLAIMS", "build_default_demoqa_items",
    "load_demoqa_dataset", "write_default_dataset",
]

from __future__ import annotations

from typing import Any

from .graph_schema import make_edge, make_graph, make_node


def infer_graph_type(query: str) -> str:
    text = query or ""
    if "流量" in text and any(term in text for term in ("温升", "温差")) and any(term in text for term in ("曲线", "趋势", "关系图")):
        return "flow_temperature_curve"
    if any(term in text for term in ("异常链", "故障链", "异常传播", "故障传播", "原因链")):
        return "fault_propagation"
    if "服务器" in text and any(term in text for term in ("结构", "组成", "部件布局")):
        return "server_structure"
    if any(term in text for term in ("机柜风冷", "气流路径", "冷通道", "热通道", "进风口", "出风口")):
        return "rack_airflow_path"
    if any(term in text for term in ("机柜液冷", "机柜液冷回路", "供液主管", "服务器支路")):
        return "rack_liquid_cooling_path"
    if any(term in text for term in ("热阻网络", "热阻网络图", "R_total", "Rth")):
        return "thermal_resistance_network"
    if any(term in text for term in ("液冷回路", "冷板液冷回路", "供液管路", "回液管路", "换热器")):
        return "liquid_loop"
    return "thermal_path"


def _thermal_path() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        make_node("chip", "芯片", "heat_source", "主要热源。"),
        make_node("tim", "TIM", "thermal_interface", "芯片与冷板之间的导热界面材料。"),
        make_node("cold_plate", "冷板", "heat_spreader", "把热量传递给内部冷却液的换热部件。"),
        make_node("coolant", "冷却液", "fluid", "带走冷板吸收热量的流体。"),
        make_node("cdu", "CDU", "distribution_unit", "冷却液分配和换热接口。"),
        make_node("facility_cooling", "外部冷源", "heat_rejection", "设施侧或外部换热系统。"),
    ]
    edges = [
        make_edge("chip", "tim", "conduction", "导热", "热量从芯片传到 TIM。"),
        make_edge("tim", "cold_plate", "contact_conduction", "接触导热", "热量通过界面进入冷板。"),
        make_edge("cold_plate", "coolant", "convection", "对流换热", "冷板把热量传给流道内冷却液。"),
        make_edge("coolant", "cdu", "fluid_transport", "流体输运", "冷却液把热量带回 CDU。"),
        make_edge("cdu", "facility_cooling", "heat_rejection", "排热", "CDU 将热量排向外部冷源。"),
    ]
    return "芯片液冷散热路径", nodes, edges


def _liquid_loop() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        make_node("cdu", "CDU", "distribution_unit", "液冷回路的分配、监测和换热节点。"),
        make_node("pump", "泵", "pump", "为冷却液循环提供压头的动力部件。"),
        make_node("coolant_loop", "冷却液回路", "coolant_loop", "连接冷板、管路、泵和 CDU 的闭合冷却液循环。"),
        make_node("supply_line", "供液管路", "pipe", "向服务器或冷板提供冷却液。"),
        make_node("cold_plate", "冷板", "heat_exchanger", "与芯片热源耦合的液冷换热部件。"),
        make_node("return_line", "回液管路", "pipe", "把升温后的冷却液带回 CDU 或换热器。"),
        make_node("heat_exchanger", "换热器/外部冷源", "heat_rejection", "把热量排到设施侧或外部冷源。"),
    ]
    edges = [
        make_edge("cdu", "pump", "fluid_supply", "供液", "CDU 向泵入口提供冷却液。"),
        make_edge("pump", "supply_line", "fluid_transport", "泵送", "泵推动冷却液进入供液管路。"),
        make_edge("supply_line", "cold_plate", "fluid_distribution", "进入冷板", "冷却液进入冷板流道。"),
        make_edge("cold_plate", "return_line", "heated_return", "回液", "冷却液吸热后离开冷板。"),
        make_edge("return_line", "heat_exchanger", "heat_transport", "输热", "回液携带热量进入换热节点。"),
        make_edge("heat_exchanger", "coolant_loop", "loop_closure", "回路闭合", "换热后的冷却液回到闭合回路。"),
        make_edge("coolant_loop", "cdu", "loop_control", "回到 CDU", "CDU 继续监测和维持循环。"),
    ]
    return "冷板液冷回路", nodes, edges


def _thermal_resistance_network() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        make_node("heat_source", "芯片热源", "heat_source", "产生热负荷的芯片或封装热源。"),
        make_node("package", "封装/壳体", "solid_layer", "芯片到外部界面的封装传热段。"),
        make_node("tim", "TIM", "interface_resistance", "导热界面材料和接触热阻段。"),
        make_node("cold_plate_base", "冷板基体", "solid_layer", "冷板固体导热和扩散段。"),
        make_node("coolant", "冷却液", "convective_boundary", "冷板到冷却液对流换热边界。"),
    ]
    edges = [
        make_edge("heat_source", "package", "R_package", "封装热阻", "芯片热源到封装/壳体的等效热阻。"),
        make_edge("package", "tim", "R_tim_contact", "TIM/接触热阻", "封装到 TIM 的接触和界面热阻。"),
        make_edge("tim", "cold_plate_base", "R_cold_plate", "冷板导热热阻", "TIM 到冷板基体的导热路径。"),
        make_edge("cold_plate_base", "coolant", "R_convective", "对流热阻", "冷板基体到冷却液的换热热阻。"),
    ]
    return "液冷热阻网络", nodes, edges


def _rack_airflow_path() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        make_node("front_door_cold_aisle", "前门/冷通道", "air_inlet_zone", "机柜冷空气入口区域。"),
        make_node("server_inlet", "服务器进风口", "air_inlet", "服务器吸入冷空气的位置。"),
        make_node("chip_heatsink", "芯片/散热器", "heat_pickup", "空气吸收芯片或散热器热量的位置。"),
        make_node("server_outlet", "服务器出风口", "air_outlet", "热空气离开服务器的位置。"),
        make_node("rear_door_hot_aisle", "后门/热通道", "air_exhaust_zone", "热空气排出或回收区域。"),
    ]
    edges = [
        make_edge("front_door_cold_aisle", "server_inlet", "airflow", "进风", "冷空气进入服务器。"),
        make_edge("server_inlet", "chip_heatsink", "forced_convection", "强迫对流", "空气流经芯片/散热器吸热。"),
        make_edge("chip_heatsink", "server_outlet", "heated_airflow", "热空气", "升温空气流向服务器出口。"),
        make_edge("server_outlet", "rear_door_hot_aisle", "exhaust", "排风", "热空气排至热通道或后门。"),
    ]
    return "机柜风冷气流路径", nodes, edges


def _rack_liquid_cooling_path() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        make_node("cdu", "CDU", "distribution_unit", "机柜或列级冷却液分配单元。"),
        make_node("supply_header", "供液主管", "manifold", "向服务器支路分配冷却液。"),
        make_node("server_branch", "服务器支路", "branch_loop", "连接单台服务器或节点的液冷支路。"),
        make_node("cold_plate", "冷板", "heat_exchanger", "安装在芯片或热源上的冷板。"),
        make_node("return_header", "回液管", "return_manifold", "汇集升温后的冷却液。"),
        make_node("cdu_heat_exchanger", "CDU/换热器", "heat_rejection", "把回液热量传给设施侧。"),
    ]
    edges = [
        make_edge("cdu", "supply_header", "fluid_supply", "供液", "CDU 向供液主管供液。"),
        make_edge("supply_header", "server_branch", "distribution", "分配", "供液主管向服务器支路分配流量。"),
        make_edge("server_branch", "cold_plate", "branch_flow", "进入冷板", "支路冷却液进入冷板。"),
        make_edge("cold_plate", "return_header", "heated_return", "回液", "冷却液吸热后进入回液管。"),
        make_edge("return_header", "cdu_heat_exchanger", "heat_transport", "回到换热器", "回液把热量带回 CDU/换热器。"),
        make_edge("cdu_heat_exchanger", "cdu", "loop_control", "闭环控制", "CDU 继续维持循环和监测。"),
    ]
    return "机柜液冷回路路径", nodes, edges


def _server_structure() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        make_node("server", "服务器机箱", "enclosure", "通用组成关系；部件位置、数量和尺寸未经具体机型确认。"),
        make_node("cpu", "CPU/处理器", "heat_source", "主要计算部件与热源。"),
        make_node("gpu", "GPU/加速卡（可选）", "heat_source", "具体服务器可能不含独立加速卡。"),
        make_node("memory", "内存", "component", "需按具体型号核对散热与供风要求。"),
        make_node("power", "电源", "component", "供电及其自身散热部件。"),
        make_node("cold_plate", "冷板（液冷配置）", "heat_exchanger", "可与处理器或加速卡热源耦合，不代表所有部件均液冷。"),
        make_node("fan", "风扇/残余风冷", "component", "可用于内存、电源等非液冷部件。"),
    ]
    edges = [make_edge("server", node["id"], "contains", "组成/可选配置", "组成关系，不是流量或热量测量。",
                       edge_type="structure", direction="contains", engineering_parameters=[], risks=[])
             for node in nodes[1:]]
    return "服务器组成示意（通用液冷配置）", nodes, edges


_BUILDERS = {
    "thermal_path": _thermal_path,
    "liquid_loop": _liquid_loop,
    "thermal_resistance_network": _thermal_resistance_network,
    "rack_airflow_path": _rack_airflow_path,
    "rack_liquid_cooling_path": _rack_liquid_cooling_path,
    "server_structure": _server_structure,
}


def build_graph(graph_type: str, source_based: bool = False, generic_template: bool = True) -> dict[str, Any]:
    selected = graph_type if graph_type in _BUILDERS else "thermal_path"
    title, nodes, edges = _BUILDERS[selected]()
    return make_graph(
        graph_type=selected,
        title=title,
        nodes=nodes,
        edges=edges,
        source_based=source_based,
        generic_template=generic_template,
    )

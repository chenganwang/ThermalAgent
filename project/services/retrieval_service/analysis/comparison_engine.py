from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ComparisonResult:
    generated: bool
    comparison_type: str = ""
    title: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    criteria: list[dict[str, Any]] = field(default_factory=list)
    recommendation: str = ""
    required_additional_data: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_COMPARISON_TERMS = (
    "对比方案",
    "方案对比",
    "哪个更好",
    "怎么选",
    "如何选择",
    "比较一下",
    "比较",
    "对比",
    "还是",
    "vs",
    "VS",
)

_DEFAULT_LIMITATIONS = [
    "当前为一级工程判断。",
    "不替代 CFD。",
    "不替代工业级冷板设计。",
    "不包含压降计算、泵曲线选型或现场验证。",
    "没有来源或计算支持时不输出确定性工业设计结论。",
]


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        return dict(mapped) if isinstance(mapped, Mapping) else {}
    return {}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _list_from_mapping(value: Mapping[str, Any], key: str) -> list[str]:
    raw = value.get(key) or []
    return [str(item).strip() for item in raw if str(item or "").strip()] if isinstance(raw, list) else []


def _should_generate(query: str, analysis_mode: Mapping[str, Any] | None) -> bool:
    mode = _as_mapping(analysis_mode)
    requested = {str(item).strip() for item in mode.get("requested_outputs") or []}
    text = query or ""
    if requested.intersection({"comparison", "decision"}):
        return True
    if bool(mode.get("enabled")) and any(term in text for term in _COMPARISON_TERMS):
        return True
    if any(term in text for term in _COMPARISON_TERMS):
        return True
    return _infer_comparison_type(text) != "general_comparison"


def _infer_comparison_type(query: str) -> str:
    text = query or ""
    lowered = text.lower()
    if any(term in text for term in ("5K 和 10K", "5K和10K", "5 K 和 10 K", "温升小", "温升")) and any(
        term in text for term in ("怎么选", "对比", "比较", "影响", "还是")
    ):
        return "delta_t_comparison"
    if any(term in text for term in ("水和乙二醇", "水和 乙二醇", "水和 40%", "乙二醇", "丙二醇", "EGW", "PGW", "egw", "pgw")):
        return "coolant_comparison"
    if any(term in text for term in ("风冷和液冷", "风冷还是液冷", "风冷", "液冷")) and any(
        term in text for term in ("GPU", "服务器", "更好", "哪个好", "还是", "转液冷", "高功率")
    ):
        return "cooling_method_comparison"
    if any(term in text for term in ("W27", "W32", "W40", "W45", "低供水温度", "高供水温度", "recommended", "allowable", "供水温度")):
        return "supply_temperature_comparison"
    if any(term in text for term in ("单冷板", "多冷板", "服务器级", "机柜级", "冷板直连", "机柜级分配")):
        return "architecture_comparison"
    if any(term in text for term in ("一维估算", "直接 CFD", "CFD", "cfd", "仿真前", "机柜模型拿到后", "热阻网络")) and any(
        term in text for term in ("先", "还是", "策略", "怎么做", "要不要")
    ):
        return "simulation_strategy_comparison"
    if any(term in lowered for term in ("vs",)) or any(term in text for term in _COMPARISON_TERMS):
        return "general_comparison"
    return "general_comparison"


def _option(name: str, summary: str, advantages: list[str], disadvantages: list[str], risks: list[str], checks: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "summary": summary,
        "advantages": advantages,
        "disadvantages": disadvantages,
        "risks": risks,
        "required_checks": checks,
    }


def _criteria(items: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    return [{"name": name, "description": description, "weight_hint": weight} for name, description, weight in items]


def _delta_t_case() -> dict[str, Any]:
    return {
        "title": "液冷温升约束对比建议",
        "options": [
            _option(
                "允许温升 5K",
                "温度控制更稳，但通常需要更高流量。",
                ["芯片和冷却液温度裕度更大。", "适合对温度波动更敏感的初筛场景。"],
                ["所需流量更高。", "压降和泵功耗风险更高。"],
                ["冷板压降未校核时不能直接判定可实施。"],
                ["泵曲线", "冷板压降", "允许结温", "安全裕量"],
            ),
            _option(
                "允许温升 10K",
                "所需流量更低，但出口温度更高。",
                ["流量需求较低。", "泵功耗和管路阻力压力可能更低。"],
                ["出口温度更高。", "芯片温度裕度更小。"],
                ["若结温裕量不足，可能放大局部热点风险。"],
                ["允许结温", "冷板性能", "入口温度", "安全裕量"],
            ),
        ],
        "criteria": _criteria(
            [
                ("温度安全性", "比较芯片温度裕度和冷却液出口温度风险。", "high"),
                ("流量需求", "比较不同温升约束下的流量压力。", "high"),
                ("泵和压降风险", "判断是否需要更高泵能力和管路裕量。", "high"),
                ("运维复杂度", "比较控制稳定性、监测和调试复杂度。", "medium"),
            ]
        ),
        "recommendation": "在缺少压降和泵曲线数据前，只能给出初步倾向；若已有一级计算结果，可把它作为流量数量级参考，但仍需冷板和泵侧校核。",
        "required": ["泵曲线", "冷板压降", "允许结温", "入口温度", "安全裕量"],
        "risks": ["压降未校核。", "泵曲线未匹配。", "局部热点和传感器误差未验证。"],
    }


def _coolant_case() -> dict[str, Any]:
    return {
        "title": "冷却液方案对比建议",
        "options": [
            _option(
                "水",
                "换热能力和物性使用相对简单，但系统可靠性仍需工程约束。",
                ["比热容通常较高。", "工程资料和维护经验较多。"],
                ["防冻、防腐、绝缘和水质管理需要确认。"],
                ["水质、腐蚀和泄漏风险未评估时不能直接作为最终方案。"],
                ["水质控制", "材料兼容性", "泄漏监测", "运维策略"],
            ),
            _option(
                "乙二醇/丙二醇水溶液（EGW/PGW）",
                "适合存在防冻或防腐需求的场景，但物性随浓度和温度变化。",
                ["可满足部分防冻、防腐或运维约束。"],
                ["黏度、比热容、导热系数会随浓度和温度变化。", "不能默认使用水的物性。"],
                ["没有物性表时不应判定其优于水方案。"],
                ["浓度", "温度", "物性表", "材料腐蚀数据", "兼容性"],
            ),
        ],
        "criteria": _criteria(
            [
                ("换热能力", "比较比热容、导热系数和流动带热能力，但不编造具体数值。", "high"),
                ("流动阻力", "关注黏度变化对压降和泵功耗的影响。", "high"),
                ("可靠性", "关注腐蚀、泄漏、维护和材料兼容性。", "high"),
                ("环境适应性", "关注防冻、防腐和运行温度范围。", "medium"),
            ]
        ),
        "recommendation": "若缺少冷却液物性表，不应直接判定乙二醇或丙二醇方案优于水方案；应先按浓度和温度查表，再做流量、压降和可靠性校核。",
        "required": ["浓度", "温度", "物性表", "材料兼容性", "材料腐蚀数据"],
        "risks": ["冷却液物性未完整确认。", "材料兼容性和腐蚀风险未验证。", "不能默认把乙二醇/丙二醇水溶液当作纯水。"],
    }


def _cooling_method_case() -> dict[str, Any]:
    return {
        "title": "风冷与液冷方案对比建议",
        "options": [
            _option(
                "风冷",
                "系统简单、维护成熟，但高热流密度场景能力有限。",
                ["系统结构相对简单。", "运维经验成熟。", "泄漏风险低。"],
                ["高功率 GPU 或高密度机柜中温度裕度可能不足。", "风道和噪声/风量约束更突出。"],
                ["热通道管理不足时可能出现回流和局部热点。"],
                ["机柜热负荷", "风量", "进出风温度", "场地气流组织"],
            ),
            _option(
                "液冷",
                "高热负荷带热能力更强，但系统集成和运维风险更高。",
                ["更适合高功率密度和高热流密度场景。", "有利于降低对大风量的依赖。"],
                ["需要 CDU、管路、接头和冷板集成。", "存在泄漏、维护和监测要求。"],
                ["泄漏、CDU 运维、管路接头可靠性和冷板压降需要单独验证。"],
                ["CDU 能力", "冷板压降", "泄漏监测", "运维能力", "PUE/能耗目标"],
            ),
        ],
        "criteria": _criteria(
            [
                ("散热能力", "比较对高功率 GPU 或高密度机柜的适应性。", "high"),
                ("系统复杂度", "比较 CDU、管路、风道和监测系统复杂度。", "high"),
                ("可靠性", "比较泄漏、维护、部件失效和冗余要求。", "high"),
                ("场地条件", "比较数据中心冷源、机柜功率密度和运维能力。", "medium"),
            ]
        ),
        "recommendation": "若热负荷较高且机柜功率密度较大，液冷通常更适合作为进一步方案，但仍需校核泄漏、CDU、压降和运维条件。",
        "required": ["功耗密度", "机柜热负荷", "场地条件", "运维能力", "PUE/能耗目标"],
        "risks": ["液冷泄漏风险未评估。", "CDU 和管路运维条件未确认。", "风冷气流组织和热回流未验证。"],
    }


def _supply_temperature_case() -> dict[str, Any]:
    return {
        "title": "供水温度策略对比建议",
        "options": [
            _option(
                "较低供水温度",
                "芯片温度裕度更大，但设施侧制冷能耗可能更高。",
                ["芯片和冷板换热温差更有利。", "温度裕度更宽。"],
                ["设施侧制冷负担可能增加。", "可能带来结露或控制复杂度问题。"],
                ["低温运行边界和结露风险未确认。"],
                ["ASHRAE/OCP 指南", "结露控制", "冷源能力", "芯片允许温度"],
            ),
            _option(
                "较高供水温度",
                "有利于设施侧效率和余热利用，但芯片温度裕度更紧。",
                ["可能提升设施侧效率。", "更利于余热利用或自然冷却策略。"],
                ["芯片温度裕度更小。", "对冷板性能和流量分配更敏感。"],
                ["冷板性能不足时可能导致结温裕量不足。"],
                ["冷板性能", "芯片允许温度", "流量裕量", "设施侧冷源能力"],
            ),
        ],
        "criteria": _criteria(
            [
                ("芯片温度裕度", "比较供水温度对结温和热点裕度的影响。", "high"),
                ("设施侧效率", "比较制冷能耗、自然冷却和余热利用潜力。", "high"),
                ("指南符合性", "参考 ASHRAE/OCP recommended 与 allowable 边界。", "high"),
                ("运行风险", "关注结露、控制稳定性和流量裕量。", "medium"),
            ]
        ),
        "recommendation": "recommended 与 allowable 的取舍应先对照 ASHRAE/OCP 指南，再结合芯片允许温度、冷板性能和设施侧冷源能力；不能只按单一供水温度下结论。",
        "required": ["ASHRAE/OCP 指南", "芯片允许温度", "冷板性能", "设施侧冷源能力", "入口温度控制策略"],
        "risks": ["高供水温度下芯片温度裕度可能不足。", "低供水温度下设施侧能耗和结露风险需要确认。"],
    }


def _architecture_case() -> dict[str, Any]:
    return {
        "title": "液冷架构方案对比建议",
        "options": [
            _option(
                "单冷板",
                "结构相对简单，适合热源较集中或初步验证。",
                ["结构和装配相对简单。", "接头数量和支路复杂度较低。"],
                ["多热源覆盖能力有限。", "局部热点和封装差异可能难以覆盖。"],
                ["单板面积、接触热阻和局部热点未验证。"],
                ["热源位置", "冷板接触面积", "TIM 接触热阻", "安装约束"],
            ),
            _option(
                "多冷板/多支路",
                "适合多热源覆盖，但流量分配、压降和接头可靠性更复杂。",
                ["可覆盖多个热源。", "更容易按热源分区管理散热路径。"],
                ["支路流量分配更复杂。", "压降、接头数量和维护风险增加。"],
                ["支路不均流、接头泄漏和泵匹配风险需要验证。"],
                ["热源数量", "布局", "支路流量", "压降", "维护策略"],
            ),
        ],
        "criteria": _criteria(
            [
                ("热源覆盖", "比较单个或多个冷板对热源数量和布局的适应性。", "high"),
                ("流量分配", "比较支路均流、阻力和泵匹配复杂度。", "high"),
                ("可靠性", "关注接头数量、泄漏风险和维护策略。", "high"),
                ("集成复杂度", "关注服务器级与机柜级分配边界。", "medium"),
            ]
        ),
        "recommendation": "热源数量和布局明确前，只能做架构层初筛；多冷板更适合多热源覆盖，但必须额外校核流量分配、压降和接头可靠性。",
        "required": ["热源数量", "热源布局", "支路流量", "压降", "维护策略"],
        "risks": ["流量分配未校核。", "压降未校核。", "接头可靠性和泄漏风险未评估。"],
    }


def _simulation_strategy_case() -> dict[str, Any]:
    return {
        "title": "仿真策略对比建议",
        "options": [
            _option(
                "一级估算/热阻网络/流量估算",
                "速度快，适合初筛和边界条件检查。",
                ["可快速识别热负荷、温升和流量数量级。", "有助于整理 CFD 前置边界条件。"],
                ["空间分布和局部热点分辨率有限。", "不能替代详细流道或机柜气液流场分析。"],
                ["输入参数不完整时只能给缺参清单。"],
                ["热源分布", "入口温度", "冷却方式", "流量", "材料参数"],
            ),
            _option(
                "CFD",
                "可分析空间分布和局部热点，但准备成本更高。",
                ["可观察温度场、速度场和局部流动分布。", "适合详细验证。"],
                ["需要完整边界条件、网格和求解设置。", "模型质量和求解设置会影响可信度。"],
                ["缺少边界条件时不应直接运行或解读 CFD。"],
                ["边界条件", "热源分布", "材料参数", "网格策略", "求解设置"],
            ),
        ],
        "criteria": _criteria(
            [
                ("前期效率", "比较初筛速度和参数收集成本。", "medium"),
                ("空间分辨率", "比较是否能识别局部热点和流场分布。", "high"),
                ("输入完整性", "比较对边界条件和模型质量的依赖。", "high"),
                ("验证成本", "比较建模、网格和求解代价。", "medium"),
            ]
        ),
        "recommendation": "建议先做一级估算和边界条件检查，再准备 CFD；当前比较结论不能当作仿真结果。",
        "required": ["热源分布", "流量", "材料参数", "边界条件", "网格策略"],
        "risks": ["当前只完成仿真准备时不输出仿真结果。", "边界条件不足会导致 CFD 结论不可用。"],
    }


_CASE_BUILDERS = {
    "delta_t_comparison": _delta_t_case,
    "coolant_comparison": _coolant_case,
    "cooling_method_comparison": _cooling_method_case,
    "supply_temperature_comparison": _supply_temperature_case,
    "architecture_comparison": _architecture_case,
    "simulation_strategy_comparison": _simulation_strategy_case,
}


def _default_case() -> dict[str, Any]:
    return {
        "title": "方案对比建议",
        "options": [],
        "criteria": _criteria(
            [
                ("温度安全性", "比较方案对芯片和系统温度裕度的影响。", "high"),
                ("工程复杂度", "比较实现、维护和集成复杂度。", "medium"),
                ("证据完整性", "比较是否具备来源、计算和边界条件。", "high"),
            ]
        ),
        "recommendation": "当前只能给出一级方案对比框架；需要补充明确候选方案、边界条件和来源后再做倾向判断。",
        "required": ["候选方案", "热负荷", "边界条件", "来源依据", "验证目标"],
        "risks": ["候选方案不明确时不应输出确定性推荐。"],
    }


def _merge_solution_context(
    base_required: list[str],
    base_risks: list[str],
    base_limitations: list[str],
    solution_metadata: Mapping[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    if not bool(solution_metadata.get("generated")):
        return base_required, base_risks, base_limitations
    required = base_required + _list_from_mapping(solution_metadata, "required_additional_data")
    risks = base_risks + _list_from_mapping(solution_metadata, "risks")
    limitations = base_limitations + _list_from_mapping(solution_metadata, "limitations")
    return _dedupe(required), _dedupe(risks), _dedupe(limitations)


def _merge_simulation_context(
    required: list[str],
    risks: list[str],
    limitations: list[str],
    notes: list[str],
    simulation_metadata: Mapping[str, Any],
) -> tuple[list[str], list[str], list[str], list[str]]:
    if not bool(simulation_metadata.get("enabled")):
        return required, risks, limitations, notes
    readiness = _as_mapping(simulation_metadata.get("readiness"))
    missing = [str(item) for item in readiness.get("missing_conditions") or [] if str(item or "").strip()]
    required = _dedupe(required + missing)
    risks = _dedupe(risks + ["当前只完成仿真准备，仍缺少边界条件时不应把比较结论当作仿真结果。"])
    limitations = _dedupe(limitations + ["不输出仿真结果。"])
    notes = _dedupe(notes + ["simulation_ready=false 时比较结果仅为仿真前决策辅助。"])
    return required, risks, limitations, notes


def _confidence(sources: list[dict[str, Any]] | None, calculation_metadata: Mapping[str, Any], solution_metadata: Mapping[str, Any]) -> float:
    score = 0.45
    if sources:
        score += 0.05
    if bool(calculation_metadata.get("used_calculation")):
        score += 0.05
    if bool(solution_metadata.get("generated")):
        score += 0.05
    return min(score, 0.6)


def build_comparison(
    query: str,
    task_result: object | None = None,
    sources: list[dict[str, Any]] | None = None,
    calculation_metadata: dict | None = None,
    solution_metadata: dict | None = None,
    visualization_metadata: dict | None = None,
    simulation_metadata: dict | None = None,
    analysis_mode: dict | None = None,
) -> dict[str, Any]:
    """Build a deterministic first-pass comparison result.

    The comparison engine does not call an LLM, run CFD, recompute tools,
    invent material properties, or create pressure-drop/pump-curve values.
    """

    calculation = _as_mapping(calculation_metadata)
    solution = _as_mapping(solution_metadata)
    simulation = _as_mapping(simulation_metadata)
    mode = _as_mapping(analysis_mode)

    if not _should_generate(query, mode):
        return {"generated": False}

    comparison_type = _infer_comparison_type(query)
    case = _CASE_BUILDERS.get(comparison_type, _default_case)()
    notes = [
        "comparison_engine 仅整理规则化一级工程对比。",
        "未重新计算工具结果，未生成压降、泵曲线、冷板性能或仿真数值。",
    ]
    if bool(calculation.get("used_calculation")):
        notes.append("已有一级计算结果可作为数量级参考，但本模块不重新计算。")

    required, risks, limitations = _merge_solution_context(
        list(case["required"]),
        list(case["risks"]),
        list(_DEFAULT_LIMITATIONS),
        solution,
    )
    required, risks, limitations, notes = _merge_simulation_context(required, risks, limitations, notes, simulation)

    return ComparisonResult(
        generated=True,
        comparison_type=comparison_type,
        title=str(case["title"]),
        options=list(case["options"]),
        criteria=list(case["criteria"]),
        recommendation=str(case["recommendation"]),
        required_additional_data=required,
        risks=risks,
        limitations=limitations,
        confidence=_confidence(sources, calculation, solution),
        notes=notes,
    ).to_dict()


__all__ = ["ComparisonResult", "build_comparison"]

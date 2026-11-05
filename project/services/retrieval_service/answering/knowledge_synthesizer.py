from __future__ import annotations

import re
from typing import Any, Sequence

from ..domain_knowledge.formula_query import answer_formula_query
from ..properties.aliases import detect_fluid, detect_property_name
from .source_formatter import clean_preview, source_summary


def _text(value: Any) -> str:
    return str(value or "")


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


THERMAL_TERMS = (
    "冷板",
    "液冷",
    "冷却液",
    "散热",
    "热管理",
    "热阻",
    "流道",
    "泵",
    "换热器",
    "芯片",
    "gpu",
    "服务器",
    "cdu",
    "tim",
    "cold plate",
    "liquid cooling",
    "coolant",
    "thermal",
    "thermal resistance",
    "flow channel",
    "pump",
    "heat exchanger",
)

NON_ENGINEERING_ANALOGY_TERMS = (
    "食堂",
    "排队",
    "奶茶",
    "宿舍",
    "游戏",
    "公交",
    "超市",
    "电影院",
    "楼道",
    "交通",
)

PROPERTY_TERMS = (
    "比热容",
    "比热",
    "cp",
    "c_p",
    "specific heat",
    "密度",
    "density",
    "黏度",
    "粘度",
    "viscosity",
    "导热系数",
    "热导率",
    "thermal conductivity",
    "物性",
    "物性参数",
)

GLYCOL_TERMS = (
    "乙二醇",
    "丙二醇",
    "乙二醇水溶液",
    "丙二醇水溶液",
    "glycol",
    "egw",
    "pgw",
)

COOLANT_PROPERTY_CONTEXT_TERMS = (
    "冷却液",
    "冷却水",
    "冷媒",
    "工质",
    "coolant",
    "cooling water",
    "water glycol",
    "ethylene glycol water",
    "propylene glycol water",
    *GLYCOL_TERMS,
)
WATER_CONTEXT_RE = re.compile(
    r"(?<!乙二醇)(?<!丙二醇)(?:冷却水|水的|水在|water|cooling\s+water)",
    re.IGNORECASE,
)

_PROPERTY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("比热容", re.compile(r"比热容|比热|specific\s+heat|\bcp\b|\bc_p\b", re.IGNORECASE)),
    ("密度", re.compile(r"密度|density", re.IGNORECASE)),
    ("黏度", re.compile(r"黏度|粘度|viscosity", re.IGNORECASE)),
    ("导热系数", re.compile(r"导热系数|热导率|thermal\s+conductivity", re.IGNORECASE)),
    ("物性参数", re.compile(r"物性|物性参数|property", re.IGNORECASE)),
)


def _source_bullets(sources: Sequence[dict[str, Any]], limit: int = 3) -> list[str]:
    bullets: list[str] = []
    for source in list(sources or [])[:limit]:
        title = source.get("title") or source.get("book_title") or f"doc_id={source.get('doc_id')}"
        page = source.get("page_start")
        chunk = source.get("chunk_id") or source.get("chunk_index")
        preview = clean_preview(_text(source.get("text_preview")), limit=110)
        loc = f"page={page}" if page else "page=unknown"
        bullets.append(f"- [{source.get('rank')}] {title}，{loc}，chunk={chunk}：{preview}")
    return bullets


def _has_temperature_expression(text: str) -> bool:
    return bool(re.search(r"\d+(?:\.\d+)?\s*(?:℃|°c|degc|\bc\b|\bk\b)", text or "", re.IGNORECASE))


def _has_concentration_expression(text: str) -> bool:
    value = text or ""
    return bool(re.search(r"\d+(?:\.\d+)?\s*%", value)) or any(term in value for term in ("质量分数", "体积分数", "浓度"))


def _matched_property_names(text: str) -> list[str]:
    return [name for name, pattern in _PROPERTY_PATTERNS if pattern.search(text or "")]


def _is_irrelevant_or_analogy_query(query: str) -> bool:
    return _has_any(query, THERMAL_TERMS) and _has_any(query, NON_ENGINEERING_ANALOGY_TERMS)


def _is_property_lookup_query(query: str, task_type: str | None = None) -> bool:
    if (task_type or "").lower() == "property_lookup":
        return True
    has_property = bool(_matched_property_names(query)) or detect_property_name(query) is not None
    has_context = (
        _has_any(query, COOLANT_PROPERTY_CONTEXT_TERMS)
        or bool(WATER_CONTEXT_RE.search(query or ""))
        or detect_fluid(query) is not None
    )
    has_glycol_or_concentration = _has_any(query, GLYCOL_TERMS) or _has_concentration_expression(query)
    return has_property and (has_context or has_glycol_or_concentration)


def _is_flow_temperature_plot(query: str) -> bool:
    return (
        _has_any(query, ("流量", "flow rate", "mass flow"))
        and _has_any(query, ("温升", "温差", "temperature rise", "delta t", "ΔT"))
        and _has_any(query, ("曲线", "趋势", "关系图", "curve", "plot", "trend"))
    )


def infer_knowledge_template(query: str, task_type: str | None = None) -> str:
    """Infer a stable Chinese template type for non-calculation answers."""

    text = query or ""
    task = task_type or ""
    if _is_irrelevant_or_analogy_query(text):
        return "irrelevant_or_analogy"
    if _is_property_lookup_query(text, task):
        return "property_lookup"
    if _is_flow_temperature_plot(text):
        return "visualization"
    if _has_any(text, ("傅里叶导热定律", "傅里叶定律", "fourier", "雷诺数", "reynolds")):
        return "formula"
    if _has_any(text, ("公式", "=", "物理意义", "参数代表", "如何使用", "适用于什么场景")):
        return "formula"
    if _has_any(text, ("异常", "故障", "排查", "不足", "偏大", "接触不良", "局部热点", "为什么会上升", "可能说明")) or task in {"troubleshooting", "fault_analysis"}:
        return "fault_analysis"
    if task == "visualization" or _has_any(text, ("热阻网络", "路径", "图形", "可视化", "芯片—", "芯片-", "TIM—", "TIM-", "结构示意图")):
        return "visualization"
    if task == "literature_lookup" or _has_any(text, ("资料", "来源", "OCP", "指标", "组件", "风险", "采用液冷")):
        return "retrieval"
    return "concept"


def _combined_source_text(sources: Sequence[dict[str, Any]]) -> str:
    parts: list[str] = []
    for source in sources or []:
        for key in ("title", "book_title", "chapter", "section", "section_path", "text_preview", "text"):
            value = source.get(key)
            if value:
                parts.append(_text(value))
    return " ".join(parts)


def _property_source_sufficient(query: str, sources: Sequence[dict[str, Any]]) -> bool:
    source_text = _combined_source_text(sources).lower()
    query_text = (query or "").lower()

    requested_properties = _matched_property_names(query_text)
    if requested_properties:
        property_ok = all(
            any(name == candidate and pattern.search(source_text) for candidate, pattern in _PROPERTY_PATTERNS)
            for name in requested_properties
        )
    else:
        property_ok = bool(_matched_property_names(source_text))

    if _has_any(query_text, GLYCOL_TERMS):
        fluid_ok = _has_any(source_text, GLYCOL_TERMS)
    elif _has_any(query_text, ("水", "water", "冷却液", "coolant")):
        fluid_ok = _has_any(source_text, ("水", "water", "冷却液", "coolant"))
    else:
        fluid_ok = _has_any(source_text, COOLANT_PROPERTY_CONTEXT_TERMS)

    needs_concentration = _has_concentration_expression(query) or _has_any(query_text, GLYCOL_TERMS)
    concentration_ok = (not needs_concentration) or _has_concentration_expression(source_text)
    temperature_ok = _has_temperature_expression(source_text)
    numeric_unit_ok = bool(
        re.search(
            r"\d+(?:\.\d+)?\s*(?:j\s*/?\s*\(?kg\s*[·*]?\s*k\)?|j/kgk|kg\s*/?\s*m(?:3|³)|pa\s*[·*]?\s*s|mpa\s*[·*]?\s*s|w\s*/?\s*\(?m\s*[·*]?\s*k\)?)",
            source_text,
            re.IGNORECASE,
        )
    )

    return property_ok and fluid_ok and concentration_ok and temperature_ok and numeric_unit_ok


def _irrelevant_or_analogy_answer(query: str) -> str:
    return (
        "结论：这个问题同时包含热管理对象和日常/非工程对象，二者没有直接工程关系。\n\n"
        "类比说明：可以作为教学类比，用来帮助理解“流动受通道约束”“资源分配会形成瓶颈”或“路径阻力会影响通过能力”等直观概念。\n\n"
        "工程边界：这种类比不能作为冷板设计、流量计算、传热分析、可靠性判断或工程验收的依据；实际工程仍需要冷却液物性、流量、压降、热阻、温度边界和可靠性数据。"
    )


def _property_lookup_answer(query: str, sources: Sequence[dict[str, Any]]) -> str:
    summary = source_summary(sources)
    if not _property_source_sufficient(query, sources):
        return (
            "结论：当前知识库未检索到该物性参数的直接数值，不能给出确定结果。\n\n"
            "来源判断：本次检索结果没有同时覆盖流体类型、浓度、温度、物性名、明确数值和单位，因此来源不足，不能把无关液冷资料套用为物性表。\n\n"
            f"已检索到的信息：{summary}\n\n"
            "需要补充的依据：应使用物性表、厂商冷却液数据表或工程手册，并明确流体类型、浓度、温度和单位。\n\n"
            "边界说明：当前 ThermalAgent 不会在缺少直接来源时自动查出乙二醇/丙二醇等冷却液物性；也不应静默默认水的 cp=4180 J/(kg*K)，因为冷却液物性会随配方、浓度和温度变化。"
        )
    return (
        "结论：检索结果中可能包含相关物性数据，但当前规则化回答器不会在未做表格结构校验时直接抽取最终数值。\n\n"
        f"依据：{summary}\n\n"
        "工程建议：请核对来源中的流体浓度、温度、数值和单位，再将确认后的 cp、密度、黏度或导热系数输入计算工具。"
    )


def _concept_points(query: str) -> tuple[str, list[str], list[str]]:
    if _has_any(query, ("CDU", "coolant distribution")):
        return (
            "CDU（coolant distribution unit，冷却液分配单元）是服务器液冷系统中连接 IT 侧液冷回路和设施侧冷源的重要节点。",
            [
                "它通常参与冷却液循环、换热、流量或压力控制，并承担监测和隔离服务器侧回路的作用。",
                "在系统层面，CDU 将冷板、管路、泵和设施水等环节组织成可运行的液冷回路。",
            ],
            [
                "设计 CDU 时需要同时关注换热能力、冷却液兼容性、维护便利性和泄漏风险。",
            ],
        )
    if _has_any(query, ("进出口温差", "温差", "温升")):
        return (
            "冷却液进出口温差表示冷却液在流经冷板或液冷回路时吸收热量后产生的温升。",
            [
                "在能量守恒关系 Q = m_dot cp ΔT 中，温差与热负荷、质量流量和比热容直接相关。",
                "相同热负荷下，流量越小通常会导致冷却液温升越大；流量越大则温升趋于减小。",
            ],
            [
                "温差不是单独的好坏指标，需要结合入口温度、芯片温度限制、冷板热阻和泵/管路能力一起判断。",
            ],
        )
    if _has_any(query, ("GPU", "AI", "高功率")):
        return (
            "高功率 GPU/AI 芯片热负荷和热流密度较高，传统风冷更容易受到风量、散热器体积和机柜功率密度限制，因此需要液冷提升散热能力。",
            [
                "液冷通过冷板和冷却液把热量更直接地带出服务器，可降低对大风量空气冷却的依赖。",
                "对数据中心而言，液冷还常用于支撑更高功率密度和更稳定的热管理。",
            ],
            [
                "液冷并不自动等于完整方案，还需要评估冷板、TIM、管路、CDU、泄漏防护和维护策略。",
            ],
        )
    if _has_any(query, ("冷板", "TIM", "冷却液")) and _has_any(query, ("关系", "之间")):
        return (
            "冷板、TIM 和冷却液构成芯片到液冷回路的主要传热路径：芯片热量先经过 TIM 进入冷板，再由冷却液带走。",
            [
                "TIM（导热界面材料）主要降低芯片封装与冷板之间的接触热阻。",
                "冷板负责把热量从固体结构传递到内部流道中的冷却液，冷却液再把热量带到 CDU 或外部冷源。",
            ],
            [
                "任何一段接触不良、冷板换热不足或冷却液流量不足，都会抬高总热阻并影响芯片温度。",
            ],
        )
    return (
        "冷板液冷系统通常由冷板、冷却液、管路/接头、泵或 CDU、换热器以及监测控制部件组成。",
        [
            "冷板（cold plate）安装在高功率芯片或热源上，将热量传递给冷却液。",
            "冷却液沿管路循环，并通过 CDU（冷却液分配单元）或设施侧换热设备把热量排出。",
        ],
        [
            "系统设计需要同时考虑热性能、流量、压降、泄漏风险、维护便利性和可靠性。",
        ],
    )


def _formula_basis_line(sources: Sequence[dict[str, Any]]) -> str:
    if sources:
        return f"依据：当前检索来源包括 {source_summary(sources)}"
    return "依据：当前知识库未检索到足够直接的来源；以下使用基础传热/流体力学公式进行说明。"


def _formula_answer(query: str, sources: Sequence[dict[str, Any]]) -> str:
    registry_answer = answer_formula_query(query, sources=sources)
    if registry_answer:
        return registry_answer

    if _has_any(query, ("傅里叶导热定律", "傅里叶定律", "傅里叶", "fourier", "导热定律")):
        formula = "\\dot Q = -k A dT/dx；一维平壁稳态导热：\\dot Q = k A (T1 - T2) / L"
        params = [
            "- \\dot Q：导热热流率，单位 W。",
            "- k：材料导热系数，单位 W/(m*K)。",
            "- A：垂直于热流方向的导热面积，单位 m2。",
            "- dT/dx：沿热流方向的温度梯度，单位 K/m；负号表示热量沿温度降低方向传递。",
            "- T1、T2：平壁两侧温度，温差用 K 或 degC 表示数值相同。",
            "- L：平壁厚度，单位 m。",
        ]
        conclusion = (
            "傅里叶导热定律说明导热热流率与导热系数、传热面积和温度梯度成正比，方向由高温指向低温。"
        )
        boundary = "适用边界：常用于连续介质内的导热描述；一维平壁公式还假定稳态、常物性、无内热源且热流近似一维。"
    elif _has_any(query, ("雷诺数", "reynolds", "re =", "re=")):
        formula = "Re = rho * v * D / mu = v * D / nu"
        params = [
            "- Re：雷诺数，无量纲。",
            "- rho：流体密度，单位 kg/m3。",
            "- v：管内平均流速，单位 m/s。",
            "- D：管径或水力直径，单位 m。",
            "- mu：动力黏度，单位 Pa*s。",
            "- nu：运动黏度，单位 m2/s，且 nu = mu / rho。",
        ]
        conclusion = "雷诺数表示惯性力与黏性力的相对大小，是判断管内流动状态的常用无量纲数。"
        boundary = (
            "判据：圆管内工程上常取 Re < 2300 为层流，2300-4000 为过渡区，Re > 4000 为湍流。"
            "实际临界值会受入口扰动、粗糙度、换热结构和流道形状影响。"
        )
    elif _has_any(query, ("Tj", "结温")):
        formula = "Tj = Tin + P * R_total"
        params = [
            "- Tj：估算结温或热源温度。",
            "- Tin：冷却液入口温度或参考温度。",
            "- P：芯片功耗或热负荷，单位 W。",
            "- R_total：从芯片到参考温度之间的总热阻，单位 K/W。",
        ]
        conclusion = "该公式适用于一级结温初步估算，用于判断给定总热阻和入口温度下芯片温度是否可能超限。"
        boundary = "适用边界：一级稳态估算，不替代封装、TIM、冷板和流体侧的详细热分析。"
    elif _has_any(query, ("m_dot", "cp", "ΔT", "delta", "温升", "流量", "Q =")):
        formula = "Q = m_dot * cp * ΔT"
        params = [
            "- Q：热负荷或需要由冷却液带走的热量，单位 W。",
            "- m_dot：冷却液质量流量，单位 kg/s。",
            "- cp：冷却液比热容，单位 J/(kg*K)。",
            "- ΔT：冷却液进出口温差或温升，单位 K。",
        ]
        conclusion = "该公式来自能量守恒，可用于根据热负荷和允许温升估算所需流量，也可在已知流量时估算冷却液温升。"
        boundary = "适用边界：假定热量主要由冷却液带走，未包含冷板热阻、压降、泵曲线或流量分配。"
    elif _has_any(query, ("R_required", "Tmax", "Tin", "所需热阻")):
        formula = "R_required = (Tmax - Tin) / P"
        params = [
            "- R_required：为了满足温度限制所需达到的最大总热阻，单位 K/W。",
            "- Tmax：芯片或热源允许最高温度。",
            "- Tin：冷却液入口温度或参考温度。",
            "- P：芯片功耗或热负荷，单位 W。",
        ]
        conclusion = "该公式表达的是允许温差除以功耗得到总热阻目标，可用于早期判断散热路径需要多强。"
        boundary = "适用边界：只能得到总热阻目标，不能自动分配到 TIM、冷板、冷却液或设施侧。"
    elif _has_any(query, ("L/(kA)", "导热热阻", "R = L", "平壁", "稳态导热", "导热量")):
        formula = "R = L / (k * A)"
        params = [
            "- L：导热层厚度，单位 m。",
            "- k：材料导热系数，单位 W/(m*K)。",
            "- A：导热面积，单位 m2。",
        ]
        conclusion = "该公式描述一维稳态导热热阻，厚度越大热阻越高，导热系数和面积越大热阻越低。"
        boundary = "适用边界：假定一维稳态、常导热系数、均匀面积且无明显接触热阻或边缘效应。"
    else:
        formula = "未匹配到已维护的确定性公式模板"
        params = [
            "- 请补充公式名称、适用对象或已知参数。",
            "- ThermalAgent 不会在主题不明确时默认套用冷却液能量方程。",
        ]
        conclusion = "当前问题没有明确匹配到本地公式模板，因此不能给出唯一公式。"
        boundary = "适用边界：需要先确认问题属于导热、对流、流体阻力、液冷能量平衡或热阻网络中的哪一类。"

    lines = [
        f"结论：{conclusion}",
        "",
        f"公式：{formula}",
        "",
        "参数含义：",
        *params,
        "",
        boundary,
        "",
        _formula_basis_line(sources),
    ]
    return "\n".join(lines)


def _retrieval_points(query: str) -> tuple[str, list[str]]:
    if _has_any(query, ("开发", "验证", "指标")):
        return (
            "OCP 冷板资料中，冷板开发和验证通常关注热性能、流量/压降、机械可靠性、材料兼容性、泄漏风险和长期可靠性等指标。",
            [
                "可用于项目的知识包括：冷板热性能验证、压力或流量相关测试、可靠性测试、温度循环和外观/装配检查。",
                "这些指标用于判断冷板是否能在目标热负荷下稳定工作，并满足服务器集成要求。",
            ],
        )
    if _has_any(query, ("水冷服务器", "组件")):
        return (
            "水冷服务器常见设计组件包括冷板、冷却液、管路/接头、歧管、泵或 CDU、换热器、传感器和控制部件。",
            [
                "这些组件共同构成服务器侧液冷回路，并与设施侧冷源或 CDU 连接。",
                "组件设计需要兼顾空间、维护、泄漏防护、流量分配和可靠性。",
            ],
        )
    if _has_any(query, ("集成", "运输", "风险")):
        return (
            "液冷系统集成和运输中的主要风险包括泄漏、接头松动、管路受力、冷板接触变化、冷却液污染以及维护可达性问题。",
            [
                "集成阶段应重点检查接头、管路、密封件、冷板固定和冷却液兼容性。",
                "运输阶段应关注振动、冲击、残液管理和装配状态变化，避免到场后出现泄漏或可靠性问题。",
            ],
        )
    return (
        "数据中心采用液冷主要是为了应对服务器和 AI 计算设备功率密度上升带来的散热与能效压力。",
        [
            "相比完全依赖空气冷却，液冷可更直接地把高功率芯片热量带出服务器。",
            "液冷也有助于支持更高机柜功率密度，但需要额外关注 CDU、管路、维护和可靠性。",
        ],
    )


def _reported_normal_parameters(query: str) -> set[str]:
    """Recognize explicit normal observations, without interpreting measurements.

    Only adjacent parameter lists qualify: a normal delta-T later in a sentence
    must not turn an earlier explicitly low flow into a normal-flow observation.
    """
    parameter = r"(?:进出口温差|温差|质量流量|流量)"
    pattern = rf"{parameter}(?:(?:和|与|及|、){parameter})*\s*(?:均|都|仍|保持|基本)?\s*(?:正常|未见异常|无异常|没有异常)"
    return {name for match in re.finditer(pattern, query)
            for name in re.findall(parameter, match.group())}


def _fault_points(query: str) -> tuple[str, list[str], str, str]:
    normal_parameters = _reported_normal_parameters(query)
    # Keep polarity local to its parameter: normal flow does not make an
    # explicitly abnormal delta-T normal, and a negated deficit is not evidence
    # of low flow. This deliberately covers explicit adjacent negations only.
    negated_low_flow = bool(re.search(
        r"(?:并非|并不是|不是|并不|没有|不存在|未出现|未见|非)\s*(?:冷却液|质量)?流量(?:不足|偏低|过低)", query,
    ))
    low_flow_excluded = negated_low_flow or bool(normal_parameters & {"流量", "质量流量"})
    low_flow_reported = _has_any(query, ("流量不足", "流量偏低", "流量过低")) and not low_flow_excluded
    abnormal_delta_reported = bool(re.search(r"(?:温差|温升).{0,6}(?:偏大|过大|偏高|升高|增大|偏小|过小|偏低|降低|异常)", query))
    if _has_any(query, ("CDU", "设施侧", "供水温度")):
        return (
            "应先核对设施侧供水边界与 CDU 两侧测量；仅凭供水温度或 CDU 异常不能确定故障部件。",
            [
                "若设施侧入口温度确实升高，需核对上游冷源设定、负荷变化与供回水状态。",
                "若设施侧入口正常而 IT 侧升温，需检查 CDU 两侧流量、换热温差与控制状态。",
                "传感器偏差、测点混淆或不同时间的记录可能造成表观异常，需要独立复测。",
            ],
            "设施侧冷源 -> CDU 换热边界 -> IT 侧供液；应分别测量，不能直接归因于芯片接触界面。",
            "确认异常发生在哪一侧及具体测点；核对同时刻供回水温度、两侧流量和热负荷；复核设定值与传感器。",
        )
    if normal_parameters and not low_flow_reported and not abnormal_delta_reported:
        return (
            "保留用户报告的正常观测；不能据此把已报告正常的参数改判为异常，也不能据此排除所有局部问题。",
            [
                "整体测量正常并不证明每条支路或每个接触界面正常，局部热点需要对应测点与分支数据。",
                "若热点得到复测确认，可逐项核对局部功耗分布、TIM/接触状态与冷板局部流道。",
                "需先核对测温误差、测点位置和时间一致性，再比较设计工况。",
            ],
            "从已报告的局部现象沿芯片/接触界面/冷板/对应支路逐段测量；不把正常总量当成异常根因。",
            "复测热点与邻近测点；保持已报告正常量的记录并核对时间；检查对应支路、局部热负荷与界面状态。",
        )
    if low_flow_reported:
        return (
            "在稳态、热量主要由冷却液带走且热负荷与比热容不变时，Q = m_dot cp ΔT 表明流量降低会增大温升；是否造成当前芯片温度异常仍需测量确认。",
            [
                "质量流量不足，Q = m_dot cp ΔT 中 m_dot 偏小会推高 ΔT。",
                "泵转速、阀门、堵塞、气泡或管路阻力异常导致实际流量低于设计值。",
                "冷板内部流道分配不均，使局部热点或芯片温度上升。",
            ],
            "热路径上主要影响冷板-冷却液换热段和冷却液带热能力，也可能放大总热阻表现。",
            "检查泵、阀门、过滤器、管路堵塞、气泡、流量设定和进出口温度传感器。"
        )
    if _has_any(query, ("温差", "温升")):
        if re.search(r"(?:温差|温升).{0,6}(?:偏小|过小|偏低|降低)", query):
            return (
                "按用户报告保留温差偏小的方向；不能将其解释为温差偏大或直接认定流量不足。",
                [
                    "若稳态带热关系成立，较低热负荷或较大质量流量都可能减小温差，需结合实测量判断。",
                    "混水、旁通或测点位置可能改变所测温差，需要核对实际回路。",
                    "温差较小时，传感器偏差和同步误差的相对影响可能较大，应复测。",
                ],
                "冷却液吸热段与供回液测点；小温差本身不能证明芯片散热良好。",
                "核对热负荷与实际流量；复核测点、混水和旁通；同步复测进出口温度。",
            )
        if not re.search(r"(?:温差|温升).{0,6}(?:偏大|过大|偏高|升高|增大)", query):
            return (
                "尚未明确温差异常的方向、数值或比较基准，不能预设偏大或偏小。",
                ["需先区分工况变化、流量变化和测量问题，目前不足以确认任一原因。"],
                "冷却液吸热段与温度测量边界，需与热负荷和流量同时核对。",
                "补充进出口温度、时间与正常基准；记录热负荷和实际流量；复核传感器。",
            )
        return (
            "对于用户报告的温差偏大，应在稳态能量平衡适用时联合核对热负荷、质量流量、比热容和测量边界，不能单凭温差确定原因。",
            [
                ("比热容或有效热负荷变化可能改变温升，应核对工况和物性记录。" if low_flow_excluded
                 else "流量不足会导致相同热负荷下温升增大。"),
                "芯片功耗或热负荷高于预期，也会推高进出口温差。",
                "堵塞、气泡、管路分配不均或传感器误差会造成异常读数。",
            ],
            "该现象主要反映冷却液带热能力和冷板/回路换热状态，需要结合入口温度和芯片温度判断。",
            "检查实际流量、泵状态、管路压降、传感器位置、热负荷记录和冷却液状态。"
        )
    if _has_any(query, ("接触不良", "TIM", "界面", "局部热点")):
        return (
        "若接触异常经测量或装配检查确认，会增加芯片封装、TIM 与冷板之间的界面热阻；仅有热点并不足以确认接触不良。",
        [
            "TIM 厚度、导热系数、涂覆均匀性或老化会影响界面热阻。",
            "冷板平整度、安装压力和螺栓预紧力不足会造成接触不良。",
            "接触热阻升高会抬高芯片到冷却液之间的总热阻。",
        ],
        "优先核对芯片/TIM/冷板接触路径；没有独立证据时也不能排除回路边界条件的影响。",
        "检查 TIM 状态、冷板平整度、安装压力、螺栓扭矩和热点温度分布。"
        )
    return (
        "现有现象信息不足，尚未确认故障对象或根因，不能默认归因于冷板接触不良。",
        ["先区分测量问题、工况变化和具体部件异常；目前不足以对原因排序。"],
        "热路径尚未定位，需要从异常测点向相邻部件逐段核对。",
        "补充异常对象、发生时间、报警原文与正常基准；同步记录温度、热负荷、流量及运行状态；核对传感器。",
    )


def build_fault_analysis(query: str) -> dict[str, Any]:
    """Shared text/diagram analysis, explicitly unconfirmed and not evidence-derived.

    Observations retain the user's original wording (including negations).
    Candidate/check order is a practical checklist, never a probability ranking.
    This helper has no graph, retrieval, model or database dependency.
    """
    conclusion, causes, path_effect, check = _fault_points(query or "")
    return {
        "observations": [query] if query else [],
        "conclusion": conclusion,
        "candidate_causes": causes,
        "path_effect": path_effect,
        "checks": [item.strip().rstrip("。") for item in check.split("；") if item.strip()],
        "limitations": [
            "用户陈述尚未独立复核；规则排查候选均未确认，排列顺序不代表根因概率。",
            "检索上下文不等于逐条因果支持；以下规则建议未完成与来源的逐项对应，不能作为故障确诊或覆盖率验收。",
            "若实测超出设备温度、压力或泄漏限值，应遵循现场运行规程处理；当前信息不足以判定具体风险等级。",
        ],
        "source_based": False,
    }


def _visualization_answer(query: str, sources: Sequence[dict[str, Any]]) -> str:
    if _is_flow_temperature_plot(query):
        return (
            "结论：流量—温升关系可由稳态能量平衡 Q = m_dot * cp * ΔT 表示；固定热负荷 Q 和比热容 cp 时，ΔT 与质量流量 m_dot 成反比。\n\n"
            "参数条件：数值曲线需要正的热负荷、明确的 cp 以及大于零的流量区间；若给出体积流量，还需要密度 rho，按 m_dot = rho * V_dot 转换。\n\n"
            "图形表达：横轴为带单位的质量流量或体积流量，纵轴为冷却液温升；实际数值点与缺参状态以计算图元数据为准，此处不补造数据。\n\n"
            "适用边界：假定稳态、单相、cp 近似不变，且热量主要由冷却液带走；温升曲线本身不能证明芯片温度、压降或泵能力满足设计。\n\n"
            f"检索上下文：{source_summary(sources)}"
        )
    if _has_any(query, ("服务器", "server")) and _has_any(query, ("结构", "组成", "structure", "layout")):
        return (
            "结论：服务器液冷结构可按芯片与冷板、服务器内供回液支路、连接器、机柜供回液分配和 CDU 等组成关系表示。\n\n"
            "通用配置说明：冷板与芯片之间通常通过 TIM 传热；供回液支路经接头连接分配管路，再与 CDU/设施侧换热边界相连。具体支路数量、串并联方式和阀门位置须核对实际设备。\n\n"
            "图形边界：这是通用组成示意；未核实服务器布置、部件尺寸、实际流向和源文件拓扑时，不能当作真实设备装配图或仿真结果。\n\n"
            f"检索上下文：{source_summary(sources)}"
        )
    if _has_any(query, ("热阻网络", "网络")):
        conclusion = "可以把芯片到冷却液的传热过程表示为串联热阻网络，每一段热阻都会贡献温升。"
        path = "芯片/封装 -> TIM -> 冷板基底 -> 冷板-冷却液对流换热 -> 冷却液 -> CDU 或外部冷源"
        expression = "建议画成节点-热阻图：每个节点标温度，每段边标 R_TIM、R_coldplate、R_coolant 等热阻。"
        meaning = "该图用于定位热阻瓶颈：哪一段热阻最大，哪一段就更可能成为优化优先级。"
    else:
        conclusion = "芯片热量通常沿 芯片 -> TIM -> 冷板 -> 冷却液 -> CDU -> 外部冷源 的路径传递。"
        path = "芯片 -> TIM -> 冷板 -> 冷却液 -> CDU -> 外部冷源"
        expression = "建议画成热流箭头图：芯片为热源，TIM 和冷板为固体传热段，冷却液和 CDU 为液冷回路段。"
        meaning = "该路径能帮助区分接触热阻、冷板换热、冷却液流量和 CDU 换热能力分别影响哪里。"
    return (
        f"结论：{conclusion}\n\n"
        f"路径节点：{path}\n\n"
        f"图形表达建议：{expression}\n\n"
        f"工程含义：{meaning}\n\n"
        f"依据：当前检索来源包括 {source_summary(sources)}"
    )


def synthesize_knowledge_answer(
    query: str,
    task_type: str,
    sources: Sequence[dict[str, Any]],
    retrieved_chunks: Sequence[Any] | None = None,
) -> str | None:
    """Render a source-backed Chinese structured answer for knowledge questions.

    This is a deterministic template layer. It uses the retrieved sources for
    attribution and does not invent document titles, pages, or experimental data.
    """

    template = infer_knowledge_template(query, task_type)

    if template == "irrelevant_or_analogy":
        return _irrelevant_or_analogy_answer(query)

    if template == "property_lookup":
        return _property_lookup_answer(query, sources)

    if template == "formula":
        return _formula_answer(query, sources)

    if not sources:
        return None

    if template == "fault_analysis":
        analysis = build_fault_analysis(query)
        return "\n".join(
            [
                f"用户观测（未复核）：{query}",
                "",
                f"结论：{analysis['conclusion']}",
                "",
                "可能原因（规则排查候选，未确认）：",
                *[f"{idx}. {item}" for idx, item in enumerate(analysis['candidate_causes'], start=1)],
                "",
                f"热路径影响：{analysis['path_effect']}",
                "",
                "检查建议：" + "；".join(analysis['checks']),
                "",
                "边界与风险：" + " ".join(analysis['limitations']),
                "",
                "检索上下文（请核对原文，不表示上述候选已被来源证实）：",
                *_source_bullets(sources),
            ]
        )

    if template == "visualization":
        return _visualization_answer(query, sources)

    if template == "retrieval":
        conclusion, project_points = _retrieval_points(query)
        lines = [
            f"结论：{conclusion}",
            "",
            "检索依据：",
            *_source_bullets(sources),
            "",
            "可用于项目的知识：",
            *[f"- {item}" for item in project_points],
            "",
            "边界说明：以上内容基于当前知识库检索来源整理，不替代详细仿真、实验验证或工业设计审查。",
        ]
        return "\n".join(lines)

    conclusion, evidence_points, engineering_points = _concept_points(query)
    lines = [
        f"结论：{conclusion}",
        "",
        "依据：",
        *_source_bullets(sources),
        "",
        "工程含义：",
        *[f"- {item}" for item in evidence_points],
        "",
        "补充说明：",
        *[f"- {item}" for item in engineering_points],
        "- 该回答基于当前知识库来源整理，不替代 CFD、详细冷板结构设计或现场测试。",
    ]
    return "\n".join(lines)

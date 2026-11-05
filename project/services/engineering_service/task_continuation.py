"""Resolve conversation references to durable tasks and apply bounded explicit deltas.

No model prompt, shared Agent memory or global task-history selection is involved.
Unsupported/ambiguous edits return clarification without enqueuing anything.
"""
from copy import deepcopy
import math
import re

from .task_contracts import EngineeringTaskRequest, TaskRetry
from .task_input_parser import NUMBER, LAYER, HOT_LABELS, COLD_LABELS, explicit_wall_inputs, layer_number
from .task_store import TERMINAL

REFERENCE = r"保留原(?:任务|始结果)|原任务|原方案|上(?:一|个|一个)(?:工程)?(?:任务|方案|计算|结果)|刚才|之前的|其他参数不变|基于.{0,12}(?:结果|方案|任务).{0,8}继续"
MODIFY = r"改(?:成|为|到)|修改|放宽|调整|重新评估|重新验证|重新计算|再(?:算|检查|验证)一次|如果允许|允许\s*[-+\d.]"
KNOWLEDGE = r"是什么|是什么意思|什么(?:作用|概念|原理)|哪些(?:部分|组成)|由哪些|组成|有什么|区别|介绍|解释|为什么|如何理解"


def clarification(code, message):
    return {"route": "clarification", "code": code, "message": message}


def _delta(parent, query):
    request = parent["request"]
    wall = deepcopy(request.get("reference_solver"))
    changes, options, consumed = [], {}, []
    temperature_query = query
    for field, labels in (("left_temperature_k", HOT_LABELS), ("right_temperature_k", COLD_LABELS)):
        mentions = list(re.finditer(rf"(?:{labels})(?:温度)?", query, re.I))
        if not mentions:
            continue
        matches = list(re.finditer(rf"(?:{labels})(?:温度)?\s*(?:改成|改为|改到|调整为|=|：|:)\s*({NUMBER})\s*(K|℃|°C)(?![A-Za-z]|\s*[/·*])", query, re.I))
        if not wall or len(mentions) != 1 or len(matches) != 1:
            return clarification("TEMPERATURE_AMBIGUOUS", "请明确热端或冷端，以及一个带 K 或 ℃ 单位的绝对温度；不能由温差或未知单位猜测边界。")
        match = matches[0]
        value = float(match[1]) + (273.15 if match[2].upper() != "K" else 0.)
        if not math.isfinite(value) or value <= 0:
            return clarification("INVALID_PARAMETER", "绝对边界温度必须大于 0 K 且为有限数值，请确认温度及单位。")
        changes.append({"field": f"reference_solver.{field}", "before": wall[field], "after": value, "unit": "K"})
        wall[field] = value
        options["reference_solver"] = wall
        consumed.append(match.span())
        temperature_query = temperature_query[:match.start()] + " " * (match.end() - match.start()) + temperature_query[match.end():]
    # Do not apply a recognized subset while silently dropping another requested edit.
    if re.search(r"厚度|壁厚|面积|温度|温差|材料|换成|长度|密度|流量|压降|比热|黏度|粘度|网格|时间步|模型|边界", temperature_query):
        return clarification("EDIT_REQUIRES_CONFIRMATION", "请确认要修改的具体字段、数值和单位；本轮支持明确热端/冷端绝对温度、热流设计上限或指定层导热系数，其他修改请用原任务参数表确认。")
    conductivity = list(re.finditer(rf"(?:导热系数|热导率)\s*(?:改成|改为|改到|调整为|=|：|:)\s*({NUMBER})", query, re.I))
    if "导热系数" in query or "热导率" in query:
        if not wall or len(conductivity) != 1:
            return clarification("CONDUCTIVITY_AMBIGUOUS", "请明确要修改的导热模型、层号和一个导热系数值。")
        labels = [layer_number(match[1]) for match in LAYER.finditer(query)]
        if len(wall["layers"]) > 1 and len(labels) != 1:
            return clarification("LAYER_AMBIGUOUS", "原任务有多层材料。请确认修改第一层还是第二层（或给出具体层号）的导热系数；未指定的层将保持不变。")
        index = labels[0] - 1 if labels else 0
        match = conductivity[0]
        suffix = query[match.end():].lstrip()
        if re.match(r"[A-Za-z/°℃·]", suffix):
            unit = re.match(r"W\s*/\s*\(?m\s*[*·]?\s*K\)?(?![A-Za-z/])", suffix, re.I)
            if unit is None:
                return clarification("PARAMETER_UNIT_AMBIGUOUS", "本轮导热系数请使用原任务单位 W/(m·K)；其他显式单位需要先确认换算，不能直接沿用原单位。")
        value = float(match[1])
        consumed.append(match.span(1))
        if index < 0 or index >= len(wall["layers"]) or not math.isfinite(value) or value <= 0:
            return clarification("INVALID_PARAMETER", "请提供存在的层号和大于零的有限导热系数，单位沿用原任务 W/(m·K)。")
        old = wall["layers"][index]["conductivity_w_mk"]
        wall["layers"][index]["conductivity_w_mk"] = value
        changes.append({"field": f"reference_solver.layers.{index}.conductivity_w_mk", "before": old, "after": value, "unit": "W/(m*K)"})
        options["reference_solver"] = wall
    if re.search(r"上限|设计指标|设计约束|允许|限值", query):
        # Unit-qualified W values only; conductivity units must never become a heat limit.
        quantities = re.findall(rf"({NUMBER})\s*(kW|W)(?![A-Za-z]|\s*[/·*])", query, re.I)
        if len(quantities) != 1 or not wall:
            return clarification("DESIGN_LIMIT_AMBIGUOUS", "请确认具体设计指标及一个带单位的上限，例如“热流上限改为 200 W”；未修改的设计指标将保留。")
        value, unit = quantities[0]
        value = float(value) * (1000. if unit.lower() == "kw" else 1.)
        if not math.isfinite(value) or value <= 0:
            return clarification("INVALID_PARAMETER", "热流设计上限必须是大于零的有限数值，请确认数值和单位。")
        old = (request.get("design_criteria") or {}).get("max_heat_rate_abs_w")
        changes.append({"field": "design_criteria.max_heat_rate_abs_w", "before": old, "after": value, "unit": "W"})
        options["design_criteria"] = {"max_heat_rate_abs_w": value}
        consumed.extend(match.span(1) for match in re.finditer(rf"({NUMBER})\s*(?:kW|W)(?![A-Za-z]|\s*[/·*])", query, re.I))
    remainder = list(query)
    for start, end in [*consumed, *(match.span() for match in LAYER.finditer(query))]:
        remainder[start:end] = " " * (end - start)
    if re.search(NUMBER, "".join(remainder)) or len(re.findall(r"改成|改为|改到|调整为|放宽到|放宽为", query)) > len(changes):
        return clarification("EDIT_REQUIRES_CONFIRMATION", "修改中还有未明确绑定的数值或字段，请确认最终参数；不会仅执行其中一部分修改。")
    if not changes and not re.search(r"重新评估|重新验证|重新计算|再(?:算|检查|验证)一次", query):
        return clarification("EDIT_REQUIRES_CONFIRMATION", "已定位会话中的工程任务。请确认要复查原结果，或说明要修改的字段、数值和单位；原任务会完整保留。")
    if not wall and parent.get("scope") != "bounded_liquid_cooling":
        return clarification("MODEL_CONTEXT_UNAVAILABLE", "该任务尚无可安全继承的结构化工程模型。请确认原模型与参数，不能将这次续改当成独立知识问答。")
    if parent.get("scope") == "bounded_liquid_cooling":
        snapshot = next((step.get("inputs") for step in parent["steps"] if step["step_id"] == "structure_inputs"), None)
        if not snapshot:
            return clarification("MODEL_CONTEXT_UNAVAILABLE", "原液冷任务尚无可继承的参数快照，请确认完整输入后继续。")
        options["liquid_cooling"] = snapshot
    return {"options": options, "changes": changes}


def continue_task(service, request):
    query = request.query.strip()
    if request.current_context_kind == "simulation":
        return {"route": "unhandled"}
    reference, modify = bool(re.search(REFERENCE, query)), bool(re.search(MODIFY, query))
    if not modify and re.search(KNOWLEDGE, query) and not re.search(r"计算|评估|验证|求解|生成报告", query):
        return {"route": "rag"}
    if not reference and not modify:
        try:
            parsed = explicit_wall_inputs({"query": query, "session_id": request.session_id})
            if parsed.get("reference_solver") is not None:
                payload = EngineeringTaskRequest.model_validate(parsed).model_dump(mode="json")
                return {"route": "task", **service.submit(payload), "parent_task_id": None}
        except ValueError as error:
            message = str(error).splitlines()[0][:240]
            return clarification("MULTILAYER_INPUT_INVALID", "多层导热输入需要确认：" + message)
    if re.search(r"(?:新建|建立|开始).{0,8}(?:新|另一个).{0,8}(?:工程|任务|方案)|新的工程|新任务|另一个问题", query):
        return {"route": "unhandled"}
    if not modify and re.search(KNOWLEDGE, query):
        return {"route": "rag"}
    if not reference and not modify:
        return {"route": "unhandled"}
    # A modification must either refer back or name an engineering field; this
    # prevents generic new questions containing '修改' from capturing an old task.
    if not reference and not re.search(rf"上限|设计指标|设计约束|导热系数|热导率|如果允许|重新评估|再检查一次|重新计算|{HOT_LABELS}|{COLD_LABELS}", query, re.I):
        return {"route": "unhandled"}
    if request.current_task_id:
        try:
            parent = service.store.read_task(request.current_task_id)
        except KeyError:
            parent = None
        if parent and parent["request"]["session_id"] != request.session_id:
            parent = None
        if parent:
            parent = service.store.get_task(request.current_task_id)
    else:
        parent = service.store.recent_session_task(request.session_id)
    if parent is None:
        return clarification("ENGINEERING_CONTEXT_MISSING", "当前会话没有可明确绑定的工程任务。请先选择原任务，或提供原方案及参数，再说明需要怎样修改。")
    if request.expected_revision is not None and request.expected_revision != parent["revision"]:
        return clarification("ENGINEERING_CONTEXT_CHANGED", "原任务状态已变化，请刷新并确认要继续的任务。")
    if parent["status"] not in TERMINAL:
        return clarification("ENGINEERING_CONTEXT_ACTIVE", "当前工程任务尚未结束，请等待结果后再修改，避免绑定未完成的输入和结果。")
    delta = _delta(parent, query)
    if delta.get("route"):
        return delta
    continuation = {"parent_task_id": parent["task_id"], "parent_revision": parent["revision"],
                    "query": query, "changes": delta["changes"],
                    "root_query": (parent.get("continuation") or {}).get("root_query") or parent["query"],
                    "inherited_assumptions": deepcopy(parent.get("assumptions") or []),
                    "binding": "current_session_task" if request.current_task_id else "recent_session_task",
                    "execution": "recompute_and_revalidate"}
    accepted = service.retry(parent["task_id"], TaskRetry(expected_revision=parent["revision"], confirmed=True,
        query=query, **delta["options"]), continuation=continuation)
    return {"route": "task", **accepted, "parent_task_id": parent["task_id"], "continuation": continuation}

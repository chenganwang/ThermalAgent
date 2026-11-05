"""Strict explicit layered-wall input adapter for the existing task endpoint."""
import re

from services.retrieval_service.tools.unit_parser import parse_area_m2, parse_conductivity_w_mk, parse_thickness_m
from services.simulation_service.reference import LayeredWallRequest

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
LAYER = re.compile(r"第([一二三四五六七八九十]|\d+)层")
CHINESE_NUMBERS = {word: index for index, word in enumerate("一二三四五六七八九十", 1)}
HOT_LABELS = r"左侧|左端|热侧|热端|高温侧|(?<![A-Za-z0-9_])T_(?:hot|h)(?![A-Za-z0-9_])"
COLD_LABELS = r"右侧|右端|冷侧|冷端|低温侧|(?<![A-Za-z0-9_])T_(?:cold|c)(?![A-Za-z0-9_])"


def layer_number(text):
    return int(text) if text.isdigit() else CHINESE_NUMBERS[text]


def _temperature(query, labels):
    matches = re.findall(rf"(?:{labels})(?:温度)?\s*(?:为|是|=|:|：)?\s*({NUMBER})\s*(K|℃|°C)(?![A-Za-z]|\s*[/·*])", query, re.I)
    if len(matches) != 1:
        return None
    value, unit = matches[0]
    return float(value) + (273.15 if unit.upper() != "K" else 0.)


def _explicit_heat_limit(query):
    subject = r"(?:(?:设计(?:热流)?(?:上限|指标)|热流(?:绝对值)?(?:上限|限值)|上限)\s*(?:改为|改成|改到|放宽到|放宽为|为|是|=|:|：|≤|<=|不超过|不得超过)?|热流(?:绝对值)?\s*(?:不得超过|不超过|≤|<=)|(?:如果)?允许)"
    limits = re.findall(rf"{subject}\s*({NUMBER})\s*(kW|W)(?![A-Za-z]|\s*[/·*])", query, re.I)
    if len(limits) > 1:
        raise ValueError("请只给出一个明确的热流设计上限。")
    if limits:
        value, unit = limits[0]
        return {"max_heat_rate_abs_w": float(value) * (1000. if unit.lower() == "kw" else 1.)}
    if re.search(r"设计指标|设计约束|上限|不(?:得)?超过|限值", query):
        raise ValueError("检测到设计约束，但未能唯一确定热流上限及单位；请明确写出“热流上限 100 W”等数值，不能省略设计验证。")
    return {}


def _merge_query_limits(payload, query):
    inferred = _explicit_heat_limit(query)
    supplied = payload.get("design_criteria") or {}
    if hasattr(supplied, "model_dump"):
        supplied = supplied.model_dump(mode="json", exclude_none=True)
    for key, value in inferred.items():
        if supplied.get(key) is not None and supplied[key] != value:
            raise ValueError("问题中的设计上限与结构化设计指标不一致，请确认本轮最终约束。")
    return {**payload, "design_criteria": {**supplied, **inferred}} if inferred else payload


def explicit_wall_inputs(payload):
    """Only named layers and explicit absolute boundaries become a reference model.

    Incomplete multilayer calculations must not silently enter the legacy scalar
    wall calculator, whose first-match parser represents a different model.
    """
    if not isinstance(payload, dict) or payload.get("liquid_cooling") is not None:
        return payload
    query = str(payload.get("query") or "")
    if payload.get("reference_solver") is not None:
        supplied = LayeredWallRequest.model_validate(payload["reference_solver"]).model_dump(mode="json")
        # Explicit physical input in the new question cannot be discarded just
        # because an API caller also supplied an older structured snapshot.
        for field, labels in (("left_temperature_k", HOT_LABELS), ("right_temperature_k", COLD_LABELS)):
            value = _temperature(query, labels)
            if value is not None and value != supplied[field]:
                raise ValueError("问题中的边界温度与结构化参考模型不一致，请确认本轮最终输入。")
        if len(list(LAYER.finditer(query))) >= 2 and re.search(rf"{NUMBER}\s*(?:m|mm|W)", query, re.I):
            described = explicit_wall_inputs({"query": query})
            if described.get("reference_solver") is not None and described["reference_solver"] != supplied:
                raise ValueError("问题中的多层参数与结构化参考模型不一致，请确认本轮最终输入。")
        return _merge_query_limits({**payload, "reference_solver": supplied}, query)
    if not re.search(r"(?:两层|双层|多层|[三四五六七八九十\d]+层).{0,12}(?:平壁|导热|壁)|第二层", query):
        return payload
    if not re.search(r"计算|评估|验证|求|报告|设计|再算", query) and not re.search(rf"{NUMBER}\s*(?:m|mm|K|W)", query, re.I):
        return payload
    if re.search(r"瞬态|辐射|接触热阻|内热源|体积热源|温变物性|导热系数随", query):
        raise ValueError("该描述包含当前一维稳态参考模型不支持的物理条件，请确认适用模型后再执行。")
    markers = list(LAYER.finditer(query))
    numbers = [layer_number(match[1]) for match in markers]
    layers = []
    if numbers != list(range(1, len(markers) + 1)) or len(markers) < 2:
        raise ValueError("请按第一层、第二层依次提供每层厚度和导热系数，并提供面积、左侧与右侧绝对温度。")
    declared = re.search(r"(?<!第)(两|双|[三四五六七八九十]|\d+)层(?:平壁|壁|导热)", query)
    if declared:
        count = 2 if declared[1] in {"两", "双"} else layer_number(declared[1])
        if count != len(markers):
            raise ValueError("声明层数与提供的各层参数数量不一致，请确认完整模型。")
    for index, marker in enumerate(markers):
        segment = query[marker.end():markers[index + 1].start() if index + 1 < len(markers) else len(query)]
        # Indexed labels are aliases only within their explicitly named layer;
        # mismatched indices must never be reassigned to whichever layer is nearby.
        indexed = list(re.finditer(r"(?<![A-Za-z0-9_])([Lk])_?(\d+)(?![A-Za-z0-9_])", segment, re.I))
        if any(int(match[2]) != numbers[index] for match in indexed):
            raise ValueError("L/k 参数下标与声明层号不一致，请确认每个厚度和导热系数所属的层。")
        segment = re.sub(r"(?<![A-Za-z0-9_])([Lk])_?(\d+)(?![A-Za-z0-9_])",
                         lambda match: "厚度" if match[1].lower() == "l" else "导热系数", segment, flags=re.I)
        segment = re.sub(r"(?<!度)厚(?=\s*[\d.])", "厚度", segment)
        if len(re.findall(r"厚度|壁厚|thickness|\bL\b", segment, re.I)) != 1 or len(re.findall(r"导热系数|\bk(?=\s*(?:为|是|=|:|：)?\s*[-+\d.])", segment, re.I)) != 1:
            raise ValueError("每层需要唯一的厚度和导热系数；如存在候选值或修改值，请确认最终输入。")
        if not re.search(rf"(?:导热系数|\bk\b)\s*(?:为|是|=|:|：)?\s*{NUMBER}\s*W\s*/\s*\(?m\s*[*·]?\s*K\)?", segment, re.I):
            raise ValueError("请明确各层导热系数单位 W/(m·K)，不能推断缺失或其他单位。")
        thickness, conductivity = parse_thickness_m(segment), parse_conductivity_w_mk(segment)
        if thickness is None or conductivity is None:
            raise ValueError("多层模型参数不完整；请为每层明确给出厚度及导热系数，不能用一层参数代替其他层。")
        layers.append({"thickness_m": thickness, "conductivity_w_mk": conductivity})
    # "面积 A = ..." is one explicitly named quantity with a symbol alias,
    # not two competing inputs. Separate repeated area values remain invalid.
    area_query = re.sub(r"面积\s*A\b", "面积", query, flags=re.I)
    area = parse_area_m2(area_query) if len(re.findall(r"面积|\bA\b", area_query)) == 1 else None
    left = _temperature(query, HOT_LABELS)
    right = _temperature(query, COLD_LABELS)
    if any(value is None for value in (area, left, right)):
        raise ValueError("请明确面积以及左侧和右侧绝对温度（K 或 ℃）；不能仅由温差推断温度边界。")
    result = {**payload, "reference_solver": LayeredWallRequest.model_validate({"area_m2": area,
        "left_temperature_k": left, "right_temperature_k": right, "layers": layers}).model_dump(mode="json")}
    return _merge_query_limits(result, query)

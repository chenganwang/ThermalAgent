from __future__ import annotations

import re


NUM = r"(-?\d+(?:\.\d+)?)"
TEMP_C_UNIT = r"(?:℃|°C|C|摄氏度)"
TEMP_DIFF_UNIT = r"(?:K|℃|°C|C)"


def normalize_text(text: str) -> str:
    """Normalize common punctuation while preserving engineering units."""

    value = text or ""
    replacements = {
        "（": "(",
        "）": ")",
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "＝": "=",
        "＊": "*",
        "×": "×",
        "㎥": "m3",
        "m³": "m3",
        "㎡": "m2",
        "²": "2",
        "·": "*",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return re.sub(r"\s+", " ", value).strip()


def has_water(text: str) -> bool:
    lowered = normalize_text(text).lower()
    if re.search(r"(?<!乙二醇)(?<!丙二醇)水(?!溶液)", lowered):
        return True
    return "water" in lowered


def _find_float(pattern: str, text: str, *, flags: int = re.IGNORECASE) -> float | None:
    match = re.search(pattern, normalize_text(text), flags)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _find_power_after_label(labels: str, text: str) -> float | None:
    normalized = normalize_text(text)
    pattern = rf"(?:{labels})\s*(?:=|为|是|约|大约|:)?\s*{NUM}\s*(kW|KW|kw|W|w|瓦|千瓦)(?!\s*/)"
    match = re.search(pattern, normalized, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"kw", "千瓦"}:
        value *= 1000.0
    return value


def parse_power_w(text: str) -> float | None:
    """Parse heat load or power in W, including kW."""

    labeled = _find_power_after_label(r"热负荷|功耗|芯片功耗|热量|Q|P", text)
    if labeled is not None:
        return labeled
    normalized = normalize_text(text)
    match = re.search(NUM + r"\s*(kW|KW|kw|W|w|瓦|千瓦)(?!\s*/)", normalized)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    return value * 1000.0 if unit in {"kw", "千瓦"} else value


def parse_inlet_temperature_c(text: str) -> float | None:
    return _find_float(
        rf"(?:入口水温|入口温度|冷却液入口温度|进水温度|T_in)\s*(?:=|为|是|约|大约|:)?\s*{NUM}\s*{TEMP_C_UNIT}",
        text,
    )


def parse_limit_temperature_c(text: str) -> float | None:
    return (
        _find_float(
            rf"(?:不超过|最高温度|最高|限制|上限|T_limit|T_max)\s*(?:=|为|是|约|大约|:)?\s*{NUM}\s*{TEMP_C_UNIT}",
            text,
        )
        or _find_float(rf"(?:希望芯片不超过)\s*{NUM}\s*{TEMP_C_UNIT}", text)
    )


def parse_safety_margin_c(text: str) -> float | None:
    return _find_float(rf"(?:安全裕量|safety margin)\s*(?:=|为|是|约|:)?\s*{NUM}\s*{TEMP_DIFF_UNIT}", text)


def parse_delta_t_k(text: str) -> float | None:
    normalized = normalize_text(text)
    qualifiers = r"(?:=|为|是|约|大约|不超过|不高于|不大于|小于等于|<=|≤|:)?"
    patterns = [
        rf"(?:允许|目标|最大|最高)?(?:冷却液|水)?(?:温升|温差)\s*{qualifiers}\s*{NUM}\s*{TEMP_DIFF_UNIT}",
        rf"(?:进出口|出入口|入口出口|出口入口)\s*温差\s*{qualifiers}\s*{NUM}\s*{TEMP_DIFF_UNIT}",
        rf"(?:delta[_\s]*T|dT|ΔT)\s*{qualifiers}\s*{NUM}\s*{TEMP_DIFF_UNIT}",
        rf"(?:allowed\s+temperature\s+rise|temperature\s+rise|delta\s*T|dT)\s*(?:=|is|of|about|around|no\s+more\s+than|not\s+exceed(?:ing)?|<=|≤|:)?\s*{NUM}\s*{TEMP_DIFF_UNIT}",
    ]
    for pattern in patterns:
        value = _find_float(pattern, normalized)
        if value is not None:
            return value
    return None


def parse_thermal_resistance_k_per_w(text: str) -> float | None:
    return _find_float(
        r"(?:总热阻|热阻|R_total|Rθ|Rth)\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*(?:K\s*/\s*W|℃\s*/\s*W|°C\s*/\s*W)",
        text,
    )


def parse_cp_j_kgk(text: str) -> float | None:
    return _find_float(
        r"(?:比热容|比热|cp|specific heat)\s*(?:=|为|是|约|大约|:)?\s*"
        + NUM
        + r"\s*(?:J\s*/\s*\(?kg\s*\*?\s*K\)?|J\s*/\s*kgK|J/kgK|J)",
        text,
    )


def parse_density_kg_m3(text: str) -> float | None:
    return _find_float(
        r"(?:密度|rho|density)\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*(?:kg\s*/\s*m3|kg/m3)?",
        text,
    )


def parse_mass_flow_kg_s(text: str) -> float | None:
    return _find_float(
        r"(?:质量流量|流量|m_dot|m)\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*(?:kg\s*/\s*s|kg/s)",
        text,
    )


def parse_volume_flow_m3_s(text: str) -> float | None:
    normalized = normalize_text(text)
    l_min = _find_float(r"(?:体积流量|流量|V_dot|V)?\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*(?:L\s*/\s*min|L/min|lpm)", normalized)
    if l_min is not None:
        return l_min / 60000.0
    return _find_float(
        r"(?:体积流量|流量|V_dot|V)?\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*(?:m3\s*/\s*s|m\^3\s*/\s*s)",
        normalized,
    )


def parse_volume_flow_l_min(text: str) -> float | None:
    value = parse_volume_flow_m3_s(text)
    return None if value is None else value * 60000.0


def parse_hydraulic_diameter_mm(text: str) -> float | None:
    """Parse a labeled pipe or hydraulic diameter in millimetres."""

    return _find_float(
        r"(?:水力直径|管径|内径|hydraulic\s+diameter|pipe\s+diameter|diameter|D)"
        r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*mm\b",
        text,
    )


def parse_hydraulic_length_m(text: str) -> float | None:
    """Parse a labeled hydraulic path length in metres."""

    normalized = normalize_text(text)
    millimetres = _find_float(
        r"(?:长度|管长|流道长度|流道|length|pipe\s+length|L)"
        r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*mm\b",
        normalized,
    )
    if millimetres is not None:
        return millimetres / 1000.0
    return _find_float(
        r"(?:长度|管长|流道长度|流道|length|pipe\s+length|L)"
        r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*m(?!m)\b",
        normalized,
    )


def parse_dynamic_viscosity_pa_s(text: str) -> float | None:
    return _find_float(
        r"(?:动力黏度|动力粘度|黏度|粘度|dynamic\s+viscosity|viscosity|mu|μ)"
        r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*(?:Pa\s*[*.·]?\s*s|Pa\s*s)?",
        text,
    )


def parse_minor_loss_coefficient(text: str) -> float | None:
    return _find_float(
        r"(?:局部阻力系数|minor\s+loss\s+coefficient|loss\s+coefficient|K)"
        r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\b",
        text,
    )


def parse_friction_factor(text: str) -> float | None:
    return _find_float(
        r"(?:摩阻系数|达西摩阻系数|friction\s+factor|Darcy\s+factor|f)"
        r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\b",
        text,
    )


def parse_roughness_m(text: str) -> float | None:
    normalized = normalize_text(text)
    millimetres = _find_float(
        r"(?:粗糙度|roughness|epsilon|ε)\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*mm\b",
        normalized,
    )
    if millimetres is not None:
        return millimetres / 1000.0
    return _find_float(
        r"(?:粗糙度|roughness|epsilon|ε)\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*m(?!m)\b",
        normalized,
    )


def parse_temperature_c(text: str) -> float | None:
    labeled = _find_float(
        rf"(?:冷却液温度|流体温度|温度|temperature|T)\s*(?:=|为|是|约|大约|:)?\s*{NUM}\s*{TEMP_C_UNIT}",
        text,
    )
    if labeled is not None:
        return labeled
    return _find_float(rf"(?:at|在)\s*{NUM}\s*{TEMP_C_UNIT}", text)


def parse_pressure_drop_kpa(text: str) -> float | None:
    pascals = _find_float(
        r"(?:压降|压力损失|pressure\s+drop|delta[_\s]*p|dP)"
        r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*Pa\b",
        text,
    )
    if pascals is not None:
        return pascals / 1000.0
    return _find_float(
        r"(?:压降|压力损失|pressure\s+drop|delta[_\s]*p|dP)"
        r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*kPa\b",
        text,
    )


def parse_required_head_m(text: str) -> float | None:
    return _find_float(
        r"(?:所需扬程|目标扬程|扬程|required\s+head|pump\s+head|head)"
        r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*m\b",
        text,
    )


def parse_thickness_m(text: str) -> float | None:
    normalized = normalize_text(text)
    label = r"(?:厚度|壁厚|thickness|\bL\b)"
    mm = _find_float(label + r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*mm", normalized)
    if mm is not None:
        return mm / 1000.0
    cm = _find_float(label + r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*cm", normalized)
    if cm is not None:
        return cm / 100.0
    return _find_float(label + r"\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*m(?!m)", normalized)


def parse_area_m2(text: str) -> float | None:
    normalized = normalize_text(text)
    dim = re.search(NUM + r"\s*(mm|cm|m)\s*[xX×*]\s*" + NUM + r"\s*(mm|cm|m)\b", normalized)
    if dim:
        a = float(dim.group(1))
        b = float(dim.group(3))
        unit_a = dim.group(2)
        unit_b = dim.group(4)
        scale = {"mm": 0.001, "cm": 0.01, "m": 1.0}
        return a * scale[unit_a] * b * scale[unit_b]
    mm2 = _find_float(r"(?:面积|A)\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*(?:mm2|mm\^2)", normalized)
    if mm2 is not None:
        return mm2 * 1e-6
    cm2 = _find_float(r"(?:面积|A)\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*(?:cm2|cm\^2)", normalized)
    if cm2 is not None:
        return cm2 * 1e-4
    return _find_float(r"(?:面积|A)\s*(?:=|为|是|约|大约|:)?\s*" + NUM + r"\s*(?:m2|m\^2)", normalized)


def parse_conductivity_w_mk(text: str) -> float | None:
    normalized = normalize_text(text)
    with_unit = _find_float(
        r"(?:导热系数|k)\s*(?:=|为|是|约|大约|:)?\s*"
        + NUM
        + r"\s*(?:W\s*/\s*\(?m\s*\*?\s*K\)?|W\s*/\s*mK|W/mK|W)",
        normalized,
    )
    if with_unit is not None:
        return with_unit
    return _find_float(
        r"(?:导热系数|thermal\s+conductivity|\bk\b)\s*(?:=|为|是|约|大约|:)?\s*" + NUM,
        normalized,
    )


def parse_hot_temperature_c(text: str) -> float | None:
    return _find_float(
        rf"(?:热端(?:温度)?|热侧(?:温度)?|高温侧(?:温度)?|T_hot|T_h|hot(?:\s+side)?(?:\s+temperature)?)"
        rf"\s*(?:=|为|是|约|大约|:)?\s*{NUM}\s*{TEMP_C_UNIT}",
        normalize_text(text),
    )


def parse_cold_temperature_c(text: str) -> float | None:
    return _find_float(
        rf"(?:冷端(?:温度)?|冷侧(?:温度)?|低温侧(?:温度)?|T_cold|T_c|cold(?:\s+side)?(?:\s+temperature)?)"
        rf"\s*(?:=|为|是|约|大约|:)?\s*{NUM}\s*{TEMP_C_UNIT}",
        normalize_text(text),
    )


def parse_plane_wall_temperature_difference_k(text: str) -> float | None:
    """Parse the temperature difference across a plane wall."""

    normalized = normalize_text(text)
    direct_delta = parse_delta_t_k(normalized)
    if direct_delta is not None:
        return abs(float(direct_delta))

    paired_patterns = [
        rf"(?:两侧|两面|两端|内外|表面)(?:温度)?(?:分别)?(?:为|=|:)?\s*{NUM}\s*{TEMP_C_UNIT}\s*(?:和|与|,|、|/|到|-)\s*{NUM}\s*{TEMP_C_UNIT}",
        rf"(?:T1|T_hot|T_h|热侧温度|高温侧温度)\s*(?:=|为|:)?\s*{NUM}\s*{TEMP_C_UNIT}.*?(?:T2|T_cold|T_c|冷侧温度|低温侧温度)\s*(?:=|为|:)?\s*{NUM}\s*{TEMP_C_UNIT}",
        rf"(?:T2|T_cold|T_c|冷侧温度|低温侧温度)\s*(?:=|为|:)?\s*{NUM}\s*{TEMP_C_UNIT}.*?(?:T1|T_hot|T_h|热侧温度|高温侧温度)\s*(?:=|为|:)?\s*{NUM}\s*{TEMP_C_UNIT}",
    ]
    for pattern in paired_patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            return abs(float(match.group(1)) - float(match.group(2)))

    if re.search(r"平壁|导热量|稳态导热|一维导热|传热量", normalized):
        values = [float(value) for value in re.findall(NUM + r"\s*" + TEMP_C_UNIT, normalized, re.IGNORECASE)]
        if len(values) >= 2:
            return abs(values[0] - values[1])
    return None


__all__ = [name for name in globals() if name.startswith("parse_")] + ["has_water", "normalize_text"]

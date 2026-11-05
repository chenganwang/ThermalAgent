from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import KnowledgeUnitCandidate
from .normalizer import compact_text, make_dedup_key, sentence_windows


@dataclass(frozen=True)
class FormulaRule:
    name: str
    pattern: re.Pattern[str]
    expression: str
    variables: dict[str, str]
    units: dict[str, str]
    application_hint: str


FORMULA_RULES = [
    FormulaRule(
        name="liquid_heat_balance",
        pattern=re.compile(r"\bq\s*=\s*(?:m(?:_dot|dot)?|ṁ)\s*\*?\s*cp\s*\*?\s*(?:ΔT|dT|delta\s*T)\b", re.I),
        expression="Q = m_dot * cp * ΔT",
        variables={"Q": "heat_load_W", "m_dot": "mass_flow_kg_s", "cp": "specific_heat_J_kgK", "ΔT": "temperature_rise_K"},
        units={"Q": "W", "m_dot": "kg/s", "cp": "J/(kg*K)", "ΔT": "K"},
        application_hint="liquid cooling heat balance",
    ),
    FormulaRule(
        name="mass_flow_from_heat_balance",
        pattern=re.compile(r"\bm(?:_dot|dot)?\s*=\s*q\s*/\s*\(?\s*cp\s*\*?\s*(?:ΔT|dT|delta\s*T)\s*\)?", re.I),
        expression="m_dot = Q / (cp * ΔT)",
        variables={"m_dot": "mass_flow_kg_s", "Q": "heat_load_W", "cp": "specific_heat_J_kgK", "ΔT": "temperature_rise_K"},
        units={"m_dot": "kg/s", "Q": "W", "cp": "J/(kg*K)", "ΔT": "K"},
        application_hint="required coolant mass flow",
    ),
    FormulaRule(
        name="conduction_resistance",
        pattern=re.compile(r"\br\s*=\s*l\s*/\s*\(?\s*k\s*\*?\s*a\s*\)?", re.I),
        expression="R = L / (kA)",
        variables={"R": "conduction_resistance_K_per_W", "L": "thickness_m", "k": "thermal_conductivity_W_mK", "A": "area_m2"},
        units={"R": "K/W", "L": "m", "k": "W/(m*K)", "A": "m2"},
        application_hint="one-dimensional conduction resistance",
    ),
    FormulaRule(
        name="junction_temperature",
        pattern=re.compile(r"\btj\s*=\s*ta\s*\+\s*p\s*\*?\s*r(?:theta|θ|θ)?\b", re.I),
        expression="Tj = Ta + P * Rθ",
        variables={"Tj": "junction_temperature_C", "Ta": "ambient_or_inlet_temperature_C", "P": "power_W", "Rθ": "thermal_resistance_K_per_W"},
        units={"Tj": "°C", "Ta": "°C", "P": "W", "Rθ": "K/W"},
        application_hint="junction temperature estimate",
    ),
    FormulaRule(
        name="required_thermal_resistance",
        pattern=re.compile(r"\br(?:theta|θ)?\s*=\s*\(?\s*tj,?max\s*-\s*ta\s*\)?\s*/\s*p\b", re.I),
        expression="Rθ = (Tj,max - Ta) / P",
        variables={"Rθ": "thermal_resistance_K_per_W", "Tj,max": "maximum_junction_temperature_C", "Ta": "ambient_or_inlet_temperature_C", "P": "power_W"},
        units={"Rθ": "K/W", "Tj,max": "°C", "Ta": "°C", "P": "W"},
        application_hint="thermal resistance target",
    ),
    FormulaRule(
        name="reynolds_number",
        pattern=re.compile(r"\bre\s*=\s*rho\s*\*?\s*v\s*\*?\s*d\s*/\s*mu\b", re.I),
        expression="Re = rho * v * D / mu",
        variables={"Re": "Reynolds_number", "rho": "density_kg_m3", "v": "velocity_m_s", "D": "hydraulic_diameter_m", "mu": "dynamic_viscosity_Pa_s"},
        units={"Re": "dimensionless", "rho": "kg/m3", "v": "m/s", "D": "m", "mu": "Pa*s"},
        application_hint="flow regime estimate",
    ),
    FormulaRule(
        name="darcy_pressure_drop",
        pattern=re.compile(r"(?:Δp|dp)\s*=\s*f\s*\*?\s*l\s*/\s*d\s*\*?\s*rho\s*\*?\s*v(?:\^?2|2)\s*/\s*2", re.I),
        expression="Δp = f * L/D * rho * v^2 / 2",
        variables={"Δp": "pressure_drop_Pa", "f": "friction_factor", "L": "length_m", "D": "diameter_m", "rho": "density_kg_m3", "v": "velocity_m_s"},
        units={"Δp": "Pa", "L": "m", "D": "m", "rho": "kg/m3", "v": "m/s"},
        application_hint="pipe/channel pressure drop estimate",
    ),
]


def extract(text: str, source: dict) -> list[KnowledgeUnitCandidate]:
    normalized = compact_text(text)
    if not normalized:
        return []

    candidates: list[KnowledgeUnitCandidate] = []
    for rule in FORMULA_RULES:
        if not rule.pattern.search(normalized):
            continue
        variables_text = ", ".join(f"{name}={description}" for name, description in rule.variables.items())
        content = f"{rule.expression}; variables: {variables_text}"
        candidates.append(
            KnowledgeUnitCandidate(
                unit_type="formula",
                canonical_name=rule.name,
                title=rule.expression,
                content=content,
                aliases=[],
                properties={
                    "expression": rule.expression,
                    "variables": rule.variables,
                    "units": rule.units,
                    "application_hint": rule.application_hint,
                },
                source=source,
                confidence=0.86,
                extraction_method="rule_based",
                dedup_key=make_dedup_key("formula", rule.name, rule.expression),
                warnings=[],
            )
        )
    return candidates

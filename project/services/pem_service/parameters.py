"""Unit and geometric checks; no invented manufacturing limits."""
from __future__ import annotations

import hashlib
import json
import math

from .contracts import StudyRequest

LENGTH_UNITS = {"m": 1.0, "mm": 1e-3, "cm": 1e-2, "um": 1e-6}
LENGTH_NAMES = ("channel_width", "channel_depth", "channel_spacing", "plate_width", "plate_length", "plate_thickness")
REQUIRED_NAMES = (*LENGTH_NAMES, "channel_count", "topology")
TOPOLOGIES = ("parallel", "serpentine", "interdigitated")


class ParameterError(ValueError):
    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def normalize_boundary(boundary):
    scales = {"mass_flow_rate": {"kg/s": 1, "g/s": 0.001, "kg/h": 1 / 3600},
              "outlet_pressure": {"Pa": 1, "kPa": 1000, "MPa": 1e6}}
    units = {"mass_flow_rate": "kg/s", "temperature": "K", "outlet_pressure": "Pa"}
    normalized = {}
    for name in units:
        value, unit = boundary[name]["value"], boundary[name]["unit"]
        if name == "temperature":
            if unit not in {"K", "degC"}:
                raise ParameterError(["temperature: unit must be K or degC"])
            si = value + (273.15 if unit == "degC" else 0)
        else:
            if unit not in scales[name]:
                raise ParameterError([f"{name}: invalid unit {unit}"])
            si = value * scales[name][unit]
        if not math.isfinite(si) or si <= 0:
            raise ParameterError([f"{name}: normalized value must be positive and finite"])
        normalized[name] = {"value": si, "unit": units[name]}
    normalized["additional"] = boundary.get("additional", {})
    return normalized


def normalize_parameters(specs, values):
    normalized, reasons = {}, []
    for spec in specs:
        name = spec["name"]
        value = values.get(name)
        if value is None:
            reasons.append(f"{name}: missing parameter")
        elif spec["kind"] == "categorical":
            if value not in spec["choices"]:
                reasons.append(f"{name}: value not in declared choices")
            else:
                normalized[name] = value
        elif isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            reasons.append(f"{name}: value must be finite numeric")
        elif not spec["lower"] <= value <= spec["upper"]:
            reasons.append(f"{name}: outside declared bounds")
        elif spec["kind"] == "integer" and value != int(value):
            reasons.append(f"{name}: integer required")
        else:
            si = value * LENGTH_UNITS[spec["unit"]] if name in LENGTH_NAMES else int(value)
            if not math.isfinite(si) or (si <= 0 and name != "channel_spacing") or si < 0:
                reasons.append(f"{name}: illegal physical dimension")
            else:
                normalized[name] = si
    unknown = set(values) - {s["name"] for s in specs}
    if unknown:
        reasons.append("Unknown parameters: " + ", ".join(sorted(unknown)))
    if reasons:
        raise ParameterError(reasons)
    return normalized


def candidate_constraints(specs, values):
    try:
        p = normalize_parameters(specs, values)
    except ParameterError as exc:
        return None, exc.reasons, []
    reasons, warnings = [], []
    envelope = p["channel_count"] * p["channel_width"] + (p["channel_count"] - 1) * p["channel_spacing"]
    if not math.isfinite(envelope) or envelope > p["plate_width"] + 1e-12 * p["plate_width"]:
        reasons.append("geometry: channel_count*channel_width+(channel_count-1)*channel_spacing exceeds plate_width")
    if p["channel_depth"] >= p["plate_thickness"]:
        reasons.append("geometry: channel_depth must be below plate_thickness")
    if p["topology"] != "parallel":
        warnings.append("needs_expert_validation: nonparallel topology envelope checks do not validate CAD routes, bends or manifolds")
    return p, reasons, warnings


def validate_study(payload):
    # Check the original metadata before Pydantic JSON-mode normalization can turn NaN into null.
    try:
        canonical_hash(payload)
    except (ValueError, TypeError):
        raise ParameterError(["Research input and metadata must be finite JSON"])
    definition = StudyRequest.model_validate(payload).model_dump(mode="json")
    # Strict finite JSON catches NaN hidden in research metadata too.
    try:
        canonical_hash(definition)
    except (ValueError, TypeError):
        raise ParameterError(["Research conditions and additional metadata must be finite JSON"])
    specs = definition["parameter_space"]
    names = [s["name"] for s in specs]
    reasons = []
    if len(names) != len(set(names)):
        reasons.append("Duplicate parameter names")
    if set(names) != set(REQUIRED_NAMES):
        reasons.append("Required parameter set: " + ", ".join(REQUIRED_NAMES))
    for s in specs:
        name, kind = s["name"], s["kind"]
        if name in LENGTH_NAMES:
            if kind != "continuous" or s["unit"] not in LENGTH_UNITS:
                reasons.append(f"{name}: continuous length with m/mm/cm/um required")
        elif name == "channel_count":
            if kind != "integer" or s["unit"] != "1":
                reasons.append("channel_count: integer with unit 1 required")
        elif name == "topology":
            if kind != "categorical" or s["unit"] != "1":
                reasons.append("topology: categorical with unit 1 required")
        if kind == "categorical":
            choices = s["choices"]
            if not choices or len(set(choices)) != len(choices) or any(v not in TOPOLOGIES for v in choices):
                reasons.append(f"{name}: distinct declared parallel/serpentine/interdigitated choices required")
            if s["lower"] is not None or s["upper"] is not None:
                reasons.append(f"{name}: categorical bounds are not applicable")
        else:
            lo, hi = s["lower"], s["upper"]
            if lo is None or hi is None or not math.isfinite(lo) or not math.isfinite(hi) or lo > hi:
                reasons.append(f"{name}: finite lower <= upper required")
            elif lo < 0 or (name != "channel_spacing" and lo == 0):
                reasons.append(f"{name}: illegal physical dimension")
            elif kind == "integer" and (lo != int(lo) or hi != int(hi)):
                reasons.append(f"{name}: integer bounds required")
            if s["choices"] is not None:
                reasons.append(f"{name}: choices are only valid for categorical parameters")
    if reasons:
        raise ParameterError(reasons)
    normalized_boundary = normalize_boundary(definition["boundary_conditions"])
    bounds = {s["name"]: s for s in specs}
    # Reject definitions with no possible feasible geometry, without claiming all sampled points are feasible.
    min_values = {s["name"]: (s["choices"][0] if s["kind"] == "categorical" else s["lower"]) for s in specs}
    min_values["plate_width"] = bounds["plate_width"]["upper"]
    min_values["plate_thickness"] = bounds["plate_thickness"]["upper"]
    _, errors, _ = candidate_constraints(specs, min_values)
    if errors:
        raise ParameterError(["Parameter space has no feasible geometry: " + s for s in errors])
    warnings = ["User-declared ranges are research bounds, not certified manufacturing limits.",
                "Geometry envelope checks do not validate manifolds, sealing, bends or electrochemistry.",
                "Quality tolerance is a numerical screening policy, not a professional acceptance standard."]
    if definition["physics_model"] != "single_phase":
        warnings.append("Two-phase/electrochemical physics require expert model details and total mass accounting in imported results.")
    return definition, normalized_boundary, warnings


def example_study():
    ranges = {"channel_width": (0.8, 1.2), "channel_depth": (0.4, 0.8), "channel_spacing": (0.5, 1.0),
              "plate_width": (25, 25), "plate_length": (50, 50), "plate_thickness": (2, 2)}
    specs = [{"name": n, "kind": "continuous", "unit": "mm", "lower": v[0], "upper": v[1],
              "source": "Synthetic demonstration research bounds; expert validation pending"} for n, v in ranges.items()]
    specs += [{"name": "channel_count", "kind": "integer", "unit": "1", "lower": 8, "upper": 12,
               "source": "Synthetic demonstration layout count"},
              {"name": "topology", "kind": "categorical", "unit": "1", "choices": ["parallel"],
               "source": "Synthetic parallel demonstration"}]
    return {"title": "PEM parallel flowfield demonstration", "objective": "Observed pressure-drop and outlet flow screening only",
            "side": "anode", "physics_model": "single_phase", "model_version": "demo-single-phase-v1", "fluid": "water",
            "boundary_conditions": {"mass_flow_rate": {"value": 0.001, "unit": "kg/s"},
                                    "temperature": {"value": 298.15, "unit": "K"},
                                    "outlet_pressure": {"value": 101325, "unit": "Pa"}, "additional": {}},
            "parameter_space": specs, "research_conditions": {"provenance": "synthetic_demo"},
            "quality_policy": {"mass_balance_relative_tolerance": 0.01}, "knowledge_sources": []}

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from services.simulation_service.catalog.model_registry import ModelRegistry
from services.simulation_service.catalog.schemas import ModelDefinition
from services.simulation_service.modeling.lifecycle import GeneratedModelLifecycleError, GeneratedModelService
from services.retrieval_service.task.network_domain import detect_network_domain

from .simulation_mode_contracts import SimulationPlan


_NUMBER = r"([-+]?\d+(?:\.\d+)?)"


class NaturalLanguageSimulationPlanner:
    """Deterministic planner over the reviewed simulation catalog."""

    def __init__(
        self,
        *,
        model_registry: ModelRegistry | None = None,
        generated_model_service: GeneratedModelService | None = None,
    ) -> None:
        self.model_registry = model_registry or ModelRegistry()
        self.generated_model_service = generated_model_service or GeneratedModelService()

    @staticmethod
    def should_plan(query: str) -> bool:
        text = str(query or "").strip()
        lowered = text.lower()
        network_semantics = detect_network_domain(text)
        if network_semantics["domain"] == "thermal" and network_semantics["action"] in {"plan", "simulate"}:
            return True
        explicit = any(token in lowered for token in ("仿真", "模拟", "matlab", "cfd", "simulation"))
        engineering_assessment = (
            any(token in text for token in ("冷板", "液冷回路", "平壁", "稳态导热", "瞬态升温"))
            and any(token in text for token in ("分析", "评估", "计算", "能不能", "压住", "温度"))
        )
        engineering_specification = (
            any(token in text for token in ("平壁", "壁厚", "液冷回路", "瞬态"))
            and bool(re.search(r"\d", text))
            and any(token in lowered for token in ("mm", "cm", "平方米", "℃", "w", "kg", "秒"))
        )
        return explicit or engineering_assessment or engineering_specification

    def plan(self, query: str) -> SimulationPlan:
        text = str(query or "").strip()
        if self._is_cfd(text):
            return self._cfd_plan(text)
        if "集总" in text or ("瞬态" in text and "升温" in text):
            return self._transient_plan(text)
        if "液冷" in text or "回路" in text:
            return self._liquid_loop_plan(text)
        if "平壁" in text or "壁厚" in text:
            return self._plane_wall_plan(text)
        if any(token in text for token in ("稳态导热", "导热仿真", "热传导仿真")):
            return self._ambiguous_conduction_plan(text)
        return self._no_compatible_model_plan(text)

    def _no_compatible_model_plan(self, text: str) -> SimulationPlan:
        try:
            generated = self.generated_model_service.find_enabled_by_requirement(text)
            generated = generated or self.generated_model_service.create_candidate(text)
        except GeneratedModelLifecycleError:
            generated = None
        if generated and (
            (generated.get("model_ir") or {}).get("components")
            or generated.get("synthesis_status") == "needs_input"
        ):
            return self._generated_model_plan(text, generated)
        return SimulationPlan(
            plan_id=_plan_id(),
            user_goal=text,
            simulation_type="no_compatible_model",
            selected_model_id=None,
            selected_model_name=None,
            selection_reason="no_compatible_model",
            candidate_models=[],
            model_selection_confidence=0.0,
            execution_allowed=False,
            execution_block_reason="NO_COMPATIBLE_MODEL",
            risk_warnings=["当前请求没有匹配到 canonical model registry 中的兼容模型。"],
            status="no_compatible_model",
        )

    def _generated_model_plan(self, text: str, generated: dict[str, Any]) -> SimulationPlan:
        model_ir = generated.get("model_ir") if isinstance(generated.get("model_ir"), dict) else {}
        enabled = bool(generated.get("execution_eligible"))
        missing = [_public_generated_missing_input(value) for value in generated.get("missing_parameters") or []]
        validation_valid = bool((generated.get("validation_report") or {}).get("valid"))
        if enabled:
            reason = None
        elif missing:
            reason = "GENERATED_MODEL_INPUTS_INCOMPLETE"
        elif not validation_valid:
            reason = "GENERATED_MODEL_VALIDATION_FAILED"
        else:
            reason = "GENERATED_MODEL_APPROVAL_REQUIRED"
        summary = dict(generated.get("model_summary") or {})
        requested = model_ir.get("requested_outputs") if isinstance(model_ir.get("requested_outputs"), list) else []
        return SimulationPlan(
            plan_id=_plan_id(),
            user_goal=text,
            simulation_type="generated_thermal_model",
            scenario_id="autonomous_generated_thermal",
            scenario_confidence=0.85,
            model_id=str(model_ir.get("model_id") or "") or None,
            selected_model_id=str(model_ir.get("model_id") or "") or None,
            selected_model_name="Autonomous generated thermal model",
            selection_reason=(
                f"enabled_generated_model:{generated.get('_reuse_match', 'eligible_match')}"
                if enabled else "no_catalog_match:generated_model_candidate"
            ),
            candidate_models=[{
                "model_id": model_ir.get("model_id"),
                "generation_id": generated.get("generation_id"),
                "status": generated.get("status"),
                "source": "generated",
                "confidence": 0.85,
                "summary": summary,
            }],
            model_selection_confidence=0.85,
            model_version=f"revision-{generated.get('revision')}",
            model_source="generated",
            generated_model_id=str(generated.get("generation_id") or "") or None,
            generated_model_revision=int(generated.get("revision") or 0) or None,
            generated_model_status=str(generated.get("status") or "draft"),
            generated_model_summary=summary,
            missing_inputs=missing,
            assumptions=["模型拓扑来自已验证 Model IR；MATLAB block mapping 仅由服务器注册表解析。"],
            boundary_conditions=[str(item.get("kind") or "") for item in model_ir.get("boundary_conditions") or [] if isinstance(item, dict)],
            solver_backend="matlab",
            solver={"type": "simscape_generated", "serialization": "MatlabRuntimeManager_RLock"},
            execution_steps=["生成 Model IR", "分层验证", "确定性编译", "Admin 审批并启用", "用户确认", "受控 MATLAB 执行"],
            expected_outputs=[str(item.get("variable") or "") for item in requested if isinstance(item, dict)],
            risk_warnings=[] if enabled else ["生成模型尚未同时满足编译、Admin 审批和启用门禁。"],
            execution_allowed=enabled,
            execution_block_reason=reason,
            status="awaiting_confirmation" if enabled else ("needs_input" if missing else "pending_generated_model_approval"),
        )

    def refresh_generated_plan(self, plan: SimulationPlan) -> SimulationPlan:
        if plan.model_source != "generated" or not plan.generated_model_id:
            return plan
        try:
            generated = self.generated_model_service.repository.get(plan.generated_model_id)
        except GeneratedModelLifecycleError:
            plan.execution_allowed = False
            plan.execution_block_reason = "GENERATED_MODEL_NOT_FOUND"
            plan.generated_model_status = "missing"
            return plan
        plan.generated_model_revision = int(generated.get("revision") or 0) or None
        plan.generated_model_status = str(generated.get("status") or "draft")
        plan.generated_model_summary = dict(generated.get("model_summary") or {})
        plan.missing_inputs = [_public_generated_missing_input(value) for value in generated.get("missing_parameters") or []]
        plan.execution_allowed = bool(generated.get("execution_eligible") and not plan.missing_inputs)
        plan.execution_block_reason = None if plan.execution_allowed else (
            "GENERATED_MODEL_INPUTS_INCOMPLETE" if plan.missing_inputs else "GENERATED_MODEL_APPROVAL_REQUIRED"
        )
        plan.status = "awaiting_confirmation" if plan.execution_allowed else "pending_generated_model_approval"
        return plan

    def can_revise(self, plan: SimulationPlan, query: str) -> bool:
        if plan.model_id != "plane_wall_steady_v1":
            return False
        # Questions and explicit new tasks must not silently edit a pending plan.
        if re.search(r"[?？]|为什么|是什么|怎么|多少|是否|能否|解释|新.*仿真|另一个|重新仿真", query):
            return False
        if self._is_cfd(query) or any(token in query for token in ("液冷", "回路", "瞬态", "集总")):
            return False
        return bool(self._parse_plane_wall_inputs(query)[0])

    def revise(self, plan: SimulationPlan, query: str) -> SimulationPlan:
        if plan.model_id == "plane_wall_steady_v1" and self.can_revise(plan, query):
            revised = self._plane_wall_plan(query, previous=plan)
        else:
            revised = self.plan(query)
        revised.version = plan.version + 1
        return revised

    @staticmethod
    def _is_cfd(text: str) -> bool:
        return "CFD" in text.upper() or any(token in text for token in ("流场", "网格", "计算流体"))

    @staticmethod
    def _parse_plane_wall_inputs(text: str) -> tuple[dict[str, float], dict[str, str], dict[str, dict[str, Any]]]:
        inputs: dict[str, float] = {}
        sources: dict[str, str] = {}
        normalizations: dict[str, dict[str, Any]] = {}
        thickness = _match_number(text, rf"(?:厚度|壁厚)\s*(?:为|是|=|:|：)?\s*{_NUMBER}\s*(mm|毫米|cm|厘米|m|米)")
        if thickness:
            value, unit = thickness
            inputs["thickness_m"] = value * {"mm": 0.001, "毫米": 0.001, "cm": 0.01, "厘米": 0.01, "m": 1.0, "米": 1.0}[unit]
            sources["thickness_m"] = "user_query"
        conductivity = _match_value(text, rf"(?:导热系数|热导率|k)\s*(?:为|是|=|:|：)?\s*{_NUMBER}")
        if conductivity is not None:
            inputs["thermal_conductivity_w_mk"] = conductivity
            sources["thermal_conductivity_w_mk"] = "user_query"
        area = _match_value(text, rf"(?:面积|传热面积)\s*(?:为|是|=|:|：)?\s*{_NUMBER}")
        if area is not None:
            inputs["area_m2"] = area
            sources["area_m2"] = "user_query"
        delta = re.search(
            rf"(?:(?:两侧|两端)?(?:温差|相差)|temperature\s+difference|Δ\s*T)"
            rf"\s*(?:为|是|就是|is|=|:|：)?\s*{_NUMBER}\s*(K(?![a-z])|℃|°\s*C|摄氏度)",
            text, re.IGNORECASE,
        )
        if delta:
            inputs["delta_temperature_k"] = float(delta.group(1))
            sources["delta_temperature_k"] = "user_query"
            normalizations["delta_temperature_k"] = {
                "value": float(delta.group(1)), "canonical_unit": "K", "raw_unit": delta.group(2),
                "source_text": delta.group(0),
                "normalization": "identity" if delta.group(2).upper() == "K" else "temperature_difference_celsius_to_kelvin_identity",
            }
        # A Celsius temperature *difference* is never an absolute temperature.
        absolute_text = text[:delta.start()] + text[delta.end():] if delta else text
        for field, label in (("hot_temperature_c", "热侧|(?<!冷)热面|热端|高温侧"), ("cold_temperature_c", "冷侧|(?<!热)冷面|冷端|低温侧")):
            value = _match_value(absolute_text, rf"(?:{label})(?:温度)?\s*(?:为|是|=|:|：)?\s*{_NUMBER}\s*(?:℃|°\s*C|摄氏度)")
            if value is not None:
                inputs[field] = value
                sources[field] = "user_query"
        if not {"hot_temperature_c", "cold_temperature_c"}.intersection(inputs):
            temperatures = [float(item) for item in re.findall(r"([-+]?\d+(?:\.\d+)?)\s*(?:℃|°C|摄氏度)", absolute_text, re.IGNORECASE)]
            if len(temperatures) == 2:
                inputs["hot_temperature_c"] = max(temperatures)
                inputs["cold_temperature_c"] = min(temperatures)
                sources["hot_temperature_c"] = sources["cold_temperature_c"] = "user_query"
        return inputs, sources, normalizations

    def _plane_wall_plan(self, text: str, *, previous: SimulationPlan | None = None) -> SimulationPlan:
        model = self.model_registry.get("plane_wall_steady_v1")
        if model is None or not model.supports_execution:
            return self._no_compatible_model_plan(text)
        inputs, sources, normalizations = self._parse_plane_wall_inputs(text)
        if previous is not None:
            retained_inputs = dict(previous.inputs)
            retained_normalizations = dict(previous.input_normalizations)
            # Derived delta is recomputed after editing a temperature. Explicit delta
            # remains an independent constraint and can still conflict with the pair.
            if retained_normalizations.get("delta_temperature_k", {}).get("normalization") == "absolute_hot_cold_difference":
                retained_inputs.pop("delta_temperature_k", None)
                retained_normalizations.pop("delta_temperature_k", None)
            inputs = {**retained_inputs, **inputs}
            sources = {**previous.parameter_sources, **sources}
            normalizations = {**retained_normalizations, **normalizations}
            text = previous.user_goal + "\n补充/修订：" + text
        normalized = self.model_registry.normalize_inputs(model.model_id, inputs)
        inputs = normalized.inputs
        normalizations.update(normalized.normalizations)
        missing = normalized.missing_inputs
        allowed = normalized.valid
        reason = normalized.errors[0]["code"] if normalized.errors else ("SIMULATION_INPUTS_INCOMPLETE" if missing else None)
        return SimulationPlan(
            plan_id=_plan_id(),
            user_goal=text,
            simulation_type="steady_conduction",
            scenario_id="plane_wall_steady_conduction",
            scenario_confidence=0.98,
            model_id=model.model_id,
            selected_model_id=model.model_id,
            selected_model_name=model.display_name,
            selection_reason="exact_scenario_and_keyword_match:plane_wall_steady_conduction",
            candidate_models=[_candidate(model, 0.98)],
            model_selection_confidence=0.98,
            model_version=model.version,
            inputs=inputs,
            parameter_sources=sources,
            input_normalizations=normalizations,
            input_errors=normalized.errors,
            input_conflicts=[error for error in normalized.errors if error["code"] == "SIMULATION_INPUT_CONFLICT"],
            missing_inputs=missing,
            assumptions=["一维稳态导热", "材料均匀且导热系数恒定"],
            boundary_conditions=["给定温差，或由热侧与冷侧温度对推导温差；不构造绝对温度"],
            solver_backend=model.backend,
            solver={"type": "analytical", "serialization": "single_worker"},
            matlab_entrypoint=model.matlab_entrypoint,
            execution_steps=["校验白名单参数", "调用受控 MATLAB dispatcher", "归一化并记录结果证据"],
            expected_outputs=["temperature_difference_k", "heat_rate_w", "heat_flux_w_m2"],
            risk_warnings=[] if allowed else ["参数存在矛盾或无效值，请在对话中修正。" if normalized.errors else "参数尚不完整，请在对话中补充。"],
            execution_allowed=allowed,
            execution_block_reason=reason,
            status="awaiting_confirmation" if allowed else "needs_input",
        )

    def _liquid_loop_plan(self, text: str) -> SimulationPlan:
        model = self.model_registry.get("liquid_loop_energy_balance_python_v1")
        if model is None:
            return self._no_compatible_model_plan(text)
        inputs: dict[str, float] = {}
        heat = _match_value(text, rf"{_NUMBER}\s*(?:W|瓦)(?:\s*(?:GPU|热负荷))?")
        if heat is not None:
            inputs["heat_load_w"] = heat
        required = ["heat_load_w", "specific_heat_j_kgk", "inlet_temperature_c"]
        missing = [name for name in required if name not in inputs]
        if not any(name in inputs for name in ("mass_flow_kg_s", "outlet_temperature_c", "allowed_temperature_rise_k")):
            missing.append("mass_flow_kg_s_or_allowed_temperature_rise_k")
        return SimulationPlan(
            plan_id=_plan_id(),
            user_goal=text,
            simulation_type="liquid_loop_energy_balance",
            scenario_id="liquid_loop_energy_balance",
            scenario_confidence=0.94,
            model_id=model.model_id,
            selected_model_id=model.model_id,
            selected_model_name=model.display_name,
            selection_reason="scenario_match:liquid_loop_energy_balance",
            candidate_models=[_candidate(model, 0.94)],
            model_selection_confidence=0.94,
            model_version=model.version,
            inputs=inputs,
            missing_inputs=missing,
            assumptions=["稳态能量平衡", "比热容恒定且无环境热损失"],
            cooling_loop={"heat_load_w": inputs.get("heat_load_w")},
            solver_backend=model.backend,
            expected_outputs=["mass_flow_kg_s", "temperature_rise_k", "outlet_temperature_c"],
            risk_warnings=["不计算压力损失、相变、泵功或流量分配。"],
            execution_allowed=not missing,
            execution_block_reason="SIMULATION_INPUTS_INCOMPLETE" if missing else None,
            status="needs_input" if missing else "awaiting_confirmation",
        )

    def _cfd_plan(self, text: str) -> SimulationPlan:
        model = self.model_registry.get("cfd_registered_model_preparation_v1")
        if model is None:
            return self._no_compatible_model_plan(text)
        file_match = re.search(
            r"(?:模型文件|model file)(?:路径)?\s*(?:为|是|=|:|：)?\s*[\"']?([^\s\"']+\.(?:m|slx|mat|cas|msh))[\"']?",
            text,
            re.IGNORECASE,
        )
        model_file_path = file_match.group(1) if file_match else None
        missing = ["materials", "boundary_conditions"]
        if model_file_path is None:
            missing = ["model_file", "model_file_id", *missing]
        return SimulationPlan(
            plan_id=_plan_id(),
            user_goal=text,
            simulation_type="cfd_preparation",
            scenario_id="cfd_model_preparation",
            scenario_confidence=0.97,
            model_id=model.model_id,
            selected_model_id=model.model_id,
            selected_model_name=model.display_name,
            selection_reason="scenario_match:cfd_preparation_only",
            candidate_models=[_candidate(model, 0.97)],
            model_selection_confidence=0.97,
            model_version=model.version,
            model_file_required=True,
            model_file_path=model_file_path,
            missing_inputs=missing,
            solver_backend="openfoam",
            risk_warnings=["本阶段仅准备 CFD 任务，不执行 CFD。"],
            execution_allowed=False,
            execution_block_reason="CFD_EXECUTION_PROHIBITED",
            status="preparation_only",
        )

    def _transient_plan(self, text: str) -> SimulationPlan:
        model = self.model_registry.get("lumped_transient_preparation_v1")
        if model is None:
            return self._no_compatible_model_plan(text)
        required = [
            "initial_temperature_c",
            "ambient_temperature_c",
            "density_kg_m3",
            "volume_m3",
            "specific_heat_j_kgk",
            "convection_coefficient_w_m2k",
            "surface_area_m2",
            "duration_s",
            "time_step_s",
        ]
        return SimulationPlan(
            plan_id=_plan_id(),
            user_goal=text,
            simulation_type="lumped_transient_heating",
            scenario_id="lumped_transient_heating",
            scenario_confidence=0.96,
            model_id=model.model_id,
            selected_model_id=model.model_id,
            selected_model_name=model.display_name,
            selection_reason="scenario_match:experimental_transient_preparation",
            candidate_models=[_candidate(model, 0.96)],
            model_selection_confidence=0.96,
            model_version=model.version,
            missing_inputs=required,
            solver_backend="matlab",
            risk_warnings=["该模型仍为 experimental，尚未通过人工评审。"],
            execution_allowed=False,
            execution_block_reason="MODEL_EXPERIMENTAL_NOT_REVIEWED",
            status="preparation_only",
        )

    def _ambiguous_conduction_plan(self, text: str) -> SimulationPlan:
        scenario_ids = {
            "plane_wall_steady_conduction",
            "cylindrical_wall_steady_conduction",
            "multilayer_wall_conduction",
        }
        models = [
            model
            for model in self.model_registry.list(status="available")
            if model.scenario_id in scenario_ids and model.supports_execution
        ]
        if len(models) < 2:
            return self._no_compatible_model_plan(text)
        return SimulationPlan(
            plan_id=_plan_id(),
            user_goal=text,
            simulation_type="model_selection_required",
            selected_model_id=None,
            selected_model_name=None,
            selection_reason="multiple_compatible_models",
            candidate_models=[_candidate(model, 0.72) for model in models],
            model_selection_confidence=0.72,
            execution_allowed=False,
            execution_block_reason="MODEL_SELECTION_REQUIRED",
            risk_warnings=["存在多个接近的导热模型，需要先确认几何类型。"],
            status="needs_model_selection",
        )


def _plan_id() -> str:
    return f"sim-{uuid4().hex}"


def _public_generated_missing_input(value: Any) -> str:
    internal = str(value or "").strip()
    labels = {
        "branch_resistances_k_w": "parallel branch thermal resistances",
        "upstream_resistances_k_w": "upstream series thermal resistances",
        "downstream_resistances_k_w": "downstream series thermal resistances",
        "hot_temperature_k": "hot-side temperature boundary",
        "cold_temperature_k": "cold-side temperature boundary",
        "invalid_structured_requirement": "valid thermal model parameters",
    }
    return labels.get(internal, internal.replace("_", " "))


def _match_value(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _match_number(text: str, pattern: str) -> tuple[float, str] | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return (float(match.group(1)), match.group(2)) if match else None


def _candidate(model: ModelDefinition, confidence: float) -> dict[str, Any]:
    return {
        "model_id": model.model_id,
        "display_name": model.display_name,
        "backend": model.backend,
        "scenario_types": list(model.scenario_types),
        "status": model.status,
        "confidence": confidence,
    }


__all__ = ["NaturalLanguageSimulationPlanner"]

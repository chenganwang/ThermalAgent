from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
import json

from services.ingest_service.external_ingestion import connect_mysql
from services.retrieval_service.config import AppConfig


REVIEWER_TYPE = "codex_source_grounded_review"


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def candidate_hash(candidate: dict[str, Any]) -> str:
    identity = {
        "unit_type": candidate.get("unit_type"),
        "canonical_name": candidate.get("canonical_name"),
        "title": candidate.get("title"),
        "content": candidate.get("content"),
        "source": candidate.get("source"),
        "dedup_key": candidate.get("dedup_key"),
    }
    return sha256(_stable_json(identity).encode("utf-8")).hexdigest()


def load_review_candidates(result_path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
    candidates = payload.get("knowledge_gate", {}).get("needs_human_review", [])
    if not isinstance(candidates, list):
        raise ValueError("knowledge_gate.needs_human_review must be a list")

    output: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("review candidate must be an object")
        item = dict(candidate)
        digest = candidate_hash(item)
        item["candidate_hash"] = digest
        item["candidate_id"] = f"external_ku_{digest[:16]}"
        output.append(item)
    return output


def _fetchall(cursor: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    cursor.execute(sql, params)
    return [dict(row) for row in (cursor.fetchall() or [])]


def load_source_contexts(
    cfg: AppConfig,
    candidates: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        for candidate in candidates:
            source = dict(candidate.get("source") or {})
            document_id = int(source.get("document_id"))
            chunk_id = int(source.get("chunk_id"))

            documents = _fetchall(
                cursor,
                "SELECT id, source, title, sha256, local_path, meta_json FROM documents WHERE id=%s LIMIT 1",
                (document_id,),
            )
            chunks = _fetchall(
                cursor,
                "SELECT id, doc_id, chunk_index, page_start, page_end, section_path, text, content_hash, meta_json "
                "FROM chunks WHERE id=%s AND doc_id=%s LIMIT 1",
                (chunk_id, document_id),
            )
            if not documents or not chunks:
                raise ValueError(
                    f"source provenance not found for candidate_id={candidate.get('candidate_id')} "
                    f"document_id={document_id} chunk_id={chunk_id}"
                )

            chunk = chunks[0]
            chunk_index = int(chunk.get("chunk_index"))
            previous_chunks = _fetchall(
                cursor,
                "SELECT id, doc_id, chunk_index, page_start, page_end, section_path, text, content_hash "
                "FROM chunks WHERE doc_id=%s AND chunk_index=%s ORDER BY id",
                (document_id, chunk_index - 1),
            )
            next_chunks = _fetchall(
                cursor,
                "SELECT id, doc_id, chunk_index, page_start, page_end, section_path, text, content_hash "
                "FROM chunks WHERE doc_id=%s AND chunk_index=%s ORDER BY id",
                (document_id, chunk_index + 1),
            )
            assets = _fetchall(
                cursor,
                "SELECT id, doc_id, chunk_id, asset_type, title, file_path, page_number, asset_meta "
                "FROM source_assets WHERE doc_id=%s ORDER BY id",
                (document_id,),
            )
            page_matches = source.get("page_no") in (None, chunk.get("page_start"), chunk.get("page_end"))
            contexts[str(candidate.get("candidate_id"))] = {
                "document": documents[0],
                "source_assets": assets,
                "chunk": chunk,
                "previous_chunks": previous_chunks,
                "next_chunks": next_chunks,
                "source_context_checked": True,
                "adjacent_context_checked": True,
                "provenance_verified": bool(
                    chunk.get("doc_id") == document_id
                    and chunk.get("id") == chunk_id
                    and page_matches
                ),
            }
        return contexts
    finally:
        connection.close()


def _decode_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def load_existing_knowledge_units(cfg: AppConfig) -> list[dict[str, Any]]:
    connection = connect_mysql(cfg, autocommit=True)
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, unit_code, unit_type, title, summary, content, source_doc_id, source_chunk_id, "
            "page_start, page_end, review_status, meta_json FROM knowledge_units ORDER BY id"
        )
        output = []
        for row in cursor.fetchall() or []:
            item = dict(row)
            item["meta"] = _decode_json_object(item.get("meta_json"))
            output.append(item)
        return output
    finally:
        connection.close()


def _normalize_text(value: Any) -> str:
    text = " ".join(str(value or "").lower().split())
    return "".join(ch for ch in text if ch.isalnum())


def _unit(
    unit_type: str,
    canonical_name: str,
    title: str,
    content: str,
    *,
    conditions: list[str],
    limitations: list[str],
    required_phrases: list[str],
    variables: list[dict[str, str]] | None = None,
    units: dict[str, str] | None = None,
    properties: dict[str, Any] | None = None,
    evidence_chunk_id: int | None = None,
    aliases: list[str] | None = None,
    keywords: list[str] | None = None,
    confidence: float = 0.9,
) -> dict[str, Any]:
    merged_properties = dict(properties or {})
    merged_properties.update(
        {
            "variables": list(variables or []),
            "units": dict(units or {}),
            "conditions": list(conditions),
            "limitations": list(limitations),
        }
    )
    return {
        "unit_type": unit_type,
        "canonical_name": canonical_name,
        "title": title,
        "content": content,
        "properties": merged_properties,
        "required_phrases": list(required_phrases),
        "evidence_chunk_id": evidence_chunk_id,
        "aliases": list(aliases or []),
        "keywords": list(keywords or []),
        "confidence": float(confidence),
    }


def _repair_recipes() -> dict[tuple[int, str, str], list[dict[str, Any]]]:
    study = ["Specific to the Frontier digital-twin study and its stated operating data; not an industry-wide rule."]
    return {
        (482, "component", "cdu"): [
            _unit(
                "component", "frontier_htw_parallel_subloop", "Frontier HTW parallel subloop",
                "The Frontier HTW system uses four parallel subloops: three active and one reserve. Each active subloop has a CDU cluster, an HTW pump, and a heat exchanger.",
                conditions=["Frontier supercomputer warm-water cooling architecture described in the source study."],
                limitations=study,
                required_phrases=["four parallel subloops", "three are active", "one is held in reserve"],
                evidence_chunk_id=481,
                properties={"system_specific": True, "facility": "Frontier supercomputer"},
                keywords=["Frontier", "HTW", "parallel subloop", "CDU"],
            )
        ],
        (479, "component", "chip"): [
            _unit(
                "thermal_path", "frontier_cascaded_cooling_loops", "Frontier cascaded cooling-loop thermal path",
                "In the described Frontier architecture, processor and accelerator heat enters a 50/50 ethylene-glycol/water CDU loop, transfers through plate heat exchangers to the pure-water HTW loop, and is rejected onward through the cooling-tower-water loop.",
                conditions=["Frontier supercomputer architecture; the source states that the basis of the reported 50% glycol solution is unspecified."],
                limitations=study + ["Do not reuse the stated coolant concentration as a general EGW property or composition rule."],
                required_phrases=["three thermally coupled fluid loops", "plate heat exchangers", "pure water"],
                properties={
                    "system_specific": True,
                    "facility": "Frontier supercomputer",
                    "nodes": ["CDU glycol-water loop", "HTW pure-water loop", "CTW cooling-tower loop", "atmosphere"],
                },
                keywords=["Frontier", "thermal path", "CDU loop", "HTW loop", "CTW loop"],
            )
        ],
        (479, "parameter", "flow_rate"): [
            _unit(
                "parameter", "frontier_htw_operating_flow_range", "Frontier HTW operating flow range",
                "The paper reports that the Frontier hot-temperature-water loop circulates pure water at 113 to 412 kg/s, depending on operating conditions.",
                conditions=["Frontier HTW loop under the operating conditions represented by the cited study."],
                limitations=study + ["This is a facility-level mass-flow range, not a cold-plate branch design value."],
                required_phrases=["113 and 412kg/s", "depending on operating conditions"],
                units={"mass_flow_rate": "kg/s"},
                properties={"minimum": 113, "maximum": 412, "system_specific": True},
                keywords=["Frontier", "HTW", "mass flow rate"],
            )
        ],
        (481, "concept", "heat_exchanger"): [
            _unit(
                "component", "frontier_active_htw_subloop_components", "Frontier active HTW subloop components",
                "Each active Frontier HTW subloop contains its own CDU cluster, HTW pump, and heat exchanger, and its thermal return-temperature constraint is evaluated independently of the other active branches.",
                conditions=["Frontier HTW parallel topology in the cited operational dataset and Modelica study."],
                limitations=study,
                required_phrases=["Each active subloop contains", "thermal constraint must be satisfied independently"],
                properties={"system_specific": True, "topology": "parallel"},
                keywords=["HTW subloop", "heat exchanger", "pump", "parallel"],
            )
        ],
        (483, "concept", "pump"): [
            _unit(
                "component", "frontier_variable_speed_htw_pump", "Frontier variable-speed HTW pump role",
                "In the source's Frontier schematic, a variable-speed pump drives HTW supply flow from the cooling-tower basin through the parallel subloops; warm return flow is then rejected through mechanical-draft cooling towers.",
                conditions=["Frontier HTW system schematic and digital-twin boundary described by the study."],
                limitations=study + ["The source passage does not provide a vendor pump curve or pump model."],
                required_phrases=["variable-speed pump drives", "mechanical-draft cooling tower"],
                properties={"system_specific": True, "pump_curve_available": False},
                keywords=["variable-speed pump", "HTW", "Frontier"],
            )
        ],
        (487, "concept", "cdu"): [
            _unit(
                "formula", "frontier_constant_effectiveness_heat_exchanger", "Constant-effectiveness heat-exchanger model used for Frontier",
                "Q_HX = epsilon * C_min * (T_hot,in - T_cold,in), where C_min is the smaller of the hot- and cold-side heat-capacity rates.",
                conditions=["HTW-to-CTW plate heat exchangers in the cited Frontier Modelica model; prescribed constant effectiveness."],
                limitations=study + ["This idealized equation does not establish a measured exchanger performance curve."],
                required_phrases=["QHX =", "Cmin = min", "constant-effectiveness formulation"],
                evidence_chunk_id=488,
                variables=[
                    {"name": "Q_HX", "definition": "heat-transfer rate"},
                    {"name": "epsilon", "definition": "heat-exchanger effectiveness"},
                    {"name": "C_min", "definition": "minimum hot/cold heat-capacity rate"},
                    {"name": "T_hot,in", "definition": "hot-side inlet temperature"},
                    {"name": "T_cold,in", "definition": "cold-side inlet temperature"},
                ],
                units={"Q_HX": "power", "C_min": "power/temperature", "temperature": "temperature"},
                properties={"model_specific": True, "formula": "Q_HX = epsilon * C_min * (T_hot,in - T_cold,in)"},
                keywords=["effectiveness-NTU", "heat exchanger", "Frontier"],
            )
        ],
        (489, "parameter", "supply_temperature"): [
            _unit(
                "formula", "frontier_htw_ua_flow_scaling", "Frontier HTW UA flow scaling",
                "UA(m_dot) = UA_nom * (m_dot / m_dot_nom)^0.8, with UA_nom = 2252 kW/K at m_dot_nom = 190 kg/s in the study model.",
                conditions=["The source assumes HTW-side convective resistance dominates wall-conduction and CTW-side resistance."],
                limitations=study + ["The nominal UA and reference flow are model parameters for this facility, not universal exchanger values."],
                required_phrases=["UA(", "2,252kW/K", "190kg/s"],
                variables=[
                    {"name": "UA", "definition": "overall heat-transfer coefficient-area product"},
                    {"name": "m_dot", "definition": "HTW mass flow rate"},
                    {"name": "UA_nom", "definition": "nominal UA"},
                    {"name": "m_dot_nom", "definition": "reference mass flow rate"},
                ],
                units={"UA_nom": "kW/K", "m_dot_nom": "kg/s"},
                properties={"model_specific": True, "formula": "UA = UA_nom * (m_dot / m_dot_nom)^0.8"},
                keywords=["UA", "mass flow", "Frontier"],
            ),
            _unit(
                "formula", "frontier_htw_pump_power_scaling", "Frontier HTW pump-power scaling",
                "P_pump(m_dot) = P_pump,nom * (m_dot / m_dot_nom)^n. The study uses n = 3 as its baseline and tests n in {2.0, 2.5, 3.0}.",
                conditions=["Variable-speed centrifugal-pump model for the closed Frontier HTW loop with negligible static head."],
                limitations=study + ["No manufacturer pump curve is used; exponent sensitivity does not constitute pump selection data."],
                required_phrases=["Ppump(", "baseline pump power exponent is n = 3", "n ∈{2.0, 2.5, 3.0}"],
                variables=[
                    {"name": "P_pump", "definition": "pump power at mass flow m_dot"},
                    {"name": "P_pump,nom", "definition": "nominal pump power"},
                    {"name": "m_dot", "definition": "mass flow rate"},
                    {"name": "n", "definition": "pump-power exponent"},
                ],
                units={"P_pump": "power", "m_dot": "mass flow rate", "n": "dimensionless"},
                properties={"model_specific": True, "formula": "P_pump = P_pump_nom * (m_dot / m_dot_nom)^n", "pump_curve_used": False},
                keywords=["pump affinity", "pump power", "Frontier"],
            ),
        ],
        (492, "parameter", "return_temperature"): [
            _unit(
                "formula", "frontier_cooling_tower_heat_rejection_balance", "Frontier cooling-tower heat-rejection balance",
                "Q_rej = sum(i=1..3, Q_i) + P_pump in the study's three-active-subloop cooling model.",
                conditions=["Frontier cooling-tower model with three active HTW subloops."],
                limitations=study + ["The equation is a model energy balance and not a measured tower-performance result."],
                required_phrases=["Qrej =", "Ppump", "total IT heat load plus the pump work"],
                variables=[
                    {"name": "Q_rej", "definition": "cooling-tower heat-rejection rate"},
                    {"name": "Q_i", "definition": "IT heat load of active subloop i"},
                    {"name": "P_pump", "definition": "pump work added to the fluid"},
                ],
                units={"Q_rej": "power", "Q_i": "power", "P_pump": "power"},
                properties={"model_specific": True, "formula": "Q_rej = sum(Q_i, i=1..3) + P_pump"},
                keywords=["cooling tower", "heat rejection", "energy balance"],
            ),
            _unit(
                "formula", "frontier_total_cooling_power_balance", "Frontier total cooling-system power balance",
                "P_total = P_pump + P_CT, where P_CT is cooling-tower fan power in the study model.",
                conditions=["Frontier pump and mechanical-draft cooling-tower model."],
                limitations=study + ["The relation does not include unmodeled auxiliary loads."],
                required_phrases=["Ptotal = Ppump + PCT", "sum of pump and cooling tower fan power"],
                variables=[
                    {"name": "P_total", "definition": "modeled total cooling-system power"},
                    {"name": "P_pump", "definition": "HTW pump power"},
                    {"name": "P_CT", "definition": "cooling-tower fan power"},
                ],
                units={"P_total": "power", "P_pump": "power", "P_CT": "power"},
                properties={"model_specific": True, "formula": "P_total = P_pump + P_CT"},
                keywords=["cooling power", "pump", "cooling tower"],
            ),
        ],
        (495, "parameter", "return_temperature"): [
            _unit(
                "parameter", "frontier_dataset_internal_specific_heat", "Frontier dataset internal specific-heat constant",
                "The paper reports that the dataset's derived waste-heat columns use a fixed specific-heat constant of 3709 J/(kg*K) across 49,869 records, making validation against that same constant circular.",
                conditions=["Internal derived-quantity convention in the Frontier operational dataset analyzed by the paper."],
                limitations=study + ["This is not an independently measured EGW property and must not be used as a general coolant-property value."],
                required_phrases=["cp = 3,709 J/(kg*K)", "49,869 records", "circular validation"],
                units={"specific_heat": "J/(kg*K)"},
                properties={"value": 3709, "dataset_specific": True, "not_property_reference": True},
                keywords=["specific heat", "derived dataset", "circular validation"],
            ),
            _unit(
                "parameter", "frontier_digital_twin_adopted_specific_heat", "Specific heat adopted by the Frontier digital twin",
                "For validation, the paper's digital twin adopts cp = 3500 J/(kg*K) for its modeled glycol-water coolant over 25-35 degrees C, rather than the dataset's internal 3709 J/(kg*K) constant.",
                conditions=["Adopted validation constant in the cited Frontier digital-twin model; source reports a nominal 50/50 EGW description with composition-basis ambiguity."],
                limitations=study + ["This model choice is not a project-wide EGW property table and must not replace concentration- and temperature-specific lookup data."],
                required_phrases=["digital twin adopts cp = 3,500 J/(kg*K)", "25-35", "50/50 ethylene glycol-water"],
                units={"specific_heat": "J/(kg*K)", "temperature_range": "degree C"},
                properties={"value": 3500, "temperature_min_c": 25, "temperature_max_c": 35, "model_specific": True, "not_property_reference": True},
                keywords=["EGW", "specific heat", "digital twin", "Frontier"],
            ),
        ],
        (524, "parameter", "supply_temperature"): [
            _unit(
                "parameter", "frontier_strategy_c_supply_temperature_range", "Frontier Strategy C supply-temperature range",
                "During the representative 168-hour July week in the paper, Strategy C maintains a 28-32 degree C supply-temperature setpoint, compared with a 24-28 degree C baseline.",
                conditions=["Representative summer-week simulation for Strategy C in the cited Frontier digital-twin study."],
                limitations=study + ["The range is simulation- and scenario-specific and is not a universal data-center supply-temperature recommendation."],
                required_phrases=["168 hours in July", "28-32", "baseline 24-28"],
                units={"supply_temperature": "degree C"},
                properties={"minimum": 28, "maximum": 32, "baseline_minimum": 24, "baseline_maximum": 28, "simulation_specific": True},
                keywords=["Strategy C", "supply temperature", "Frontier"],
            )
        ],
        (537, "parameter", "return_temperature"): [
            _unit(
                "parameter", "frontier_return_temperature_cv_rmse", "Frontier digital-twin return-temperature CV-RMSE",
                "The paper reports per-subloop return-temperature prediction CV-RMSE of 1.96% to 2.67% for its calibrated physics-based digital twin.",
                conditions=["Validation results for the cited Frontier digital-twin study and its dataset."],
                limitations=study + ["This study-specific error range is not evidence of equivalent accuracy on another facility."],
                required_phrases=["1.96-2.67% CV-RMSE", "per-subloop return temperatures"],
                units={"cv_rmse": "%"},
                properties={"minimum": 1.96, "maximum": 2.67, "study_specific": True},
                keywords=["CV-RMSE", "return temperature", "digital twin"],
            )
        ],
        (658, "component", "cpu"): [
            _unit(
                "concept", "intel_xeon_multidie_tcase_compliance", "Intel Xeon Scalable multidie TCASE compliance",
                "For the Intel Xeon Scalable platform described by the December 2019 guide, CPU-die and Fabric-die TCASE maxima depend on the workload emphasizing each die; thermal compliance requires each measured TCASE to remain below the corresponding TCASE_MAX at that case-temperature location.",
                conditions=["Intel Xeon Processor Scalable Family platform covered by the December 2019 thermal-mechanical guide."],
                limitations=["Vendor- and platform-specific guidance; do not generalize it to all processors or generations."],
                required_phrases=["TCASE at each location", "based on a particular power workload", "less than TCASE_MAX"],
                properties={"vendor": "Intel", "platform_specific": True, "applicable_platform": "Intel Xeon Processor Scalable Family", "guide_date": "December 2019"},
                keywords=["Intel", "Xeon Scalable", "TCASE", "TCASE_MAX"],
            )
        ],
        (708, "parameter", "pressure_drop"): [
            _unit(
                "formula", "intel_xeon_case_to_ambient_psi_ca", "Intel Xeon case-to-local-ambient thermal characterization parameter",
                "Psi_CA = (T_CASE - T_LA) / TDP, where T_CASE is processor case temperature, T_LA is local ambient temperature before the heatsink, and the guide assumes TDP power dissipates through the integrated heat spreader.",
                conditions=["Thermal-solution characterization in the Intel Xeon Processor Scalable Family December 2019 guide."],
                limitations=["Vendor- and platform-specific design parameter; the all-power-through-IHS assumption is explicitly described as inexact."],
                required_phrases=["case-to-local ambient", "TDP", "assumes all power dissipates through the integrated heat spreader"],
                variables=[
                    {"name": "Psi_CA", "definition": "case-to-local-ambient thermal characterization parameter"},
                    {"name": "T_CASE", "definition": "processor case temperature"},
                    {"name": "T_LA", "definition": "local ambient temperature before the heatsink"},
                    {"name": "TDP", "definition": "thermal design power used by the guide"},
                ],
                units={"Psi_CA": "degree C/W", "T_CASE": "degree C", "T_LA": "degree C", "TDP": "W"},
                properties={"vendor": "Intel", "platform_specific": True, "applicable_platform": "Intel Xeon Processor Scalable Family", "formula": "Psi_CA = (T_CASE - T_LA) / TDP"},
                keywords=["Intel", "Xeon", "Psi_CA", "thermal characterization"],
            )
        ],
        (709, "parameter", "pressure_drop"): [
            _unit(
                "formula", "intel_xeon_psi_ca_decomposition", "Intel Xeon Psi_CA decomposition",
                "Psi_CA = Psi_CS + Psi_SA, decomposing the case-to-local-ambient characterization parameter into TIM and heatsink-to-local-ambient contributions.",
                conditions=["Thermal-solution characterization in the Intel Xeon Processor Scalable Family December 2019 guide."],
                limitations=["Vendor- and platform-specific characterization; Psi_CS and Psi_SA depend on TIM properties, heatsink geometry, material, and airflow."],
                required_phrases=["Ψ CA = Ψ CS + Ψ SA", "Thermal characterization parameter of the TIM", "air velocity through the heatsink fins"],
                variables=[
                    {"name": "Psi_CA", "definition": "case-to-local-ambient thermal characterization parameter"},
                    {"name": "Psi_CS", "definition": "TIM thermal characterization parameter"},
                    {"name": "Psi_SA", "definition": "heatsink-to-local-ambient thermal characterization parameter"},
                ],
                units={"Psi_CA": "degree C/W", "Psi_CS": "degree C/W", "Psi_SA": "degree C/W"},
                properties={"vendor": "Intel", "platform_specific": True, "applicable_platform": "Intel Xeon Processor Scalable Family", "formula": "Psi_CA = Psi_CS + Psi_SA"},
                keywords=["Intel", "Xeon", "Psi_CA", "TIM", "heatsink"],
            )
        ],
        (986, "parameter", "specific_heat"): [
            _unit(
                "parameter", "coursework_cold_plate_aluminum_specific_heat", "Coursework cold-plate aluminum specific heat",
                "The coursework simulation assigns a constant-pressure specific heat of 871 J/(kg*K) to the aluminum alloy used for all three modeled cold plates.",
                conditions=["Three cold-plate geometries in the cited academic coursework simulation."],
                limitations=["Academic-coursework and simulation-specific material input; the aluminum alloy grade is not identified, so this value must not be generalized."],
                required_phrases=["定压比热容 871 J/(kg", "三种冷板均采用铝合金材质"],
                units={"specific_heat": "J/(kg*K)"},
                properties={"value": 871, "academic_coursework": True, "simulation_specific": True, "geometry_specific": True},
                keywords=["cold plate", "aluminum", "specific heat"],
            )
        ],
        (986, "parameter", "density"): [
            _unit(
                "parameter", "coursework_cold_plate_aluminum_density", "Coursework cold-plate aluminum density",
                "The coursework simulation assigns a density of 2719 kg/m3 to the aluminum alloy used for all three modeled cold plates.",
                conditions=["Three cold-plate geometries in the cited academic coursework simulation."],
                limitations=["Academic-coursework and simulation-specific material input; the aluminum alloy grade is not identified, so this value must not be generalized."],
                required_phrases=["密度 2719kg/m3", "三种冷板均采用铝合金材质"],
                units={"density": "kg/m3"},
                properties={"value": 2719, "academic_coursework": True, "simulation_specific": True, "geometry_specific": True},
                keywords=["cold plate", "aluminum", "density"],
            )
        ],
        (986, "parameter", "viscosity"): [
            _unit(
                "parameter", "coursework_air_dynamic_viscosity", "Coursework air dynamic viscosity",
                "The coursework simulation uses air dynamic viscosity 1.72e-5 Pa*s at 20 degrees C and 101325 Pa.",
                conditions=["Air properties used by the cited academic coursework simulation at 20 degrees C and 101325 Pa."],
                limitations=["Academic-coursework and simulation-specific input; this is an air property, not a liquid-coolant property."],
                required_phrases=["20℃、101325Pa", "动力粘度 1.72×10⁻⁵ Pa"],
                units={"dynamic_viscosity": "Pa*s", "temperature": "degree C", "pressure": "Pa"},
                properties={"value": 0.0000172, "temperature_c": 20, "pressure_pa": 101325, "fluid": "air", "academic_coursework": True, "simulation_specific": True},
                keywords=["air", "dynamic viscosity", "coursework"],
            )
        ],
        (986, "parameter", "thermal_conductivity"): [
            _unit(
                "parameter", "coursework_cold_plate_aluminum_thermal_conductivity", "Coursework cold-plate aluminum thermal conductivity",
                "The coursework simulation assigns thermal conductivity 202 W/(m*K) to the aluminum alloy used for all three modeled cold plates.",
                conditions=["Three cold-plate geometries in the cited academic coursework simulation."],
                limitations=["Academic-coursework and simulation-specific material input; the aluminum alloy grade is not identified, so this value must not be generalized."],
                required_phrases=["导热系数 202W/(m", "三种冷板均采用铝合金材质"],
                units={"thermal_conductivity": "W/(m*K)"},
                properties={"value": 202, "academic_coursework": True, "simulation_specific": True, "geometry_specific": True},
                keywords=["cold plate", "aluminum", "thermal conductivity"],
            )
        ],
        (991, "parameter", "pressure_drop"): [
            _unit(
                "concept", "coursework_cold_plate_pressure_loss_definition", "Coursework cold-plate pressure-loss definition",
                "The coursework defines cold-plate pressure loss Delta P as the inlet-to-outlet pressure difference in pascals and uses it as an indicator of flow resistance and modeled flow-energy demand.",
                conditions=["Performance metric used in the cited academic coursework simulation."],
                limitations=["Academic-coursework and simulation-specific interpretation; it is not an experimental pressure-drop result."],
                required_phrases=["冷板入口与出口的压力差值", "流动阻力", "Pa"],
                units={"pressure_loss": "Pa"},
                properties={"academic_coursework": True, "simulation_specific": True, "experiment_specific": False},
                keywords=["cold plate", "pressure loss", "simulation"],
            )
        ],
    }


REJECT_KEYS = {
    (461, "concept", "tim"), (471, "component", "tim"), (474, "thermal_path", "tim_pump"),
    (701, "fault_case", "pressure_drop"), (510, "thermal_path", "respectively_a_high_recovery_ratio_recovery_tim"),
    (511, "parameter", "thermal_conductivity"), (534, "thermal_path", "tim_cdu"),
    (643, "thermal_path", "chip_when_turbo_mode_is_disabled"),
    (690, "thermal_path", "chip_find_a_solution_that_will_meet_thermal_requirements_develop_a_reliable_and_cost_effective_thermal_solution"),
    (691, "thermal_path", "iterate_through_the_previous_steps_find_a_solution_that_will_meet_thermal_requirements_develop_a_reliable_and_cost_effective_thermal_solution"),
    (755, "thermal_path", "chip_prevent_any_damage"), (984, "component", "cold_plate"),
    (986, "concept", "cold_plate"),
}

STILL_HUMAN_KEYS = {
    (496, "parameter", "egw_density"), (525, "parameter", "supply_temperature"),
    (558, "parameter", "supply_temperature"), (558, "parameter", "flow_rate"),
    (802, "fault_case", "corrosion"), (987, "parameter", "density"),
}


def _candidate_key(candidate: dict[str, Any]) -> tuple[int, str, str]:
    source = dict(candidate.get("source") or {})
    return (int(source.get("chunk_id")), str(candidate.get("unit_type") or ""), str(candidate.get("canonical_name") or ""))


def _all_context_text(context: dict[str, Any]) -> str:
    chunks = list(context.get("previous_chunks") or []) + [dict(context.get("chunk") or {})] + list(context.get("next_chunks") or [])
    return "\n".join(str(chunk.get("text") or "") for chunk in chunks)


def _find_evidence_chunk(context: dict[str, Any], evidence_chunk_id: int | None) -> dict[str, Any]:
    chunks = list(context.get("previous_chunks") or []) + [dict(context.get("chunk") or {})] + list(context.get("next_chunks") or [])
    if evidence_chunk_id is None:
        return dict(context.get("chunk") or {})
    for chunk in chunks:
        if int(chunk.get("id") or 0) == int(evidence_chunk_id):
            return dict(chunk)
    raise ValueError(f"evidence chunk {evidence_chunk_id} is not in the checked adjacent context")


def _duplicate_match(unit: dict[str, Any], existing_units: list[dict[str, Any]], batch_units: list[dict[str, Any]]) -> dict[str, Any] | None:
    canonical = _normalize_text(unit.get("canonical_name"))
    content = _normalize_text(unit.get("content"))
    for existing in existing_units:
        meta = dict(existing.get("meta") or {})
        meta_properties = dict(meta.get("properties") or {})
        if (
            str(meta.get("dedup_key") or "") == str(unit.get("dedup_key") or "")
            and str(meta_properties.get("candidate_hash") or "") == str(unit.get("candidate_hash") or "")
        ):
            # The same reviewed pack is already present. Reconstruct the accepted
            # pack deterministically; the writer dry-run will classify it as an
            # existing skip instead of changing the review decision.
            continue
        existing_canonical = _normalize_text(meta.get("canonical_name") or existing.get("title"))
        existing_content = _normalize_text(existing.get("content"))
        if canonical and canonical == existing_canonical or content and content == existing_content:
            return {
                "is_duplicate": True,
                "duplicate_of_unit_id": existing.get("id"),
                "duplicate_type": "existing_semantic_exact",
                "similarity_reason": "normalized canonical name or content matches an existing knowledge unit",
            }
    for accepted in batch_units:
        if canonical == _normalize_text(accepted.get("canonical_name")) or content == _normalize_text(accepted.get("content")):
            return {
                "is_duplicate": True,
                "duplicate_of_candidate_id": accepted.get("candidate_id"),
                "duplicate_type": "batch_semantic_exact",
                "similarity_reason": "normalized canonical name or content matches an earlier reviewed unit",
            }
    return None


def _materialize_unit(
    candidate: dict[str, Any],
    context: dict[str, Any],
    recipe: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    context_text = _all_context_text(context)
    missing_phrases = [phrase for phrase in recipe.get("required_phrases", []) if phrase not in context_text]
    if missing_phrases:
        raise ValueError(f"required source phrases not found: {missing_phrases}")
    evidence = _find_evidence_chunk(context, recipe.get("evidence_chunk_id"))
    source = dict(candidate.get("source") or {})
    canonical_name = str(recipe["canonical_name"])
    unit_type = str(recipe["unit_type"])
    digest = sha256(
        f"{candidate['candidate_hash']}:{index}:{unit_type}:{canonical_name}".encode("utf-8")
    ).hexdigest()
    source_asset_id = None
    if context.get("source_assets"):
        source_asset_id = context["source_assets"][0].get("id")
    properties = dict(recipe.get("properties") or {})
    properties.update(
        {
            "candidate_hash": digest,
            "original_candidate_hash": candidate.get("candidate_hash"),
            "reviewer_type": REVIEWER_TYPE,
            "human_reviewed": False,
            "human_review_faked": False,
            "model_or_external_api_used": False,
            "source_context_checked": True,
            "adjacent_context_checked": True,
        }
    )
    return {
        "candidate_id": f"{candidate['candidate_id']}_{index + 1}",
        "candidate_hash": digest,
        "unit_type": unit_type,
        "canonical_name": canonical_name,
        "title": recipe["title"],
        "content": recipe["content"],
        "aliases": list(recipe.get("aliases") or []),
        "keywords": list(recipe.get("keywords") or []),
        "properties": properties,
        "source": {
            "document_id": int(evidence.get("doc_id")),
            "chunk_id": int(evidence.get("id")),
            "page_no": evidence.get("page_start"),
            "section_title": evidence.get("section_path") or source.get("section_title"),
            "source_file": source.get("source_file"),
            "source_text_preview": str(evidence.get("text") or "")[:300].rstrip(),
        },
        "document_id": int(evidence.get("doc_id")),
        "source_chunk_id": int(evidence.get("id")),
        "source_asset_id": source_asset_id,
        "confidence": float(recipe.get("confidence", 0.9)),
        "extraction_method": "codex_source_grounded_repair",
        "dedup_key": f"source_review:{unit_type}:{canonical_name}",
        "review_status": "accepted",
        "provenance_status": "ready",
        "provenance_backfill_method": "database_source_context",
        "source_statement_supported": True,
        "provenance_verified": True,
    }


def review_candidates(
    candidates: list[dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
    existing_units: list[dict[str, Any]],
) -> dict[str, Any]:
    recipes = _repair_recipes()
    records: list[dict[str, Any]] = []
    accepted_pack: list[dict[str, Any]] = []
    decision_counts = {"accepted": 0, "duplicate": 0, "rejected": 0, "still_needs_human_review": 0}
    repaired_count = 0
    split_count = 0

    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id"))
        context = contexts[candidate_id]
        key = _candidate_key(candidate)
        decision = "rejected"
        reason = "The extracted candidate is not an independent source-supported knowledge unit."
        repaired_units: list[dict[str, Any]] = []
        duplicate_status: dict[str, Any] = {"is_duplicate": False}
        repair_actions: list[str] = []

        if key == (479, "concept", "chip"):
            decision = "duplicate"
            reason = "The same source passage is covered by the repaired Frontier cascaded-loop thermal-path unit."
            duplicate_status = {
                "is_duplicate": True,
                "duplicate_of_candidate_id": next(
                    (u.get("candidate_id") for u in accepted_pack if u.get("canonical_name") == "frontier_cascaded_cooling_loops"),
                    None,
                ),
                "duplicate_type": "batch_source_overlap",
                "similarity_reason": "same source passage and same architecture fact",
            }
        elif key == (495, "parameter", "thermal_conductivity"):
            decision = "duplicate"
            reason = "This misclassified extraction duplicates the dataset-specific heat content reviewed from the same passage."
            duplicate_status = {"is_duplicate": True, "duplicate_type": "same_passage_misclassification", "similarity_reason": "same source statement"}
        elif key == (559, "parameter", "flow_rate"):
            decision = "duplicate"
            reason = "This repeats the Figure A2 flow-rate extraction from the preceding chunk and still depends on figure interpretation."
            duplicate_status = {"is_duplicate": True, "duplicate_type": "adjacent_chunk_duplicate", "similarity_reason": "same figure caption and values"}
        elif key in STILL_HUMAN_KEYS:
            decision = "still_needs_human_review"
            if key[0] in (525, 558, 987):
                reason = "The primary evidence is a figure or damaged equation layout and requires visual or expert review."
            elif key[0] == 496:
                reason = "The source itself notes glycol composition-basis ambiguity; the density-based interpretation should not be accepted automatically."
            else:
                reason = "The vendor drawing/process-test context is too incomplete for a standalone fault-case unit."
        elif key in REJECT_KEYS:
            decision = "rejected"
            reason = "The rule-based extraction is misclassified, over-broad, or unsupported as a standalone unit by the checked source context."
        elif key in recipes:
            try:
                candidates_to_add = [
                    _materialize_unit(candidate, context, recipe, index)
                    for index, recipe in enumerate(recipes[key])
                ]
                for unit in candidates_to_add:
                    duplicate = _duplicate_match(unit, existing_units, accepted_pack)
                    if duplicate:
                        duplicate_status = duplicate
                        decision = "duplicate"
                        reason = "The repaired unit duplicates an existing or earlier batch knowledge unit."
                        repaired_units = []
                        break
                else:
                    repaired_units = candidates_to_add
                    accepted_pack.extend(repaired_units)
                    decision = "accepted"
                    reason = "The repaired statement is explicitly supported by the checked source and adjacent context with scoped conditions and limitations."
                    repair_actions = ["replace_misclassified_title", "scope_statement_to_source", "add_conditions", "add_limitations", "repair_provenance"]
                    if len(repaired_units) > 1:
                        repair_actions.append("split_candidate")
                        split_count += len(repaired_units) - 1
                    repaired_count += 1
            except ValueError as exc:
                decision = "still_needs_human_review"
                reason = f"Source evidence gate did not pass: {exc}"
        else:
            decision = "rejected"
            reason = "No conservative source-grounded repair recipe applies to this candidate."

        decision_counts[decision] += 1
        first = repaired_units[0] if repaired_units else None
        record = build_review_record(
            candidate,
            decision=decision,
            decision_reason=reason,
            source_context_checked=bool(context.get("source_context_checked")),
            adjacent_context_checked=bool(context.get("adjacent_context_checked")),
            reviewed_unit=first,
            repair_actions=repair_actions,
            duplicate_status=duplicate_status,
            confidence=float(first.get("confidence", 0.0)) if first else 0.0,
        )
        record["reviewed_units"] = repaired_units
        record["provenance_verified"] = bool(context.get("provenance_verified"))
        record["source_statement_supported"] = bool(repaired_units)
        record["source_evidence"] = {
            "document_title": context.get("document", {}).get("title"),
            "document_sha256": context.get("document", {}).get("sha256"),
            "current_chunk_id": context.get("chunk", {}).get("id"),
            "previous_chunk_ids": [item.get("id") for item in context.get("previous_chunks", [])],
            "next_chunk_ids": [item.get("id") for item in context.get("next_chunks", [])],
            "source_excerpt": str(context.get("chunk", {}).get("text") or "")[:500].rstrip(),
        }
        records.append(record)

    return {
        "input_candidates": len(candidates),
        "reviewed_candidates": len(records),
        "records": records,
        "accepted_pack": accepted_pack,
        "decision_counts": decision_counts,
        "repaired_count": repaired_count,
        "split_count": split_count,
        "provenance_verified_count": sum(bool(item.get("provenance_verified")) for item in records),
        "source_statement_supported_count": sum(bool(item.get("source_statement_supported")) for item in records),
        "reviewer_type": REVIEWER_TYPE,
        "human_reviewed": False,
        "human_review_faked": False,
        "model_or_external_api_used": False,
    }


def build_review_record(
    candidate: dict[str, Any],
    *,
    decision: str,
    decision_reason: str,
    source_context_checked: bool,
    adjacent_context_checked: bool,
    reviewed_unit: dict[str, Any] | None = None,
    repair_actions: list[str] | None = None,
    duplicate_status: dict[str, Any] | None = None,
    confidence: float = 0.0,
) -> dict[str, Any]:
    source = dict(candidate.get("source") or {})
    properties = dict(candidate.get("properties") or {})
    reviewed = dict(reviewed_unit or {})
    reviewed_properties = dict(reviewed.get("properties") or {})
    return {
        "candidate_id": candidate.get("candidate_id"),
        "candidate_hash": candidate.get("candidate_hash"),
        "source_document": source.get("source_file"),
        "document_id": source.get("document_id"),
        "chunk_id": source.get("chunk_id"),
        "source_page": source.get("page_no"),
        "source_section": source.get("section_title"),
        "original_unit_type": candidate.get("unit_type"),
        "original_title": candidate.get("title"),
        "original_content": candidate.get("content"),
        "original_variables": properties.get("variables", []),
        "original_units": properties.get("units", {}),
        "original_conditions": properties.get("conditions", []),
        "original_limitations": properties.get("limitations", []),
        "reviewed_unit_type": reviewed.get("unit_type"),
        "reviewed_title": reviewed.get("title"),
        "reviewed_content": reviewed.get("content"),
        "reviewed_variables": reviewed_properties.get("variables", []),
        "reviewed_units": reviewed_properties.get("units", {}),
        "reviewed_conditions": reviewed_properties.get("conditions", []),
        "reviewed_limitations": reviewed_properties.get("limitations", []),
        "provenance_verified": bool(reviewed.get("provenance_verified", False)),
        "source_statement_supported": bool(reviewed.get("source_statement_supported", False)),
        "source_context_checked": bool(source_context_checked),
        "adjacent_context_checked": bool(adjacent_context_checked),
        "duplicate_status": dict(duplicate_status or {"is_duplicate": False}),
        "decision": decision,
        "decision_reason": decision_reason,
        "repair_actions": list(repair_actions or []),
        "confidence": float(confidence),
        "reviewer_type": REVIEWER_TYPE,
        "human_reviewed": False,
        "human_review_faked": False,
        "model_or_external_api_used": False,
    }

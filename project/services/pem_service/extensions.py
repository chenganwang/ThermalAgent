"""Typed boundaries for future solvers and optimizers; all remain unavailable."""
from typing import Protocol


class SolverAdapter(Protocol):
    def submit(self, study: dict, candidate: dict) -> dict: ...
    def collect(self, solver_job_id: str) -> dict: ...


class GeometryAdapter(Protocol):
    def build(self, study: dict, candidate: dict) -> dict: ...


class ResearchStrategy(Protocol):
    def propose(self, study: dict, observed_records: list[dict]) -> dict: ...


def extension_catalog():
    return {"extensions": [{"name": name, "status": "not_implemented", "available": False,
                             "required_inputs": required, "interface": interface}
                            for name, required, interface in (
        ("pyfluent", ["licensed Fluent installation", "validated journal/case", "solver configuration"], "SolverAdapter"),
        ("parametric_geometry", ["expert approved CAD topology", "manufacturing and sealing constraints"], "GeometryAdapter"),
        ("surrogate_model", ["adequate verified same-condition observations", "independent holdout"], "ResearchStrategy"),
        ("morris_sobol", ["validated model", "defined input distributions", "adequate sample budget"], "ResearchStrategy"),
        ("nsga_ii", ["validated solver or surrogate", "expert objective/constraint definitions"], "ResearchStrategy"),
        ("active_learning", ["validated uncertainty estimates", "verified observed data"], "ResearchStrategy"))]}


def domain_catalog():
    return {"domains": [
        {"domain_id": "liquid_cooling", "title": "Liquid cooling thermal management", "status": "existing",
         "knowledge_scope": "existing_thermal_knowledge", "tools_scope": "existing_engineering_and_matlab",
         "constraints_scope": "existing_thermal_physics"},
        {"domain_id": "pem_flowfield", "title": "PEM flowfield pre-screening", "status": "mvp",
         "knowledge_scope": "pem_flowfield", "knowledge_status": "unavailable_no_expert_reviewed_pem_corpus",
         "tools_scope": ["parameter_validation", "latin_hypercube_doe", "observed_result_import", "quality_screening", "nondominated_observed_selection"],
         "constraints_scope": "pem_geometry_and_explicit_simulation_context", "reuse": ["EngineeringStore", "RunRecorder", "API authentication"],
         "agent_execution": "deterministic_research_workspace", "autonomous_llm_or_fluent_execution": False}],
        "domain_isolation": "PEM screening does not query or certify the liquid-cooling knowledge corpus"}

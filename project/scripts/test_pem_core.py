"""Isolated unit/API integration tests using real SciPy and EngineeringStore."""
from copy import deepcopy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

for thread_var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(thread_var, "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from services.engineering_service.store import EngineeringStore
from services.pem_service.api import router
from services.pem_service.contracts import DOERequest
from services.pem_service.doe import generate_candidates
from services.pem_service.extensions import domain_catalog, extension_catalog
from services.pem_service.parameters import ParameterError, candidate_constraints, example_study, validate_study
from services.pem_service.service import PEMService


def observed_row(study, candidate, **changes):
    n = candidate["normalized_parameters"]["channel_count"]
    definition = study["definition"]
    mass = study["normalized_boundary_conditions"]["mass_flow_rate"]["value"]
    return {"candidate_id": candidate["candidate_id"], "geometry_version": candidate["geometry_version"],
            "side": definition["side"], "physics_model": definition["physics_model"],
            "model_version": definition["model_version"], "fluid": definition["fluid"],
            "boundary_conditions": deepcopy(definition["boundary_conditions"]),
            "physical_model_details": {"flow_model": "laminar", "steady": True},
            "pressure_drop": 100, "pressure_drop_unit": "Pa", "inlet_mass_flow": mass,
            "pressure_drop_definition": {"pressure_kind": "static", "inlet_surface": "inlet", "outlet_surface": "outlet", "averaging": "area_weighted_mean", "sign_convention": "inlet_minus_outlet"},
            "inlet_mass_flow_unit": "kg/s", "outlet_mass_flow": mass, "outlet_mass_flow_unit": "kg/s",
            "channel_mass_flows": [mass / n] * n, "channel_mass_flows_unit": "kg/s",
            "mass_balance_scope": "whole_domain_all_boundaries", "flow_distribution_basis": "total_mass_flow",
            "mesh_id": "synthetic-demo-mesh", "mesh_cells": 10000, "mesh_min_orthogonal_quality": 0.5,
            "mesh_max_skewness": 0.5, "convergence_status": "converged", "iterations": 100,
            "residuals": {"continuity": 1e-6}, "convergence_criteria": {"continuity": 1e-4},
            "solver_version": "synthetic-demo-fixture-only", **changes}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pem_core_")
        self.addCleanup(self.temp.cleanup)
        self.engineering = EngineeringStore(Path(self.temp.name) / "engineering.sqlite3")
        self.service = PEMService(self.engineering)
        self.definition = example_study()
        self.study = self.service.create_study(self.definition)

    def sample(self, samples=5, seed=42):
        return self.service.doe(self.study["study_id"], {"samples": samples, "seed": seed})

    def test_seed_reproducibility_uses_actual_scipy(self):
        first, second = self.sample(), self.sample()
        self.assertEqual([c["normalized_parameters"] for c in first["candidates"]],
                         [c["normalized_parameters"] for c in second["candidates"]])
        self.assertEqual([c["geometry_version"] for c in first["candidates"]],
                         [c["geometry_version"] for c in second["candidates"]])
        self.assertNotEqual(first["batch_id"], second["batch_id"])
        self.assertFalse(set(c["candidate_id"] for c in first["candidates"]) & set(c["candidate_id"] for c in second["candidates"]))
        self.assertTrue(all(c.get("duplicate_of") for c in second["candidates"]))
        self.assertEqual(first["metadata"]["sampler"], "scipy.stats.qmc.LatinHypercube")

    def test_distinct_seed_changes_proposals(self):
        self.assertNotEqual([c["normalized_parameters"] for c in self.sample(seed=1)["candidates"]],
                            [c["normalized_parameters"] for c in self.sample(seed=2)["candidates"]])

    def test_all_candidates_obey_declared_bounds_and_geometry(self):
        batch = self.sample(samples=50)
        for c in batch["candidates"]:
            normalized, errors, _ = candidate_constraints(self.study["definition"]["parameter_space"], c["parameters"])
            self.assertEqual(errors, [])
            self.assertEqual(normalized, c["normalized_parameters"])
            self.assertIsInstance(normalized["channel_count"], int)
            self.assertEqual(c["observation_status"], "awaiting_simulation")

    def test_invalid_units_dimensions_bounds_and_missing_rejected(self):
        mutations = [lambda p: p["parameter_space"][0].update(unit="inch"),
                     lambda p: p["parameter_space"][0].update(lower=-1),
                     lambda p: p["parameter_space"][0].update(lower=2, upper=1),
                     lambda p: p["parameter_space"].pop(),
                     lambda p: p["parameter_space"][-2].update(lower=1.5),
                     lambda p: p["parameter_space"][0].update(source=" "),
                     lambda p: p["boundary_conditions"]["mass_flow_rate"].update(unit="L/min")]
        for mutate in mutations:
            payload = deepcopy(self.definition); mutate(payload)
            with self.subTest(payload=payload["parameter_space"][0]):
                with self.assertRaises((ParameterError, ValidationError)):
                    validate_study(payload)

    def test_boundary_si_and_dimension_overflow_rejected(self):
        p = deepcopy(self.definition)
        p["boundary_conditions"] = {"mass_flow_rate": {"value": 3.6, "unit": "kg/h"},
                                   "temperature": {"value": 25, "unit": "degC"},
                                   "outlet_pressure": {"value": 0.101325, "unit": "MPa"}}
        _, normalized, _ = validate_study(p)
        self.assertAlmostEqual(normalized["mass_flow_rate"]["value"], 0.001)
        self.assertAlmostEqual(normalized["temperature"]["value"], 298.15)
        self.assertAlmostEqual(normalized["outlet_pressure"]["value"], 101325)
        p["boundary_conditions"]["outlet_pressure"]["value"] = 1e308
        with self.assertRaises(ParameterError): validate_study(p)

    def test_no_manufacturing_bound_and_extremely_small_valid_geometry(self):
        p = deepcopy(self.definition)
        for s in p["parameter_space"]:
            if s["kind"] == "continuous": s["lower"] *= 1e-5; s["upper"] *= 1e-5
        _, _, warnings = validate_study(p)
        self.assertTrue(any("not certified manufacturing" in w for w in warnings))

    def test_impossible_geometry_refused_at_definition(self):
        for name, bounds in [("channel_depth", (3, 4)), ("plate_width", (0.5, 0.5))]:
            p = deepcopy(self.definition)
            next(s for s in p["parameter_space"] if s["name"] == name).update(lower=bounds[0], upper=bounds[1])
            with self.assertRaises(ParameterError): validate_study(p)

    def test_candidate_out_of_bounds_refused(self):
        candidate = self.sample(1)["candidates"][0]
        values = {**candidate["parameters"], "channel_width": 20}
        _, errors, _ = candidate_constraints(self.study["definition"]["parameter_space"], values)
        self.assertTrue(any("outside declared bounds" in s for s in errors))

    def test_nonparallel_topology_needs_expert_validation(self):
        p = deepcopy(self.definition); p["parameter_space"][-1]["choices"] = ["serpentine"]
        study = self.service.create_study(p)
        batch = self.service.doe(study["study_id"], {"samples": 1, "seed": 1})
        self.assertTrue(any("needs_expert_validation" in w for w in batch["candidates"][0]["warnings"]))

    def test_fixed_space_dedup_and_honest_shortfall(self):
        p = deepcopy(self.definition)
        for s in p["parameter_space"]:
            if s["kind"] != "categorical": s["upper"] = s["lower"]
        study = self.service.create_study(p)
        batch = self.service.doe(study["study_id"], {"samples": 5, "seed": 0, "max_attempts": 20})
        self.assertEqual(batch["accepted_samples"], 1)
        self.assertEqual(len(batch["rejected"]), 19)
        self.assertTrue(batch["warnings"])
        self.assertTrue(all("duplicate" in c["reasons"][0] for c in batch["rejected"]))

    def test_constraint_rejection_is_recorded(self):
        p = deepcopy(self.definition)
        next(s for s in p["parameter_space"] if s["name"] == "plate_width").update(lower=14, upper=14)
        study = self.service.create_study(p)
        batch = self.service.doe(study["study_id"], {"samples": 30, "seed": 42})
        self.assertTrue(batch["rejected"])
        self.assertTrue(all(r["parameters"] and r["reasons"] for r in batch["rejected"]))

    def test_strict_seed_and_finite_metadata(self):
        for seed in [True, 1.5, "42", -1]:
            with self.assertRaises(ValidationError): DOERequest(samples=2, seed=seed)
        p = deepcopy(self.definition); p["research_conditions"] = {"unknown": float("nan")}
        with self.assertRaises(ParameterError): validate_study(p)

    def test_child_version_preserves_parent_and_project(self):
        payload = {**deepcopy(self.definition), "parent_study_id": self.study["study_id"], "title": "Child version"}
        child = self.service.create_study(payload)
        self.assertEqual(child["study_version"], 2)
        self.assertEqual(self.service.store.get_study(self.study["study_id"]), self.study)
        project = self.engineering.create_project("Other project")
        payload["project_id"] = project["project_id"]
        with self.assertRaises(ValueError): self.service.create_study(payload)

    def test_doe_visible_existing_engineering_history_and_finished(self):
        batch = self.sample()
        run = self.engineering.get(batch["run_id"])
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["receipt"]["scope"], "pem_doe")
        self.assertTrue(run["receipt"]["finished_at"])
        self.assertIsNone(run["calculation_result"])
        self.assertTrue(any("Fluent" in s for s in run["receipt"]["limitations"]))

    def test_storage_failure_leaves_failed_operation_and_no_batch(self):
        with patch.object(self.service.store, "save_batch", side_effect=OSError("injected test fault")):
            with self.assertRaises(OSError): self.sample()
        runs = self.engineering.list_runs()["runs"]
        self.assertEqual(runs[0]["status"], "failed")
        self.assertEqual(self.service.store.batches(self.study["study_id"]), [])

    def test_transaction_rolls_back_partial_candidates(self):
        batch = generate_candidates(self.study, {"samples": 2, "seed": 42})
        run = self.sample(1)["run_id"]
        batch["run_id"] = run
        batch["candidates"][1]["candidate_id"] = batch["candidates"][0]["candidate_id"]
        with self.assertRaises(Exception): self.service.store.save_batch(batch)
        self.assertNotIn(batch["batch_id"], [b["batch_id"] for b in self.service.store.batches(self.study["study_id"])])

    def test_record_hash_tampering_refused(self):
        with self.engineering.connection() as con:
            con.execute("UPDATE pem_studies SET payload=? WHERE study_id=?", (json.dumps({"tampered": True}), self.study["study_id"]))
        with self.assertRaises(ValueError): self.service.store.get_study(self.study["study_id"])

    def test_domain_isolation_and_future_capabilities_truthful(self):
        pem = next(d for d in domain_catalog()["domains"] if d["domain_id"] == "pem_flowfield")
        self.assertIn("unavailable", pem["knowledge_status"])
        self.assertFalse(pem["autonomous_llm_or_fluent_execution"])
        self.assertTrue(all(not e["available"] and e["status"] == "not_implemented" for e in extension_catalog()["extensions"]))


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pem_api_")
        self.addCleanup(self.temp.cleanup)
        self.engineering = EngineeringStore(Path(self.temp.name) / "records.sqlite3")
        app = FastAPI(); app.include_router(router)
        app.state.agent = SimpleNamespace(engineering_store=self.engineering)
        self.client = TestClient(app)
        response = self.client.post("/pem/studies", json=example_study())
        self.assertEqual(response.status_code, 201, response.text)
        self.study = response.json()
        self.base = "/pem/studies/" + self.study["study_id"]
        response = self.client.post(self.base + "/doe", json={"samples": 3, "seed": 42})
        self.assertEqual(response.status_code, 200, response.text)
        self.batch = response.json()

    def imported(self, format="json", rows=None, filename="demo.json", field_map=None):
        rows = rows or [observed_row(self.study, c) for c in self.batch["candidates"]]
        if format == "csv":
            stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader()
            for row in rows: writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()})
            content = stream.getvalue()
        else: content = json.dumps(rows)
        response = self.client.post(self.base + "/imports", json={"content": content, "format": format,
                                    "filename": filename, "provenance": "synthetic_demo", "field_map": field_map or {}})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json(), content

    def test_complete_json_demo_quality_compare_report_source_history(self):
        imported, content = self.imported()
        self.assertEqual(imported["counts"]["screened"], 3)
        self.assertEqual(len(self.client.get(self.base + "/results").json()["results"]), 3)
        compared = self.client.post(self.base + "/compare", json={}).json()
        self.assertEqual(len(compared["groups"]), 1)
        self.assertTrue(compared["observed_only"])
        report = self.client.get(self.base + "/report").json()
        self.assertIn("合成", report["content"])
        self.assertEqual(self.client.get(self.base + "/report?format=markdown").status_code, 200)
        source = self.client.get(self.base + "/imports/" + imported["import_id"] + "/source")
        self.assertEqual(source.content, content.encode("utf-8"))
        self.assertEqual(source.headers["x-content-sha256"], hashlib.sha256(source.content).hexdigest())
        self.assertEqual(self.engineering.get(imported["run_id"])["receipt"]["scope"], "pem_import")
        self.assertEqual(self.client.get(self.base).json()["workflow"]["fluent_execution"], "not_executed")

    def test_csv_mapping_and_exact_original_recovery(self):
        row = observed_row(self.study, self.batch["candidates"][0]); row["external_dp"] = row.pop("pressure_drop")
        imported, content = self.imported("csv", [row], "fluent-demo.csv", {"pressure_drop": "external_dp"})
        self.assertEqual(imported["counts"]["screened"], 1)
        self.assertEqual(imported["records"][0]["quality"]["metrics"]["pressure_drop_pa"], 100)
        self.assertEqual(self.client.get(self.base + "/imports/" + imported["import_id"] + "/source").content, content.encode())

    def test_invalid_and_unconverged_cases_preserved_excluded(self):
        row = observed_row(self.study, self.batch["candidates"][0], convergence_status="unconverged", outlet_mass_flow=0.0001)
        imported, _ = self.imported(rows=[row])
        self.assertEqual(imported["counts"], {"total": 1, "screened": 0, "invalid": 1})
        comparison = self.client.post(self.base + "/compare", json={}).json()
        self.assertEqual(comparison["groups"], [])
        self.assertEqual(len(comparison["excluded"]), 1)
        self.assertEqual(len(self.client.get(self.base + "/results").json()["results"]), 1)
        self.assertEqual(self.client.get(self.base).json()["workflow"]["quality"], "invalid")

    def test_different_conditions_models_not_ranked(self):
        a = observed_row(self.study, self.batch["candidates"][0])
        b = observed_row(self.study, self.batch["candidates"][1]); b["boundary_conditions"]["temperature"]["value"] = 333
        c = observed_row(self.study, self.batch["candidates"][2], physics_model="two_phase")
        self.imported(rows=[a, b, c])
        compared = self.client.post(self.base + "/compare", json={}).json()
        self.assertFalse(compared["cross_group_ranking_allowed"])
        self.assertEqual(compared["groups"][0]["sample_count"], 1)
        self.assertEqual(len(compared["excluded"]), 2)

    def test_csv_and_json_candidates_export(self):
        exported = self.client.get(self.base + "/candidates").json()
        self.assertEqual(len(exported["candidates"]), 3)
        self.assertEqual(exported["study"]["input_hash"], self.study["input_hash"])
        self.assertTrue(exported["study"]["definition"]["parameter_space"][0]["source"])
        self.assertEqual(exported["batches"][0]["run_id"], self.batch["run_id"])
        self.assertIn("rejected", exported["batches"][0])
        response = self.client.get(self.base + "/candidates?format=csv")
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 3)
        self.assertIn("channel_width[mm]", rows[0])
        self.assertIn("geometry_version", rows[0])
        self.assertEqual(rows[0]["seed"], "42")
        self.assertTrue(json.loads(rows[0]["parameter_sources"]))
        self.assertEqual(json.loads(rows[0]["boundary_conditions"])["temperature"]["unit"], "K")

    def test_unsafe_filename_invalid_unit_and_secret_safe_errors(self):
        payload = {"content": "[]", "format": "json", "filename": "../../private.env", "provenance": "synthetic_demo"}
        self.assertEqual(self.client.post(self.base + "/imports", json=payload).status_code, 422)
        payload["filename"] = "safe.json"; payload["content"] = "secret-value-invalid-json"
        response = self.client.post(self.base + "/imports", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("secret-value", response.text)
        payload = example_study(); payload["parameter_space"][0]["unit"] = "inch"
        self.assertEqual(self.client.post("/pem/studies", json=payload).status_code, 422)

    def test_wrong_study_source_and_unknown_comparison_rejected(self):
        imported, _ = self.imported()
        other = self.client.post("/pem/studies", json=example_study()).json()
        response = self.client.get("/pem/studies/" + other["study_id"] + "/imports/" + imported["import_id"] + "/source")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post(self.base + "/compare", json={"result_ids": ["wrong_result"]}).status_code, 422)

    def test_source_tamper_refused(self):
        imported, _ = self.imported()
        with self.engineering.connection() as con:
            con.execute("UPDATE pem_imports SET content=? WHERE import_id=?", (b"tampered", imported["import_id"]))
        self.assertEqual(self.client.get(self.base + "/imports/" + imported["import_id"] + "/source").status_code, 422)

    def test_nonfinite_validation_does_not_break_json(self):
        payload = example_study(); payload["boundary_conditions"]["temperature"]["value"] = float("nan")
        response = self.client.post("/pem/studies", content=json.dumps(payload), headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)
        self.assertIsInstance(response.json()["detail"], list)

    def test_host_router_uses_existing_authentication(self):
        # Import the actual entrypoint; do not enter lifespan or initialize production resources.
        from services.retrieval_service.api.v11_api_server import app
        from services.engineering_service.api import get_store
        original = dict(app.dependency_overrides)
        app.dependency_overrides[get_store] = lambda: self.engineering
        try:
            with patch.dict(os.environ, {"RAG_API_KEY": "test-pem-only-token"}):
                client = TestClient(app)
                self.assertEqual(client.get("/pem/catalog").status_code, 401)
                headers = {"Authorization": "Bearer test-pem-only-token"}
                self.assertEqual(client.get("/pem/catalog", headers=headers).status_code, 200)
                self.assertEqual(client.get("/pem/studies", headers=headers).status_code, 200)
                capabilities = client.get("/capabilities", headers=headers).json()
                self.assertFalse(capabilities["pem_flowfield"]["real_fluent_execution_verified"])
                self.assertIn("engineering", capabilities)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)

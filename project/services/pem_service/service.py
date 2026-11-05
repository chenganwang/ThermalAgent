"""Deterministic research workflow sharing EngineeringStore and RunRecorder."""
from __future__ import annotations

import csv
import json
from io import StringIO
from uuid import uuid4

from services.engineering_service.execution import RunRecorder
from services.engineering_service.store import now
from . import VERSION
from .contracts import ImportRequest
from .doe import generate_candidates
from .parameters import canonical_hash, validate_study
from .store import PEMStore


class PEMService:
    def __init__(self, engineering_store):
        self.engineering = engineering_store
        self.store = PEMStore(engineering_store)

    def create_study(self, payload):
        definition, boundary, warnings = validate_study(payload)
        if not self.engineering.project_exists(definition["project_id"]):
            raise KeyError("Engineering project not found")
        parent = self.store.get_study(definition["parent_study_id"]) if definition.get("parent_study_id") else None
        if parent and parent["project_id"] != definition["project_id"]:
            raise ValueError("Child research version must belong to the same project")
        study = {"study_id": "pem_study_" + uuid4().hex, "study_version": parent["study_version"] + 1 if parent else 1,
                 "parent_study_id": definition.get("parent_study_id"), "project_id": definition["project_id"],
                 "domain_id": "pem_flowfield", "definition": definition, "normalized_boundary_conditions": boundary,
                 "input_hash": canonical_hash({"definition": definition, "normalization_version": VERSION}),
                 "created_at": now(), "schema_version": "1.0", "tool_version": VERSION, "warnings": warnings}
        return self.store.create_study(study)

    def get_study(self, study_id):
        study = self.store.get_study(study_id)
        batches, imports = self.store.batches(study_id), self.store.imports(study_id)
        counts = {"total": sum(i["counts"]["total"] for i in imports),
                  "screened": sum(i["counts"]["screened"] for i in imports),
                  "invalid": sum(i["counts"]["invalid"] for i in imports)}
        quality = ("mixed" if counts["screened"] and counts["invalid"] else
                   "invalid" if counts["invalid"] else "screened" if counts["screened"] else "pending")
        study["workflow"] = {"study_definition": "completed", "constraints": "screened",
                             "doe": "completed" if batches else "pending", "fluent_execution": "not_executed",
                             "results_import": "completed" if imports else "pending",
                             "quality": quality, "quality_counts": counts, "report": "available",
                             "batch_count": len(batches), "import_count": len(imports)}
        return study

    def operation(self, study, scope, request, execute):
        # Running checkpoint precedes specialty writes; failures are persisted as failed.
        run = {"schema_version": "1.1", "run_id": "engineering_" + uuid4().hex,
               "scope": scope, "domain_id": "pem_flowfield", "status": "running", "created_at": now(),
               "tool_name": scope, "tool_version": VERSION, "model_version": study["definition"]["model_version"],
               "input_snapshot": request, "input_fingerprint": canonical_hash(request),
               "study_id": study["study_id"], "study_version": study["study_version"],
               "steps": [{"step_id": "operation", "title": scope, "status": "running", "depends_on": []}],
               "variables": [], "events": [], "evidence": [], "validation": {"status": "incomplete"},
               "limitations": ["This Run records a PEM research operation; Fluent, MATLAB and LLM were not executed.",
                               "Operation completion does not mean CFD convergence or professional validation."],
               "report": {"generated": False}}
        recorder = RunRecorder(self.engineering, request, study["project_id"])
        try:
            recorder(run)
            if not recorder.state.get("saved"):
                raise RuntimeError("Engineering Run could not be persisted")
            result = execute(run["run_id"])
            run["status"] = "completed"
            run["finished_at"] = now()
            run["steps"][0]["status"] = "completed"
            run["validation"] = {"status": "operation_completed", "scope": scope, "professional_validation": False}
            recorder(run)
            if not recorder.state.get("saved"):
                raise RuntimeError("Engineering Run completion could not be persisted")
            return {**result, "run_id": run["run_id"], "persistence": recorder.state}
        except Exception:
            run["status"] = "failed"
            run["finished_at"] = now()
            run["steps"][0]["status"] = "failed"
            recorder(run)
            raise
        finally:
            recorder.close()

    def doe(self, study_id, payload):
        study = self.store.get_study(study_id)
        def execute(run_id):
            batch = {**generate_candidates(study, payload), "run_id": run_id}
            existing = {c["geometry_version"]: c["candidate_id"] for c in self.store.candidates(study_id)}
            duplicates = 0
            for candidate in batch["candidates"]:
                if candidate["geometry_version"] in existing:
                    candidate["duplicate_of"] = existing[candidate["geometry_version"]]
                    duplicates += 1
            if duplicates:
                batch["warnings"].append(f"{duplicates} geometries already exist in this study; candidate IDs are new and duplicate_of identifies earlier proposals.")
            self.store.save_batch(batch)
            return batch
        return self.operation(study, "pem_doe", {"study_id": study_id, "input_hash": study["input_hash"], "doe": payload}, execute)

    def import_results(self, study_id, payload):
        from .results import import_results
        request = ImportRequest.model_validate(payload).model_dump()
        study = self.store.get_study(study_id)
        source_hash = __import__("hashlib").sha256(request["content"].encode("utf-8")).hexdigest()
        operation_request = {"study_id": study_id, "input_hash": study["input_hash"],
                             **{k: v for k, v in request.items() if k != "content"}, "source_sha256": source_hash}
        def execute(run_id):
            imported = import_results(study, self.store.candidates(study_id), request["content"], request["format"],
                                      request["filename"], request["provenance"], request["field_map"])
            imported.update(import_id="pem_import_" + uuid4().hex, study_id=study_id, run_id=run_id, created_at=now())
            for record in imported["records"]:
                record.update(import_id=imported["import_id"], study_id=study_id)
            self.store.save_import(imported, request["content"])
            return imported
        return self.operation(study, "pem_import", operation_request, execute)

    def compare(self, study_id, result_ids=None):
        from .comparison import compare_results
        return compare_results(self.store.get_study(study_id), self.store.results(study_id), result_ids)

    def report(self, study_id):
        from .report import build_report
        study = self.store.get_study(study_id)
        comparison = self.compare(study_id)
        return {"study_id": study_id, "content": build_report(study, self.store.candidates(study_id),
                                                             self.store.results(study_id), comparison),
                "comparison": comparison}

    def candidate_csv(self, study_id):
        study = self.store.get_study(study_id)
        specs = study["definition"]["parameter_space"]
        fields = ["candidate_id", "study_id", "study_version", "batch_id", "geometry_version", "observation_status"]
        metadata_fields = ["seed", "sampler", "scipy_version", "tool_version", "input_hash", "parameter_sources", "boundary_conditions", "duplicate_of"]
        fields += [f"{s['name']}[{s['unit']}]" for s in specs]
        fields += metadata_fields
        stream = StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for candidate in self.store.candidates(study_id):
            writer.writerow({**{k: candidate[k] for k in fields[:6]},
                             **{f"{s['name']}[{s['unit']}]": candidate["parameters"][s["name"]] for s in specs},
                             **{k: candidate["generation_basis"][k] for k in metadata_fields[:5]},
                             "parameter_sources": json.dumps({s["name"]: s["source"] for s in specs}, ensure_ascii=False),
                             "boundary_conditions": json.dumps(study["definition"]["boundary_conditions"], ensure_ascii=False),
                             "duplicate_of": candidate.get("duplicate_of", "")})
        return stream.getvalue()

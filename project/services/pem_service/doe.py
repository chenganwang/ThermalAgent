"""Reproducible SciPy LHS proposal generation; no performance prediction."""
from __future__ import annotations

import math
from uuid import uuid4

from services.engineering_service.store import now
from . import VERSION
from .contracts import DOERequest
from .parameters import canonical_hash, candidate_constraints


def generate_candidates(study, payload):
    request = DOERequest.model_validate(payload).model_dump()
    try:
        import scipy
        from scipy.stats import qmc
    except ImportError:
        raise RuntimeError("SciPy is required for Latin hypercube sampling") from None
    specs = study["definition"]["parameter_space"]
    batch_id = "pem_batch_" + uuid4().hex
    accepted, rejected, seen = [], [], set()
    # One declared LHS design per operation; constraints may reduce the retained count.
    attempts = min(request["max_attempts"], max(request["samples"], request["samples"] * 10))
    sampler = qmc.LatinHypercube(d=len(specs), rng=request["seed"])
    points = sampler.random(attempts)
    metadata = {"sampler": "scipy.stats.qmc.LatinHypercube", "scipy_version": scipy.__version__,
                "tool_version": VERSION, "seed": request["seed"], "lhs_design_size": attempts,
                "requested_samples": request["samples"], "max_attempts": request["max_attempts"],
                "input_hash": study["input_hash"], "selection": "first feasible distinct points in ordered LHS design",
                "limitations": ["Constraint rejection and truncation mean the retained subset is not a full Latin hypercube.",
                                "Candidates are unobserved proposals, not optimized or simulated structures."]}
    attempted = 0
    for point in points:
        attempted += 1
        values = {}
        for s, u in zip(specs, point):
            if s["kind"] == "categorical":
                values[s["name"]] = s["choices"][min(len(s["choices"]) - 1, int(u * len(s["choices"])))]
            elif s["kind"] == "integer":
                values[s["name"]] = int(s["lower"]) + min(int(s["upper"] - s["lower"]), int(u * (s["upper"] - s["lower"] + 1)))
            else:
                values[s["name"]] = s["lower"] + float(u) * (s["upper"] - s["lower"])
        normalized, reasons, warnings = candidate_constraints(specs, values)
        geometry_hash = canonical_hash(normalized) if normalized else None
        if not reasons and geometry_hash in seen:
            reasons = ["duplicate: normalized geometry already retained in this DOE batch"]
        if reasons:
            rejected.append({"sample_index": attempted - 1, "parameters": values, "reasons": reasons})
        else:
            seen.add(geometry_hash)
            accepted.append({"candidate_id": "pem_candidate_" + uuid4().hex, "study_id": study["study_id"],
                             "study_version": study["study_version"], "batch_id": batch_id,
                             "geometry_version": "geometry_" + geometry_hash, "parameters": values,
                             "normalized_parameters": normalized, "parameter_units": {s["name"]: s["unit"] for s in specs},
                             "normalized_units": {s["name"]: ("m" if s["name"] in {"channel_width", "channel_depth", "channel_spacing", "plate_width", "plate_length", "plate_thickness"} else "1") for s in specs},
                             "created_at": now(), "sample_index": attempted - 1, "generation_basis": metadata,
                             "observation_status": "awaiting_simulation", "warnings": warnings})
        if len(accepted) == request["samples"]:
            break
    warnings = []
    if len(accepted) < request["samples"]:
        warnings.append(f"Only {len(accepted)} of {request['samples']} requested distinct feasible candidates were generated; no missing candidates were fabricated.")
    return {"batch_id": batch_id, "study_id": study["study_id"], "requested_samples": request["samples"],
            "accepted_samples": len(accepted), "attempted_samples": attempted, "candidates": accepted,
            "rejected": rejected, "metadata": metadata, "warnings": warnings, "created_at": now()}

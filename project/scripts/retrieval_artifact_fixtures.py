"""Explicit synthetic I/O fixtures for legacy retrieval artifact contract tests.

No production gold, index, database or saved runtime report is modified. Builders,
manifest transformation, diagnostics, review conversion and report writers remain
real; only external database/retrieval boundaries receive controlled records.
"""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import pickle
from unittest.mock import patch

import numpy as np
from services.retrieval_service.config import load_config
from services.retrieval_service.indexing.artifact_io import write_faiss_index
from services.retrieval_service.bm25_tokenizer import bm25_tokenize, LEGACY_TOKENIZER_VERSION


def deterministic_vectors(texts):
    vectors = np.asarray([list(hashlib.sha256(text.encode()).digest()[:16]) for text in texts], dtype="float32")
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


class ChunkConnection:
    def __init__(self, rows, calls):
        self.rows, self.calls, self.result = rows, calls, []

    def cursor(self, dictionary=True):
        return self

    def execute(self, sql, params=()):
        normalized = " ".join(sql.lower().split())
        assert normalized.startswith("select"), normalized
        assert "knowledge_units" not in normalized, "KU cannot enter the chunk production build"
        self.calls.append(normalized)
        if "count(*)" in normalized:
            self.result = [{"n": 0 if "d.id is null" in normalized else len(self.rows)}]
        elif "from embeddings" in normalized:
            self.result = [dict(chunk_id=1, vector_pos=0, model_name="fixture", embedding_model="fixture", dim=16, index_name="fixture", index_version="fixture-old", build_id="fixture-old")]
        elif "c.id as chunk_id" in normalized:
            self.result = self.rows
        else:
            raise AssertionError("Unexpected fixture SQL: " + normalized)

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)

    def close(self):
        pass


@contextmanager
def synthetic_index_environment(root, count=909):
    import faiss
    root = Path(root)
    indexes = root / "synthetic_production_indexes"
    indexes.mkdir(parents=True)
    original = load_config(root)
    cfg = replace(original, paths=replace(original.paths, project_root=root, data_dir=root / "data",
        faiss_dir=indexes, faiss_index_path=indexes / "faiss.index", faiss_meta_path=indexes / "faiss.index.meta.json",
        bm25_dir=indexes, bm25_corpus_path=indexes / "bm25.pkl", bm25_meta_path=indexes / "bm25.pkl.meta.json"))
    rows = [dict(chunk_id=i, document_id=(i - 1) % 9 + 1, page_start=i, page_end=i, section_path="Synthetic fixture",
                 text=f"Synthetic thermal index fixture {i}: conduction flow pressure validation.", stored_content_hash=None,
                 document_title=f"Synthetic document {(i - 1) % 9 + 1}", source_path=f"fixture_{(i - 1) % 9 + 1}.pdf",
                 local_path=None, document_sha256=None, source_asset_id=(i - 1) % 9 + 1) for i in range(1, count + 1)]
    index = faiss.IndexFlatIP(16)
    index.add(deterministic_vectors([rows[0]["text"]]))
    write_faiss_index(index, cfg.paths.faiss_index_path)
    cfg.paths.faiss_meta_path.write_text(json.dumps({"build_id": "fixture-old", "dim": 16, "ntotal": 1, "model_name": "synthetic-fixture", "normalize": True}), encoding="utf-8")
    with cfg.paths.bm25_corpus_path.open("wb") as handle:
        pickle.dump({"chunk_ids": [1], "tokenized_corpus": [bm25_tokenize(rows[0]["text"], version=LEGACY_TOKENIZER_VERSION)], "corpus_texts": [rows[0]["text"]]}, handle)
    cfg.paths.bm25_meta_path.write_text(json.dumps({"chunk_count": 1, "k1": cfg.bm25.k1, "b": cfg.bm25.b}), encoding="utf-8")
    calls = []
    with patch("services.retrieval_service.indexing.index_manifest.connect_mysql", side_effect=lambda *_args, **_kwargs: ChunkConnection(rows, calls)):
        yield cfg, rows, calls


SHADOW_TOPICS = [
    ("concept", "thermal_resistance"), ("concept", "conduction"), ("concept", "convection"),
    ("concept", "radiation"), ("concept", "laminar"), ("concept", "boiling"),
    ("parameter", "pressure_drop"), ("parameter", "flow_rate"), ("parameter", "conductivity"),
    ("parameter", "heat_capacity"), ("parameter", "viscosity"), ("parameter", "temperature_rise"),
    ("component", "gpu"), ("component", "cdu"), ("component", "cold_plate"),
    ("component", "pump"), ("component", "radiator"), ("component", "tim"),
    ("fault_case", "leakage"), ("fault_case", "blockage"), ("fault_case", "cavitation"),
    ("fault_case", "corrosion"), ("mixed", "gpu_leakage"), ("mixed", "cdu_pressure"),
]


def write_shadow_query_fixture(path):
    records = [dict(query_id=f"FIXTURE-SHADOW-{i:02d}", query=topic.replace("_", " "), category=category,
                    difficulty="medium" if category == "mixed" else "easy",
                    expected_unit_types=["component", "fault_case"] if category == "mixed" else [category],
                    expected_keywords=[topic.replace("_", " ")], expected_canonical_names=[topic],
                    notes="Synthetic deterministic contract fixture; not production retrieval gold.")
               for i, (category, topic) in enumerate(SHADOW_TOPICS, 1)]
    Path(path).write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    return records


def shadow_fixture_rows():
    return [dict(id=i, unit_code=f"fixture_{topic}", dedup_key=f"fixture:{topic}",
                 unit_type="component" if category == "mixed" else category, canonical_name=topic,
                 title=topic, content=f"Synthetic {topic.replace('_', ' ')} engineering evidence.", source_doc_id=9001,
                 source_chunk_id=9100 + i, provenance_status="ready", meta_json=None, updated_at="2026-01-01")
            for i, (category, topic) in enumerate(SHADOW_TOPICS, 1)]

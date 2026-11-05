"""Read-only projections for index coverage and the existing engineering task store."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from ..contracts import AdminAPIError


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _metadata(path):
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("Index metadata unavailable")
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError("Invalid index metadata")
    return result


def knowledge_coverage(repository, *, resolve_bundle=None):
    """Compare active source IDs with the current mapping, never rebuild/load a model.

    Legacy artifact counts are metadata, not a fresh numerical index validation.
    Active-bundle resolution additionally applies its existing artifact hash checks.
    """
    if resolve_bundle is None:
        from services.retrieval_service.indexing.active_bundle import resolve_active_bundle
        resolve_bundle = resolve_active_bundle
    result = {
        "schema_version": "1.0", "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "unknown", "documents_count": None, "active_chunks": None,
        "indexed_active_chunks": None, "missing_chunks": None, "coverage_ratio": None,
        "documents": [], "index": {"status": "unknown", "version": None, "faiss_count": None, "bm25_count": None},
        "warnings": [], "read_only": True, "quality_verified": False,
        "measurement": "metadata_and_current_chunk_mapping", "side_effects": [],
    }
    try:
        bundle = resolve_bundle(repository.cfg)
        paths = bundle.cfg.paths
        faiss = _metadata(paths.faiss_meta_path)
        bm25 = _metadata(paths.bm25_meta_path)
        if not paths.faiss_index_path.is_file() or not paths.bm25_corpus_path.is_file():
            raise ValueError("Index artifacts unavailable")
        faiss_count = _count(faiss.get("ntotal"))
        bm25_count = _count(bm25.get("chunk_count"))
        if faiss_count is None or bm25_count is None:
            raise ValueError("Invalid index count")
        result["index"].update({"version": bundle.version, "faiss_count": faiss_count,
                                "bm25_count": bm25_count, "active_bundle": bundle.active,
                                "artifact_hashes_verified": bundle.active})
    except Exception:
        bundle = None
        result["warnings"].append("INDEX_COVERAGE_UNAVAILABLE")
    connection = None
    try:
        connection = repository._connect()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT d.id AS document_id, d.title, c.id AS chunk_id FROM documents d "
                       "LEFT JOIN chunks c ON c.doc_id=d.id AND c.is_active=1 "
                       "AND c.text IS NOT NULL AND CHAR_LENGTH(TRIM(c.text))>0 ORDER BY d.id,c.id")
        rows = cursor.fetchall() or []
        documents = {}
        active = set()
        for row in rows:
            document_id = int(row["document_id"])
            document = documents.setdefault(document_id, {"document_id": document_id, "title": row.get("title") or "未命名文档", "active_chunks": 0})
            if row.get("chunk_id") is not None:
                document["active_chunks"] += 1
                active.add(int(row["chunk_id"]))
        result["documents_count"] = len(documents)
        result["active_chunks"] = len(active)
        result["documents"] = [{**d, "indexed_chunks": None, "missing_chunks": None, "status": "unknown"} for d in documents.values()]
        if bundle is None:
            result["documents"] = [{**d, "indexed_chunks": None, "missing_chunks": None, "status": "unknown"} for d in documents.values()]
            return result
        if bundle.mapping_chunk_ids is None:
            cursor.execute("SELECT chunk_id, vector_pos FROM embeddings ORDER BY vector_pos")
            mappings = cursor.fetchall() or []
            ids = [int(row["chunk_id"]) for row in mappings]
            positions = [int(row["vector_pos"]) for row in mappings]
            contiguous = positions == list(range(len(ids)))
        else:
            ids = list(bundle.mapping_chunk_ids)
            contiguous = True
        if not contiguous or len(ids) != len(set(ids)) or len(ids) != faiss_count or faiss_count != bm25_count:
            result["index"]["status"] = "inconsistent"
            result["warnings"].append("INDEX_MAPPING_COUNTS_INCONSISTENT")
            result["documents"] = [{**d, "indexed_chunks": None, "missing_chunks": None, "status": "unknown"} for d in documents.values()]
            return result
        indexed = set(ids)
        matched = indexed & active
        by_document = Counter(int(row["document_id"]) for row in rows if row.get("chunk_id") in matched)
        missing = len(active - indexed)
        stale = len(indexed - active)
        state = "gap" if missing or stale else "covered"
        result.update({"status": state, "indexed_active_chunks": len(matched), "missing_chunks": missing,
                       "coverage_ratio": len(matched) / len(active) if active else None})
        result["index"].update({"status": state, "mapped_chunks": len(ids), "stale_mappings": stale})
        result["documents"] = [{**d, "indexed_chunks": by_document[key],
                                "missing_chunks": d["active_chunks"] - by_document[key],
                                "status": "gap" if d["active_chunks"] != by_document[key] else "covered"}
                               for key, d in documents.items()]
        return result
    except Exception:
        result["warnings"].append("COVERAGE_DATABASE_UNAVAILABLE")
        result["status"] = "unknown"
        return result
    finally:
        if connection is not None:
            connection.close()


class AdminTaskReader:
    """Uses the canonical task projection under Admin authorization, with no writes."""
    def __init__(self, project_root=None):
        self.project_root = project_root or Path(__file__).resolve().parents[3]

    def read(self, task_id=None, *, limit=30, offset=0):
        from services.engineering_service.execution import configured_store
        from services.engineering_service.store import identifier
        if task_id:
            try:
                identifier(task_id)
            except ValueError:
                raise AdminAPIError("AGENT_TASK_NOT_FOUND", "任务记录不存在。", status_code=404) from None
        try:
            from services.engineering_service.task_store import read_only_tasks
        except ImportError:
            raise AdminAPIError("AGENT_TASK_MONITOR_UNAVAILABLE", "任务监控接口暂不可用。", status_code=503) from None
        try:
            store = configured_store(self.project_root)
        except Exception:
            raise AdminAPIError("AGENT_TASK_MONITOR_UNAVAILABLE", "任务存储配置暂时无法读取。", status_code=503) from None
        if store is None:
            if task_id:
                raise AdminAPIError("AGENT_TASK_NOT_FOUND", "任务记录不存在。", status_code=404)
            return {"tasks": [], "total": 0, "store_available": False, "persistence_enabled": False}
        try:
            return read_only_tasks(store.path, task_id=task_id, limit=limit, offset=offset)
        except KeyError:
            raise AdminAPIError("AGENT_TASK_NOT_FOUND", "任务记录不存在。", status_code=404) from None
        except Exception:
            raise AdminAPIError("AGENT_TASK_MONITOR_UNAVAILABLE", "任务记录暂时无法读取。", status_code=503, retryable=True) from None


def get_admin_task_reader():
    return AdminTaskReader()

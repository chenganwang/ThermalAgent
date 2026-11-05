from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        mapped = value.to_dict()
        return dict(mapped) if isinstance(mapped, Mapping) else {}
    return {}


def _source_summary(source: Any) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        return {}
    summary: dict[str, Any] = {}
    for key in ("doc_id", "chunk_id", "title", "page_start", "page_end", "score"):
        if source.get(key) is not None:
            summary[key] = source.get(key)
    preview = source.get("text_preview") or source.get("preview")
    if preview:
        summary["preview_chars"] = len(str(preview))
    return summary


@dataclass
class CritiqueWorkflowState:
    query: str
    answer: str
    task: dict[str, Any] = field(default_factory=dict)
    rewrite: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    critique_result: dict[str, Any] | None = None
    repair_attempts: int = 0
    final_answer: str | None = None
    workflow_trace: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        query: str,
        answer: str,
        sources: list[dict] | None = None,
        metadata: dict | None = None,
        task: dict | None = None,
        rewrite: dict | None = None,
    ) -> "CritiqueWorkflowState":
        return cls(
            query=query or "",
            answer=answer or "",
            task=_as_mapping(task),
            rewrite=_as_mapping(rewrite),
            sources=list(sources or []),
            metadata=_as_mapping(metadata),
            final_answer=answer or "",
        )

    def add_trace(self, node: str, status: str = "ok", **data: Any) -> None:
        item = {"node": node, "status": status}
        item.update({key: value for key, value in data.items() if value is not None})
        self.workflow_trace.append(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "answer_chars": len(self.answer),
            "task": self.task,
            "rewrite": self.rewrite,
            "sources_count": len(self.sources),
            "sources_summary": [_source_summary(source) for source in self.sources[:5]],
            "metadata_keys": sorted(self.metadata.keys()),
            "critique_result": self.critique_result,
            "repair_attempts": self.repair_attempts,
            "final_answer_chars": len(self.final_answer or ""),
            "final_answer_unchanged": self.final_answer == self.answer,
            "workflow_trace": list(self.workflow_trace),
            "errors": list(self.errors),
        }


__all__ = ["CritiqueWorkflowState"]

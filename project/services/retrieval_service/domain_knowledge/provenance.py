from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


PROVENANCE_VERIFIED = "verified"
PROVENANCE_PENDING = "pending"
PROVENANCE_SOURCE_REQUIRED = "source_required"

VALID_PROVENANCE_STATUSES = {
    PROVENANCE_VERIFIED,
    PROVENANCE_PENDING,
    PROVENANCE_SOURCE_REQUIRED,
}


@dataclass(frozen=True)
class ProvenanceRecord:
    status: str
    source_id: str | None = None
    source_name: str | None = None
    source_type: str | None = None
    document_id: int | None = None
    document_name: str | None = None
    page: str | int | None = None
    section: str | None = None
    note: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ProvenanceRecord":
        data = dict(raw or {})
        status = str(data.get("status") or PROVENANCE_SOURCE_REQUIRED)
        if status not in VALID_PROVENANCE_STATUSES:
            status = PROVENANCE_SOURCE_REQUIRED
        return cls(
            status=status,
            source_id=_optional_str(data.get("source_id")),
            source_name=_optional_str(data.get("source_name")),
            source_type=_optional_str(data.get("source_type")),
            document_id=_optional_int(data.get("document_id")),
            document_name=_optional_str(data.get("document_name")),
            page=data.get("page"),
            section=_optional_str(data.get("section")),
            note=_optional_str(data.get("note")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_verified(self) -> bool:
        return self.status == PROVENANCE_VERIFIED


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_provenance_zh(record: ProvenanceRecord) -> str:
    if record.status == PROVENANCE_VERIFIED:
        parts = [record.source_name or record.document_name or record.source_id or "verified source"]
        if record.page not in (None, ""):
            parts.append(f"page={record.page}")
        if record.section:
            parts.append(f"section={record.section}")
        return "来源：已验证，" + "，".join(parts) + "。"
    if record.status == PROVENANCE_PENDING:
        note = record.note or "本地已有结构化记录，但尚未绑定可审计的文档页码。"
        return f"来源状态：pending，{note}"
    note = record.note or "需要补充教材、手册或厂商数据表来源后才能标记为 verified。"
    return f"来源状态：source_required，{note}"


__all__ = [
    "PROVENANCE_PENDING",
    "PROVENANCE_SOURCE_REQUIRED",
    "PROVENANCE_VERIFIED",
    "ProvenanceRecord",
    "VALID_PROVENANCE_STATUSES",
    "format_provenance_zh",
]

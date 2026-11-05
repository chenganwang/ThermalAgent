from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CritiqueIssue:
    type: str
    severity: str
    message: str
    suggested_action: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    node: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CritiqueResult:
    enabled: bool
    passed: bool
    severity: str
    issues: list[CritiqueIssue] = field(default_factory=list)
    repair_action: str = "none"
    route: str = "finalize"
    requires_human_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [issue.to_dict() if isinstance(issue, CritiqueIssue) else issue for issue in self.issues]
        return data


def issue(
    *,
    type: str,
    severity: str,
    message: str,
    suggested_action: str,
    node: str,
    evidence: dict[str, Any] | None = None,
) -> CritiqueIssue:
    return CritiqueIssue(
        type=type,
        severity=severity,
        message=message,
        suggested_action=suggested_action,
        evidence=dict(evidence or {}),
        node=node,
    )


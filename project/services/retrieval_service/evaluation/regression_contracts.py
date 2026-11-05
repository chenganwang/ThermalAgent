from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RegressionTestItem:
    test_id: str
    command: str
    suite: str
    required: bool = True
    timeout_seconds: int = 120
    slow: bool = False
    reason: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["RegressionTestItem"]

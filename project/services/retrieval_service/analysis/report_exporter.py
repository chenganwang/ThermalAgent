from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
import os
import re
import secrets


REPORT_ID_RE = re.compile(r"^analysis_[0-9]{8}_[0-9]{6}_[a-f0-9]{8}$")


@dataclass
class ReportExportResult:
    generated: bool
    format: str
    report_id: str
    filename: str
    relative_path: str
    download_url: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_analysis_report_dir() -> Path:
    configured = os.environ.get("THERMAL_AGENT_ANALYSIS_REPORT_DIR")
    if configured:
        return Path(configured)
    return _project_root() / "reports" / "analysis"


def _new_report_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"analysis_{timestamp}_{secrets.token_hex(4)}"


def validate_report_id(report_id: str) -> bool:
    return bool(report_id and REPORT_ID_RE.fullmatch(report_id))


def _failure(
    *,
    export_format: str,
    errors: list[str],
    report_id: str = "",
    warnings: list[str] | None = None,
) -> ReportExportResult:
    return ReportExportResult(
        generated=False,
        format=export_format,
        report_id=report_id,
        filename="",
        relative_path="",
        download_url="",
        warnings=warnings or [],
        errors=errors,
    )


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_report_path(output_dir: Path, report_id: str) -> Path | None:
    base = output_dir.resolve()
    target = (base / f"{report_id}.md").resolve()
    if target.parent != base or not _is_relative_to(target, base):
        return None
    return target


def _redact_sensitive_lines(content: str) -> str:
    redacted_lines: list[str] = []
    sensitive_markers = ("PASSWORD", "SECRET", "TOKEN", "PRIVATE_KEY")
    for line in content.splitlines():
        if any(marker in line.upper() for marker in sensitive_markers):
            redacted_lines.append("[sensitive line omitted]")
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines)


def _sanitize_full_source_text(content: str, metadata: dict | None) -> tuple[str, list[str]]:
    if not metadata:
        return content, []

    warnings: list[str] = []
    sources = metadata.get("sources") if isinstance(metadata, dict) else None
    if not isinstance(sources, list):
        return content, warnings

    sanitized = content
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("text", "raw_text", "chunk_text", "expanded_text"):
            source_text = source.get(key)
            if isinstance(source_text, str) and len(source_text) > 120 and source_text in sanitized:
                sanitized = sanitized.replace(source_text, "[source text omitted]")
                warnings.append("full_source_text_omitted")
    return sanitized, warnings


def _sanitize_content(content: str, metadata: dict | None) -> tuple[str, list[str]]:
    sanitized = _redact_sensitive_lines(content)
    sanitized, source_warnings = _sanitize_full_source_text(sanitized, metadata)
    return sanitized, source_warnings


def resolve_exported_report_path(
    report_id: str,
    export_format: str = "md",
    output_dir: Path | None = None,
) -> tuple[Path | None, str | None]:
    normalized_format = (export_format or "").lower().strip()
    if normalized_format != "md":
        return None, "unsupported_format"
    if not validate_report_id(report_id):
        return None, "invalid_report_id"

    target_dir = output_dir or default_analysis_report_dir()
    target_path = _safe_report_path(target_dir, report_id)
    if target_path is None:
        return None, "invalid_report_path"
    return target_path, None


def export_markdown_report(
    content: str,
    title: str | None = None,
    output_dir: Path | None = None,
    metadata: dict | None = None,
    report_id: str | None = None,
    export_format: str = "md",
) -> ReportExportResult:
    """Export already-built Markdown report content to a local .md file."""

    del title

    normalized_format = (export_format or "").lower().strip()
    if normalized_format != "md":
        return _failure(export_format=normalized_format or export_format, errors=["unsupported_format"])

    if not content or not content.strip():
        return _failure(export_format="md", errors=["empty_content"])

    report_id = report_id or _new_report_id()
    if not validate_report_id(report_id):
        return _failure(export_format="md", errors=["invalid_report_id"], report_id=report_id)

    target_path, path_error = resolve_exported_report_path(
        report_id=report_id,
        export_format="md",
        output_dir=output_dir,
    )
    if target_path is None:
        return _failure(export_format="md", errors=[path_error or "invalid_report_path"], report_id=report_id)

    filename = f"{report_id}.md"
    sanitized_content, warnings = _sanitize_content(content.strip(), metadata)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(sanitized_content, encoding="utf-8")

    return ReportExportResult(
        generated=True,
        format="md",
        report_id=report_id,
        filename=filename,
        relative_path=str(Path("reports") / "analysis" / filename),
        download_url=f"/agent/reports/{report_id}/download?format=md",
        warnings=warnings,
    )


__all__ = [
    "ReportExportResult",
    "default_analysis_report_dir",
    "export_markdown_report",
    "resolve_exported_report_path",
    "validate_report_id",
]

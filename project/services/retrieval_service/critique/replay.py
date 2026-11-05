from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any, Mapping

from .workflow import run_critique_workflow


DEFAULT_REPLAY_REPORT_DIR = Path("reports/evaluation/self_critique_replay")
PREVIEW_LIMIT = 180


def _safe_id(value: Any) -> str:
    text = str(value or "manual_case").strip() or "manual_case"
    text = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", text)
    return text[:80] or "manual_case"


def _preview(value: Any, limit: int = PREVIEW_LIMIT) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _issues(self_critique: Mapping[str, Any]) -> list[dict[str, Any]]:
    original = self_critique.get("original_critique")
    if isinstance(original, Mapping) and isinstance(original.get("issues"), list):
        return [dict(item) for item in original["issues"] if isinstance(item, Mapping)]
    raw = self_critique.get("issues")
    return [dict(item) for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []


def _issue_types(self_critique: Mapping[str, Any]) -> list[str]:
    return sorted({str(issue.get("type")) for issue in _issues(self_critique) if issue.get("type")})


def _source_count(sources: Any) -> int:
    return len(sources) if isinstance(sources, list) else 0


def _normalize_case(case: dict) -> dict[str, Any]:
    normalized = dict(case or {})
    if "query" not in normalized and "query_preview" in normalized:
        normalized["query"] = normalized.get("query_preview") or ""
    if "answer" not in normalized and "answer_preview" in normalized:
        normalized["answer"] = normalized.get("answer_preview") or ""
    normalized.setdefault("id", normalized.get("case_id") or "manual_case")
    normalized.setdefault("type", normalized.get("case_type") or "manual")
    normalized.setdefault("query", "")
    normalized.setdefault("answer", "")
    normalized.setdefault("sources", [])
    normalized.setdefault("metadata", {})
    normalized.setdefault("enable_repair", False)
    return normalized


def _diff_summary(original_answer: str, final_answer: str) -> dict[str, list[str]]:
    if original_answer == final_answer:
        return {"removed_fragments": [], "added_fragments": []}
    removed: list[str] = []
    added: list[str] = []
    if original_answer and original_answer not in final_answer:
        removed.append(_preview(original_answer))
    if final_answer and final_answer not in original_answer:
        added.append(_preview(final_answer))
    return {"removed_fragments": removed[:3], "added_fragments": added[:3]}


def _markdown_report(result: dict, case: dict) -> str:
    critique = result.get("self_critique") or {}
    issues = _issues(critique)
    expected = {
        "expected_severity": case.get("expected_severity"),
        "expected_route": case.get("expected_route"),
        "expected_repair_action": case.get("expected_repair_action"),
    }
    lines = [
        "# Self-Critique Replay Report",
        "",
        "## 1. Case 信息",
        f"- id: `{result.get('case_id')}`",
        f"- type: `{result.get('case_type')}`",
        f"- enable_repair: `{result.get('enable_repair')}`",
        f"- expected_severity: `{expected['expected_severity']}`",
        f"- expected_route: `{expected['expected_route']}`",
        f"- expected_repair_action: `{expected['expected_repair_action']}`",
        "",
        "## 2. Query",
        "",
        result.get("query") or "",
        "",
        "## 3. Original Answer",
        "",
        result.get("original_answer") or "",
        "",
        "## 4. Self-Critique Result",
        f"- severity: `{critique.get('severity')}`",
        f"- passed: `{critique.get('passed')}`",
        f"- route: `{result.get('route')}`",
        f"- final_route: `{critique.get('final_route')}`",
        f"- repair_action: `{result.get('repair_action')}`",
        f"- repaired: `{result.get('repaired')}`",
        f"- repair_attempts: `{result.get('repair_attempts')}`",
        f"- requires_human_review: `{result.get('requires_human_review')}`",
        f"- issue_types: `{', '.join(result.get('detected_issue_types') or [])}`",
        "",
        "## 5. Issues",
    ]
    if issues:
        for issue in issues:
            lines.extend(
                [
                    f"- type: `{issue.get('type')}`",
                    f"  - severity: `{issue.get('severity')}`",
                    f"  - node: `{issue.get('node')}`",
                    f"  - message: {issue.get('message')}",
                    f"  - suggested_action: `{issue.get('suggested_action')}`",
                ]
            )
    else:
        lines.append("- None.")

    lines.extend(["", "## 6. Trace"])
    for item in result.get("trace") or []:
        lines.append(f"- `{item.get('node')}`: status=`{item.get('status')}`, route=`{item.get('route')}`")

    lines.extend(
        [
            "",
            "## 7. Final Answer",
            "",
            result.get("final_answer") or "",
            "",
            "## 8. Diff Summary",
            "",
        ]
    )
    diff = result.get("diff_summary") or {}
    lines.append(f"- removed_fragments: {diff.get('removed_fragments') or []}")
    lines.append(f"- added_fragments: {diff.get('added_fragments') or []}")

    lines.extend(
        [
            "",
            "## 9. Boundary Notes",
            "",
            "- replay 不修改数据库。",
            "- replay 不修改索引。",
            "- replay 不修改测试集 expected。",
            "- replay 不运行 CFD。",
            "- replay 只用于失败归因和回归样例构造。",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_reports(result: dict, case: dict, report_dir: str | None = None) -> tuple[str, str]:
    target_dir = Path(report_dir) if report_dir else DEFAULT_REPLAY_REPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    case_id = _safe_id(result.get("case_id"))
    md_path = target_dir / f"{case_id}_replay.md"
    json_path = target_dir / f"{case_id}_replay.json"
    md_path.write_text(_markdown_report(result, case), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(md_path), str(json_path)


def generate_candidate_case(replay_result: dict) -> dict[str, Any]:
    critique = _as_mapping(replay_result.get("self_critique"))
    original = _as_mapping(critique.get("original_critique"))
    return {
        "id": f"candidate_{_safe_id(replay_result.get('case_id'))}",
        "type": replay_result.get("case_type") or "manual",
        "query": replay_result.get("query") or "",
        "answer": replay_result.get("original_answer") or "",
        "sources": [],
        "metadata": _as_mapping(replay_result.get("metadata")),
        "enable_repair": bool(replay_result.get("enable_repair")),
        "expected_severity": original.get("severity") or critique.get("severity"),
        "expected_route": replay_result.get("route"),
        "expected_repair_action": original.get("repair_action") or critique.get("repair_action"),
        "expected_repaired": bool(replay_result.get("repaired")),
        "must_detect_issue_types": replay_result.get("detected_issue_types") or [],
        "must_contain_after_repair": [],
        "forbidden_after_repair": [],
        "notes": "Generated from replay; requires human review before adding to official dataset.",
    }


def replay_self_critique_case(
    case: dict,
    enable_repair: bool | None = None,
    write_report: bool = False,
    report_dir: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_case(case)
    effective_repair = bool(normalized.get("enable_repair")) if enable_repair is None else bool(enable_repair)
    query = str(normalized.get("query") or "")
    answer = str(normalized.get("answer") or "")
    sources = normalized.get("sources") if isinstance(normalized.get("sources"), list) else []
    metadata = _as_mapping(normalized.get("metadata"))

    critique = run_critique_workflow(
        query=query,
        answer=answer,
        sources=sources,
        metadata=metadata,
        enable_repair=effective_repair,
        max_repair_attempts=1 if effective_repair else 0,
    )
    final_answer = str(critique.get("final_answer") or answer)
    original_answer = str(critique.get("original_answer") or answer)
    result: dict[str, Any] = {
        "case_id": normalized.get("id"),
        "case_type": normalized.get("type"),
        "query": query,
        "enable_repair": effective_repair,
        "sources_count": _source_count(sources),
        "metadata": metadata,
        "original_answer": original_answer,
        "final_answer": final_answer,
        "answer_changed": original_answer != final_answer,
        "self_critique": critique,
        "detected_issue_types": _issue_types(critique),
        "route": critique.get("original_route") or critique.get("route"),
        "repair_action": (_as_mapping(critique.get("original_critique")).get("repair_action") or critique.get("repair_action")),
        "repaired": bool(critique.get("repaired")),
        "repair_attempts": int(critique.get("repair_attempts") or 0),
        "requires_human_review": bool(_as_mapping(critique.get("original_critique")).get("requires_human_review") or critique.get("requires_human_review")),
        "trace": critique.get("trace") or [],
        "diff_summary": _diff_summary(original_answer, final_answer),
        "report_path": None,
        "json_report_path": None,
        "candidate_case": {},
    }
    if write_report:
        md_path, json_path = _write_reports(result, normalized, report_dir=report_dir)
        result["report_path"] = md_path
        result["json_report_path"] = json_path
        # Rewrite JSON report after report paths are known.
        Path(json_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["candidate_case"] = generate_candidate_case(result)
    return result


__all__ = ["generate_candidate_case", "replay_self_critique_case"]

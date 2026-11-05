"""Read bounded numerical evidence. Solver exit success is not physics validation."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re

from .contracts import CaseSpec
from services.physics_service.contracts import PhysicsQuantity, PhysicsValidationRequest
from services.physics_service.validator import validate_physics

MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_POINTS = 500


def _number(raw: str) -> float:
    return float(raw.replace("D", "e").replace("d", "e"))


def _report_points(path: Path, column: int) -> list[list[float]]:
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("Report exceeds evidence size limit")
    points = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        tokens = line.strip().split()
        if not tokens or not re.match(r"^[+\-]?(?:\d|\.\d)", tokens[0]):
            continue
        if len(tokens) <= column:
            raise ValueError("Incomplete numeric report row")
        row = [_number(tokens[0]), _number(tokens[column])]
        if not all(math.isfinite(value) for value in row):
            raise ValueError("Non-finite report value")
        if points and row[0] < points[-1][0]:
            raise ValueError("Non-monotonic report iterations")
        points.append(row)
    return points[-MAX_POINTS:]


def parse_results(folder: Path, case: CaseSpec, transcript: str) -> dict:
    metrics, histories, checks, report_artifacts = [], [], [], []
    for spec in case.reports:
        # Fluent may suffix report files with run/iteration numbers. Refuse ambiguity.
        stem = Path(spec.filename).stem
        candidates = [p for p in folder.iterdir() if p.is_file() and re.fullmatch(re.escape(stem) + r"(?:[-_]\d+)*\.out", p.name)]
        if len(candidates) != 1:
            checks.append({"name": spec.name, "status": "incomplete", "message": "Expected one report file for this run."})
            continue
        try:
            candidate = candidates[0]
            if candidate.is_symlink() or candidate.resolve().parent != folder.resolve():
                raise ValueError("Report must remain inside the job")
            points = _report_points(candidate, spec.value_column)
            if not points:
                raise ValueError("Report has no numeric data")
            report_artifacts.append({"name": spec.name, "artifact_id": "report_" + spec.name,
                                     "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                                     "size_bytes": candidate.stat().st_size})
            value = points[-1][1]
            metrics.append({"name": spec.name, "value": value, "unit": spec.unit})
            histories.append({"name": spec.name, "unit": spec.unit, "points": points})
            physical = validate_physics(PhysicsValidationRequest(quantities=[PhysicsQuantity(
                name=spec.name, value=value, unit=spec.unit, quantity_type=spec.quantity_type,
                minimum=spec.minimum, maximum=spec.maximum,
            )]))
            checks.append({"name": spec.name, "status": physical.status,
                           "message": "Finite value and configured physical bounds checked.",
                           "issues": [issue.model_dump() for issue in physical.issues]})
        except (OSError, ValueError, OverflowError):
            checks.append({"name": spec.name, "status": "failed", "message": "Report contains invalid or unreadable numerical evidence."})
    header, residuals = [], {}
    for line in transcript.splitlines():
        tokens = line.split()
        if tokens and tokens[0].lower() in {"iter", "iteration"} and any(name in tokens for name in case.residual_targets):
            header = tokens[1:]
        elif header and tokens and tokens[0].isdigit():
            for index, name in enumerate(header, 1):
                if name in case.residual_targets:
                    try:
                        residuals[name] = _number(tokens[index])
                    except (ValueError, IndexError):
                        residuals[name] = math.nan
    for name, target in case.residual_targets.items():
        value = residuals.get(name)
        state = "incomplete" if value is None else "passed" if math.isfinite(value) and 0 <= value <= target else "failed"
        checks.append({"name": "residual_" + name, "status": state, "message": f"Final residual must be finite and between 0 and {target:g}."})
    if not case.reports:
        checks.append({"name": "engineering_outputs", "status": "incomplete", "message": "No engineering report definitions were registered."})
    if not case.residual_targets:
        checks.append({"name": "convergence", "status": "incomplete", "message": "No residual convergence targets were registered."})
    state = "failed" if any(c["status"] == "failed" for c in checks) else "incomplete" if any(c["status"] == "incomplete" for c in checks) else "passed"
    return {"metrics": metrics, "histories": histories, "report_artifacts": report_artifacts,
            "validation": {"status": state, "checks": checks, "validator_version": "physics-v1"}, "is_mock": False,
            "limitations": ["Checks do not establish mesh independence, model validity, or conservation unless independently assessed."]}


def build_report(job: dict) -> str:
    result = job.get("result") or {}
    backend = job.get("effective_backend") or result.get("effective_backend") or "unknown"
    is_mock = job.get("is_mock") is True or result.get("is_mock") is True or backend == "mock"
    lines = ["# CFD 任务报告", "", f"- 任务：`{job['job_id']}`", f"- 请求模式：{job.get('requested_backend', 'unknown')}",
             f"- 有效后端：{'Mock CFD（演示数据）' if is_mock else backend}", f"- is_mock：{'true' if is_mock else 'false'}",
             f"- 请求算例：`{job.get('requested_case_id', job['case_id'])}`", f"- 实际算例：`{job.get('effective_case_id', job['case_id'])}`", f"- 运行状态：{job['status']}",
             f"- 输入指纹：`{job['input_fingerprint']}`", f"- 迭代上限：{job['iterations']}；计算进程：{job['processors']}",
             ""]
    if is_mock:
        lines += ["> 本结果来自 Mock CFD 的解析演示，并非真实 CFD 求解结果；演示数值不能用于真实工程设计结论，也不代表请求的真实算例。若先前尝试过真实后端，其启动或许可失败记录保留在下文。", ""]
    fallback = job.get("fallback_reason") or result.get("fallback_reason")
    if isinstance(fallback, dict):
        lines += [f"备用后端原因：{fallback.get('code', '')} — {fallback.get('message', '')}", ""]
    lines += ["## 执行记录", ""]
    lines += [f"- {s['name']}：{s['status']} — {s['detail']}" for s in job['steps']]
    if job.get("attempts"):
        lines += ["", "## 后端尝试", ""]
        for attempt in job["attempts"]:
            error = attempt.get("error") or {}
            lines.append(f"- {attempt.get('backend', 'unknown')}：{attempt.get('status', 'unknown')}；退出码={attempt.get('exit_code')}；{error.get('code', '')} {error.get('message', '')}")
    if result:
        lines += ["", "## 关键结果", "", "| 量 | 数值 | 单位 |", "|---|---:|---|"]
        lines += [f"| {m['name']} | {m['value']:.8g} | {m['unit']} |" for m in result['metrics']]
        lines += ["", "## 独立规则校验", "", f"状态：{result['validation']['status']}", ""]
        lines += [f"- {c['name']}：{c['status']} — {c['message']}" for c in result['validation']['checks']]
        if result.get("limitations"):
            lines += ["", "## 结果限制", ""] + [f"- {item}" for item in result["limitations"]]
    if job.get("error"):
        lines += ["", f"错误：{job['error']['code']} — {job['error']['message']}"]
    scope = "Mock 的检查只验证演示合同和解析数据，不能证明真实流场、收敛或物理模型有效。" if is_mock else "真实 Fluent 仅适用于人工配置并审核的稳态 HDF5 算例；数值/阈值检查不代替网格无关性、湍流模型适用性、边界条件审查或独立守恒检验。"
    lines += ["", "## 适用范围", "", scope, "任务完成不等于工程验证通过。任务快照、hash、有效后端、尝试记录和结果保存在本机独立目录；Mock 不伪造 Fluent case/data 或 transcript。", ""]
    return "\n".join(lines)

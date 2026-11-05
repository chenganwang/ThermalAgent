from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Sequence

from .fact_extractor import extract_facts
from .knowledge_synthesizer import synthesize_knowledge_answer
from .no_answer_policy import no_retrieval_answer, weak_evidence_answer
from .source_formatter import clean_preview, hits_to_sources, source_summary

try:
    from services.ingest_service.chunking.pack import strip_packed_meta
except Exception:  # pragma: no cover - defensive fallback for partial installs
    def strip_packed_meta(text: str) -> str:
        return text or ""


def _to_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    try:
        return asdict(value)
    except Exception:
        return {}


def _keywords(query: str) -> list[str]:
    english = re.findall(r"[A-Za-z][A-Za-z0-9_+./-]*", query or "")
    cjk = re.findall(r"[\u4e00-\u9fff]{2,}", query or "")
    out: list[str] = []
    for token in [*english, *cjk]:
        if token not in out:
            out.append(token)
    return out[:10]


def _split_sentences(text: str) -> list[str]:
    cleaned = strip_packed_meta(text or "")
    cleaned = re.sub(r"\[(HIT|CTX)\][^\n]*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    parts = [x.strip() for x in re.split(r"(?<=[。！？!?])\s+|[；;]\s*", cleaned) if x.strip()]
    if not parts and cleaned:
        parts = [cleaned]
    return [clean_preview(part, limit=140) for part in parts if part]


def _evidence_items(query: str, hits: Sequence[Any], max_items: int = 5) -> list[tuple[str, int]]:
    terms = [x.lower() for x in _keywords(query)]
    scored: list[tuple[int, int, str]] = []
    for idx, hit in enumerate(hits, start=1):
        text = getattr(hit, "expanded_text", None) or getattr(hit, "text", "")
        for sentence in _split_sentences(text)[:6]:
            lowered = sentence.lower()
            score = sum(1 for term in terms if term and term in lowered)
            scored.append((score, idx, sentence))
    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    for _score, source_idx, sentence in scored:
        if sentence in seen:
            continue
        seen.add(sentence)
        out.append((sentence, source_idx))
        if len(out) >= max_items:
            break
    return out


def _render_fact_answer(facts_result: Any, sources: Sequence[dict[str, Any]]) -> str | None:
    fact_type = getattr(facts_result, "fact_type", None)
    facts = getattr(facts_result, "facts", {}) or {}
    missing = "未在当前检索证据中核实"
    source_text = source_summary(sources)

    if fact_type == "ashrae_cold_plate_formula_absent":
        return (
            "结论：当前检索到的 ASHRAE thermal guidelines / refcard 内容没有给出冷板内部流道设计公式；"
            "它主要给出数据中心空气冷却等级、液冷等级以及对应的温湿度或供水温度范围。"
            "因此不能据此编造冷板流道设计公式。\n\n"
            f"来源：{source_text}"
        )

    if fact_type == "ashrae_w_class_supply_temperature":
        return (
            "结论：ASHRAE 液冷等级的 facility water supply temperature 对应关系为：\n"
            f"- W17：{facts.get('W17', missing)}\n"
            f"- W27：{facts.get('W27', missing)}\n"
            f"- W32：{facts.get('W32', missing)}\n"
            f"- W40：{facts.get('W40', missing)}\n"
            f"- W45：{facts.get('W45', missing)}\n"
            f"- W+：{facts.get('W+', missing)}\n"
            f"- 证据中的最低供水温度：{facts.get('minimum_water_temperature_all_classes', missing)}\n\n"
            f"来源：{source_text}"
        )

    if fact_type == "ashrae_h1_dry_bulb_temperature":
        return (
            "结论：ASHRAE H1 high-density server 的干球温度范围为：\n"
            f"- Recommended：{facts.get('recommended', missing)}\n"
            f"- Allowable：{facts.get('allowable', missing)}\n\n"
            f"来源：{source_text}"
        )

    if fact_type == "ashrae_a1_a4_allowable_dry_bulb":
        return (
            "结论：ASHRAE A1/A2/A3/A4 的 allowable dry-bulb temperature 范围分别为：\n"
            f"- A1：{facts.get('A1', missing)}\n"
            f"- A2：{facts.get('A2', missing)}\n"
            f"- A3：{facts.get('A3', missing)}\n"
            f"- A4：{facts.get('A4', missing)}\n\n"
            f"来源：{source_text}"
        )

    if fact_type == "ashrae_a1_a4_recommended_dry_bulb":
        return (
            f"结论：ASHRAE A1 到 A4 等级推荐的干球温度范围均为 {facts.get('A1_to_A4_recommended')}。\n\n"
            f"来源：{source_text}"
        )
    return None


def generate_answer(
    query: str,
    task_result: Any,
    retrieved_chunks: Sequence[Any],
    sources: Sequence[dict[str, Any]] | None = None,
) -> str:
    """Generate a structured, extractive RAG answer without requiring an LLM."""

    task = _to_mapping(task_result)
    task_type = str(task.get("task_type") or "general_qa")
    warnings = [str(x) for x in task.get("warnings", []) if x]
    # An explicit empty list means the evidence gate rejected every source.
    # Do not reconstruct those rejected cards from raw retrieval candidates.
    sources = list(hits_to_sources(retrieved_chunks) if sources is None else sources)

    if not retrieved_chunks or not sources:
        return no_retrieval_answer(warnings)

    facts_result = extract_facts(query, retrieved_chunks, sources)
    if facts_result.has_facts:
        fact_answer = _render_fact_answer(facts_result, sources)
        if fact_answer:
            if warnings:
                fact_answer += "\n\n提示：" + "；".join(warnings)
            return fact_answer

    synthesized = synthesize_knowledge_answer(query, task_type, sources, retrieved_chunks)
    if synthesized:
        if warnings:
            synthesized += "\n\n提示：" + "；".join(warnings)
        return synthesized

    evidence = _evidence_items(query, retrieved_chunks, max_items=6)
    if not evidence:
        return weak_evidence_answer()

    def line(index: int, default: int = 0) -> str:
        if index < len(evidence):
            text, source_idx = evidence[index]
        else:
            text, source_idx = evidence[default]
        return f"{text} [{source_idx}]"

    source_text = source_summary(sources)
    if task_type == "concept_explanation":
        answer = (
            "基于当前知识库检索结果，可以这样理解：\n\n"
            f"定义与作用：{line(0)}\n\n"
            f"关键机制：{line(1)}\n\n"
            f"工程关注点：{line(2)}\n\n"
            f"来源依据：{source_text}"
        )
    elif task_type == "mechanism_analysis":
        answer = (
            "基于当前知识库检索结果，机理可以按以下层次梳理：\n\n"
            f"主要现象：{line(0)}\n\n"
            f"传热路径或影响因素：{line(1)}\n\n"
            f"需要结合的约束：{line(2)}\n\n"
            f"来源依据：{source_text}"
        )
    elif task_type == "comparison":
        answer = (
            "基于当前知识库检索结果，可以按对比维度组织回答：\n\n"
            f"维度一：{line(0)}\n\n"
            f"维度二：{line(1)}\n\n"
            f"适用场景：{line(2)}\n\n"
            f"来源依据：{source_text}"
        )
    elif task_type == "troubleshooting":
        answer = (
            "基于当前知识库检索结果，可先按排查思路处理：\n\n"
            f"现象与线索：{line(0)}\n\n"
            f"可能原因：{line(1)}\n\n"
            f"排查路径：先确认热负载、接触界面、冷却介质/风道状态和运行工况，再结合温度、流量、压降或风扇转速等数据定位。参考依据：{line(2)}\n\n"
            f"来源依据：{source_text}"
        )
    elif task_type == "design_advice":
        answer = (
            "基于当前知识库检索结果，设计建议应先从目标和约束展开：\n\n"
            f"设计目标：{line(0)}\n\n"
            f"关键约束：{line(1)}\n\n"
            f"方案风险点：{line(2)}\n\n"
            f"来源依据：{source_text}"
        )
    elif task_type == "literature_lookup":
        items = []
        for src in sources[:5]:
            title = src.get("title") or src.get("book_title") or f"doc_id={src.get('doc_id')}"
            loc = f"p.{src.get('page_start')}-{src.get('page_end')}" if src.get("page_start") and src.get("page_end") else "页码未知"
            items.append(f"- [{src.get('rank')}] {title}：{loc}，chunk_id={src.get('chunk_id')}：{src.get('text_preview')}")
        answer = "当前知识库中相关来源如下：\n\n" + "\n".join(items)
    else:
        answer = (
            "基于当前知识库检索结果，回答如下：\n\n"
            f"{line(0)}\n\n"
            f"补充依据：{line(1)}\n\n"
            f"来源依据：{source_text}"
        )

    if warnings:
        answer += "\n\n提示：" + "；".join(warnings)
    return answer

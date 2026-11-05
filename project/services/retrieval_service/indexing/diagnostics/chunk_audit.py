from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from statistics import mean, median
from typing import Any
import re

import numpy as np


SHORT_CHUNK_THRESHOLD = 120
LONG_CHUNK_THRESHOLD = 2500
NEAR_EMPTY_THRESHOLD = 20


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(text or "").lower())).strip()


def _length_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {key: 0 for key in ("min", "max", "mean", "median", "p25", "p75", "p90", "p95")}
    return {
        "min": min(values),
        "max": max(values),
        "mean": round(mean(values), 2),
        "median": round(median(values), 2),
        "p25": round(float(np.percentile(values, 25)), 2),
        "p75": round(float(np.percentile(values, 75)), 2),
        "p90": round(float(np.percentile(values, 90)), 2),
        "p95": round(float(np.percentile(values, 95)), 2),
    }


def _simhash(text: str) -> int:
    tokens = re.findall(r"[A-Za-z0-9_./+\-=]{2,}|[\u4e00-\u9fff]{2,}", text.lower())
    if not tokens:
        tokens = [text]
    vector = [0] * 64
    for token in tokens:
        value = int.from_bytes(sha256(token.encode("utf-8")).digest()[:8], "big")
        for bit in range(64):
            vector[bit] += 1 if (value >> bit) & 1 else -1
    output = 0
    for bit, score in enumerate(vector):
        if score >= 0:
            output |= 1 << bit
    return output


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _candidate_flags(text: str) -> list[str]:
    stripped = str(text or "").strip()
    lower = stripped.lower()
    flags: list[str] = []
    if len(stripped) < SHORT_CHUNK_THRESHOLD:
        flags.append("extremely_short")
    if len(stripped) > LONG_CHUNK_THRESHOLD:
        flags.append("extremely_long")
    if len(stripped) < NEAR_EMPTY_THRESHOLD:
        flags.append("near_empty")
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if "table of contents" in lower or "contents" == lower or sum(bool(re.match(r"^\d+(?:\.\d+)*\s+", line)) for line in lines) >= 5:
        flags.append("table_of_contents_style")
    if "references" in lower or "bibliography" in lower or (
        len(re.findall(r"\[\d+\]", stripped)) >= 3 and "doi" in lower
    ):
        flags.append("reference_style")
    numeric_lines = sum(bool(re.search(r"\d", line)) for line in lines)
    if len(lines) >= 4 and numeric_lines / len(lines) >= 0.75 and sum(len(line) < 80 for line in lines) / len(lines) >= 0.75:
        flags.append("table_fragment")
    symbol_count = len(re.findall(r"[=±∑∫√<>^]", stripped))
    if symbol_count >= 4 and len(stripped) < 500:
        flags.append("formula_fragment")
    domains = (
        ("thermal", ("thermal", "temperature", "heat", "热", "温度")),
        ("hydraulic", ("pressure", "flow", "pump", "压降", "流量", "泵")),
        ("environment", ("humidity", "dew", "ambient", "湿度", "露点", "环境")),
        ("processor", ("cpu", "processor", "tcase", "junction", "处理器", "芯片")),
    )
    matched_domains = sum(any(term in lower for term in terms) for _, terms in domains)
    if len(stripped) > 1200 and matched_domains >= 3:
        flags.append("multi_topic_mixed")
    return flags


def _domain_terms(catalog: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    terms = (
        "thermal", "temperature", "heat", "cooling", "cold plate", "coolant",
        "pressure", "flow", "pump", "water", "processor", "server", "ambient",
        "热阻", "温度", "液冷", "冷板", "冷却液", "压降", "流量", "泵",
    )
    counter: Counter[str] = Counter()
    for item in catalog.values():
        lower = str(item.get("text") or "").lower()
        for term in terms:
            count = lower.count(term)
            if count:
                counter[term] += count
    return [{"term": term, "count": count} for term, count in counter.most_common(30)]


def audit_chunk_quality(
    catalog: dict[int, dict[str, Any]],
    *,
    old_chunk_ids: set[int],
) -> dict[str, Any]:
    ordered = [dict(catalog[key]) for key in sorted(catalog)]
    lengths = [len(str(item.get("text") or "")) for item in ordered]
    normalized_by_id = {
        int(item["chunk_id"]): _normalized(str(item.get("text") or "")) for item in ordered
    }
    exact_groups: dict[str, list[int]] = defaultdict(list)
    for chunk_id, text in normalized_by_id.items():
        if text:
            exact_groups[sha256(text.encode("utf-8")).hexdigest()].append(chunk_id)
    duplicate_groups = [ids for ids in exact_groups.values() if len(ids) > 1]

    near_duplicates: list[dict[str, Any]] = []
    hashes = {chunk_id: _simhash(text) for chunk_id, text in normalized_by_id.items() if text}
    ids = sorted(hashes)
    exact_pairs = {
        tuple(sorted((left, right)))
        for group in duplicate_groups
        for index, left in enumerate(group)
        for right in group[index + 1 :]
    }
    for index, left in enumerate(ids):
        left_text = normalized_by_id[left]
        for right in ids[index + 1 :]:
            if (left, right) in exact_pairs:
                continue
            right_text = normalized_by_id[right]
            if min(len(left_text), len(right_text)) / max(len(left_text), len(right_text)) < 0.8:
                continue
            distance = _hamming(hashes[left], hashes[right])
            if distance <= 3:
                near_duplicates.append(
                    {"chunk_ids": [left, right], "simhash_distance": distance, "assessment_type": "heuristic_candidate"}
                )

    repeated_lines: dict[str, set[int]] = defaultdict(set)
    for item in ordered:
        chunk_id = int(item["chunk_id"])
        lines = [line.strip() for line in str(item.get("text") or "").splitlines() if 5 <= len(line.strip()) <= 160]
        for line in set(lines[:3] + lines[-3:]):
            repeated_lines[_normalized(line)].add(chunk_id)
    repeated_header_chunks = {
        chunk_id
        for line, chunk_ids in repeated_lines.items()
        if line and len(chunk_ids) >= 3
        for chunk_id in chunk_ids
    }

    flags_by_id: dict[int, list[str]] = {}
    for item in ordered:
        chunk_id = int(item["chunk_id"])
        flags = _candidate_flags(str(item.get("text") or ""))
        if chunk_id in repeated_header_chunks:
            flags.append("repeated_header_footer")
        if not item.get("document_id") or not item.get("source_name"):
            flags.append("missing_document_or_source_mapping")
        if any(chunk_id in group for group in duplicate_groups):
            flags.append("exact_duplicate")
        if any(chunk_id in pair["chunk_ids"] for pair in near_duplicates):
            flags.append("near_duplicate")
        flags_by_id[chunk_id] = sorted(set(flags))

    candidates = [
        {
            "chunk_id": int(item["chunk_id"]),
            "document_id": item.get("document_id"),
            "source_name": item.get("source_name"),
            "content_length": len(str(item.get("text") or "")),
            "heuristic_flags": flags_by_id[int(item["chunk_id"])],
            "preview": " ".join(str(item.get("text") or "").split())[:240],
            "assessment_type": "heuristic_candidate",
            "human_validated": False,
        }
        for item in ordered
        if flags_by_id[int(item["chunk_id"])]
    ]
    same_document_groups = 0
    cross_document_groups = 0
    for group in duplicate_groups:
        documents = {catalog[chunk_id].get("document_id") for chunk_id in group}
        if any(
            sum(catalog[chunk_id].get("document_id") == document for chunk_id in group) > 1
            for document in documents
        ):
            same_document_groups += 1
        if len(documents) > 1:
            cross_document_groups += 1

    old_lengths = [
        len(str(item.get("text") or "")) for item in ordered if int(item["chunk_id"]) in old_chunk_ids
    ]
    new_lengths = [
        len(str(item.get("text") or "")) for item in ordered if int(item["chunk_id"]) not in old_chunk_ids
    ]
    return {
        "chunk_count": len(ordered),
        "length_distribution": _length_stats(lengths),
        "extremely_short_count": sum(length < SHORT_CHUNK_THRESHOLD for length in lengths),
        "extremely_long_count": sum(length > LONG_CHUNK_THRESHOLD for length in lengths),
        "near_empty_count": sum(length < NEAR_EMPTY_THRESHOLD for length in lengths),
        "exact_duplicate_group_count": len(duplicate_groups),
        "same_document_duplicate_group_count": same_document_groups,
        "cross_document_duplicate_group_count": cross_document_groups,
        "near_duplicate_candidate_count": len(near_duplicates),
        "repeated_header_footer_candidate_count": len(repeated_header_chunks),
        "table_of_contents_candidate_count": sum("table_of_contents_style" in flags for flags in flags_by_id.values()),
        "reference_candidate_count": sum("reference_style" in flags for flags in flags_by_id.values()),
        "table_fragment_candidate_count": sum("table_fragment" in flags for flags in flags_by_id.values()),
        "formula_fragment_candidate_count": sum("formula_fragment" in flags for flags in flags_by_id.values()),
        "multi_topic_candidate_count": sum("multi_topic_mixed" in flags for flags in flags_by_id.values()),
        "missing_mapping_count": sum("missing_document_or_source_mapping" in flags for flags in flags_by_id.values()),
        "heuristic_candidate_count": len(candidates),
        "duplicate_groups": duplicate_groups,
        "near_duplicate_candidates": near_duplicates,
        "frequent_domain_terms": _domain_terms(catalog),
        "old_vs_new": {
            "old": {"count": len(old_lengths), "length_distribution": _length_stats(old_lengths)},
            "new": {"count": len(new_lengths), "length_distribution": _length_stats(new_lengths)},
        },
        "chunk_flags": {str(key): value for key, value in flags_by_id.items() if value},
        "candidates": candidates,
        "assessment_type": "heuristic_read_only_audit",
        "human_validated": False,
        "database_written": False,
        "chunks_modified": False,
    }

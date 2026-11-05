from __future__ import annotations

from typing import Iterable


# Terms that are meaningful engineering signals and must survive filtering.
ENGINEERING_KEEP_TERMS = {
    "cdu",
    "coolant",
    "cooling_liquid",
    "cold_plate",
    "contact_thermal_resistance",
    "flow_rate",
    "heat_resistance",
    "inlet_temperature",
    "outlet_temperature",
    "pressure_drop",
    "thermal_resistance",
    "temperature_rise",
    "tim",
    "冷却液",
    "冷板",
    "出口温度",
    "压降",
    "堵塞",
    "入口温度",
    "接触热阻",
    "故障",
    "泵",
    "流量",
    "温升",
    "热阻",
}


# Generic words that should not drive shadow retrieval scoring.
ENGLISH_STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "also",
    "am",
    "an",
    "and",
    "any",
    "are",
    "around",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "between",
    "both",
    "but",
    "by",
    "can",
    "case",
    "compare",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "down",
    "during",
    "each",
    "evidence",
    "explain",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "knowledge",
    "loop",
    "may",
    "more",
    "most",
    "need",
    "no",
    "nor",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "per",
    "possible",
    "question",
    "related",
    "risk",
    "role",
    "same",
    "should",
    "so",
    "source",
    "such",
    "system",
    "than",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "why",
    "with",
    "within",
    "would",
}


CHINESE_STOPWORDS = {
    "一些",
    "什么",
    "介绍",
    "以上",
    "以及",
    "但是",
    "作用",
    "关系",
    "其",
    "其中",
    "分析",
    "判断",
    "原因",
    "可能",
    "可以",
    "哪些",
    "因此",
    "如何",
    "如果",
    "它",
    "对于",
    "导致",
    "情况",
    "或者",
    "所以",
    "是否",
    "有什么",
    "有关",
    "来源",
    "比较",
    "的",
    "相关",
    "知识",
    "系统",
    "给出",
    "能否",
    "说明",
    "这个",
    "这些",
    "这种",
    "造成",
    "通常",
    "通过",
    "那些",
    "需要",
    "问题",
    "因素",
    "影响",
    "怎么",
    "怎样",
    "为什么",
}


LOW_VALUE_MATCH_TERMS = ENGLISH_STOPWORDS | CHINESE_STOPWORDS | {
    "architecture",
    "cooling",
    "liquid",
    "liquid_cooling",
    "pack",
}


def normalize_stopword_term(term: str) -> str:
    return str(term or "").strip().lower().replace(" ", "_")


def is_stopword(term: str) -> bool:
    item = normalize_stopword_term(term)
    if not item:
        return True
    if item in ENGINEERING_KEEP_TERMS:
        return False
    return item in LOW_VALUE_MATCH_TERMS


def filter_stopwords(terms: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        item = normalize_stopword_term(str(term or ""))
        if not item or item in seen or is_stopword(item):
            continue
        seen.add(item)
        out.append(item)
    return out


__all__ = [
    "CHINESE_STOPWORDS",
    "ENGINEERING_KEEP_TERMS",
    "ENGLISH_STOPWORDS",
    "LOW_VALUE_MATCH_TERMS",
    "filter_stopwords",
    "is_stopword",
    "normalize_stopword_term",
]

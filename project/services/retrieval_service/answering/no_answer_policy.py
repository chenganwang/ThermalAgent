from __future__ import annotations


def no_retrieval_answer(warnings: list[str] | None = None) -> str:
    base = "当前知识库中没有检索到足够依据，无法给出有来源支撑的完整回答。"
    if warnings:
        base += "\n\n提示：" + "；".join(warnings)
    return base


def weak_evidence_answer() -> str:
    return "当前知识库中检索到了一些结果，但可用于组织答案的文本依据不足。请查看 sources 字段中的来源片段。"


def no_source_for_requested_fact_answer() -> str:
    return "当前知识库中没有检索到足够依据，不能根据常识或未命中的资料编造答案。"

from __future__ import annotations

from services.retrieval_service.config import AppConfig
from .types import ChunkContext


def build_chunk_context(cfg: AppConfig) -> ChunkContext:
    c = cfg.chunking
    q = cfg.qc
    return ChunkContext(
        text_chunk_chars=c.text_chunk_chars,
        text_overlap_chars=c.text_overlap_chars,
        text_hard_max_chars=c.text_hard_max_chars,
        use_token_budget=c.use_token_budget,
        heading_as_chunk=c.heading_as_chunk,
        heading_max_chars=c.heading_max_chars,
        merge_text_across_pages=c.merge_text_across_pages,
        semantic_split_enable=c.semantic_split_enable,
        semantic_model_name=c.semantic_model_name,
        semantic_window_size=c.semantic_window_size,
        semantic_breakpoint_percentile=c.semantic_breakpoint_percentile,
        semantic_min_distance=c.semantic_min_distance,
        semantic_trigger_chars=c.semantic_trigger_chars,
        semantic_min_chunk_chars=c.semantic_min_chunk_chars,
        semantic_min_part_chars=c.semantic_min_part_chars,
        table_target_chars=c.table_target_chars,
        table_hard_max_chars=c.table_hard_max_chars,
        table_min_chars=c.table_min_chars,
        include_table_summary=c.include_table_summary,
        key_columns_if_many=c.key_columns_if_many,
        table_cols_per_slice=c.table_cols_per_slice,
        table_row_overlap=c.table_row_overlap,
        prev_text_tail_chars=c.prev_text_tail_chars,
        figure_anchor_chars=c.figure_anchor_chars,
        text_min_emit_chars=c.text_min_emit_chars,
        table_min_emit_chars=c.table_min_emit_chars,
        enable_qc=q.enable_qc,
        qc_min_chars=q.qc_min_chars,
        qc_max_symbol_ratio=q.qc_max_symbol_ratio,
        qc_merge_below_chars=q.qc_merge_below_chars,
        qc_max_adjacent_hamming=q.qc_max_adjacent_hamming,
        qc_text_min_chars=q.qc_text_min_chars,
        qc_table_min_chars=q.qc_table_min_chars,
        qc_figure_min_chars=q.qc_figure_min_chars,
        qc_drop_page_artifacts=q.qc_drop_page_artifacts,
        qc_text_max_symbol_ratio=q.qc_text_max_symbol_ratio,
        qc_table_max_symbol_ratio=q.qc_table_max_symbol_ratio,
        qc_figure_max_symbol_ratio=q.qc_figure_max_symbol_ratio,
    )

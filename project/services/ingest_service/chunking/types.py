from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal

BlockType = Literal["text", "table", "figure"]
ChunkType = Literal["text", "table", "table_summary", "figure"]


@dataclass
class Block:
    page: int
    type: BlockType
    order: int
    text: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    page_start: int
    page_end: int
    type: ChunkType
    text: str
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkContext:
    text_chunk_chars: int = 1100
    text_overlap_chars: int = 60
    text_hard_max_chars: int = 1400
    use_token_budget: bool = False
    heading_as_chunk: bool = False
    heading_max_chars: int = 80
    merge_text_across_pages: bool = False

    semantic_split_enable: bool = True
    semantic_model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    semantic_window_size: int = 1
    semantic_breakpoint_percentile: float = 85.0
    semantic_min_distance: float = 0.18
    semantic_trigger_chars: int = 320
    semantic_min_chunk_chars: int = 240
    semantic_min_part_chars: int = 12

    table_target_chars: int = 900
    table_hard_max_chars: int = 1400
    table_min_chars: int = 320
    include_table_summary: bool = False
    key_columns_if_many: bool = True
    table_cols_per_slice: int = 6
    table_row_overlap: int = 0

    prev_text_tail_chars: int = 240
    figure_anchor_chars: int = 120
    text_min_emit_chars: int = 220
    table_min_emit_chars: int = 260

    enable_qc: bool = True
    qc_min_chars: int = 40
    qc_max_symbol_ratio: float = 0.75
    qc_merge_below_chars: int = 160
    qc_max_adjacent_hamming: int = 2

    qc_text_min_chars: int = 80
    qc_table_min_chars: int = 140
    qc_figure_min_chars: int = 20
    qc_drop_page_artifacts: bool = True

    qc_text_max_symbol_ratio: float = 0.75
    qc_table_max_symbol_ratio: float = 0.90
    qc_figure_max_symbol_ratio: float = 0.90

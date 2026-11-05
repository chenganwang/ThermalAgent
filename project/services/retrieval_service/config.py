from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
import re


@dataclass(frozen=True)
class Paths:
    project_root: Path
    data_dir: Path
    faiss_dir: Path
    faiss_index_path: Path
    faiss_meta_path: Path
    bm25_dir: Path
    bm25_corpus_path: Path
    bm25_meta_path: Path


@dataclass(frozen=True)
class MySQLConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class EmbeddingConfig:
    model_name: str
    normalize: bool = True


@dataclass(frozen=True)
class OCRConfig:
    tesseract_cmd: str | None = None
    tessdata_dir: str | None = None
    lang: str = "chi_sim+eng"
    prefer_text_layer: bool = True
    text_layer_min_chars: int = 80
    render_dpi: int = 300


@dataclass(frozen=True)
class ChunkingConfig:
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



@dataclass(frozen=True)
class QCConfig:
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


@dataclass(frozen=True)
class BM25Config:
    enabled: bool = True
    topn: int = 30
    k1: float = 1.5
    b: float = 0.75



@dataclass(frozen=True)
class RetrievalConfig:
    topk_default: int = 5
    neighbor_window: int = 1
    faiss_topn_base: int = 50
    faiss_topn_multiplier: int = 10
    vector_weight: float = 0.55
    bm25_weight: float = 0.35
    lexical_weight: float = 0.10

    pre_retrieval_enable: bool = True
    query_rewrite_enable: bool = True
    keyword_expansion_enable: bool = True
    subquery_enable: bool = True
    max_rewrite_queries: int = 2
    max_keyword_queries: int = 2
    max_sub_queries: int = 2
    preferred_chunk_type_boost: float = 0.08
    multi_route_hit_boost: float = 0.03
    exact_reference_enable: bool = True
    exact_reference_limit: int = 24
    exact_reference_boost: float = 0.22
    warmup_on_startup: bool = False


@dataclass(frozen=True)
class PDFCleanupConfig:
    drop_first_pages: int = 0
    front_matter_scan_pages: int = 18
    front_matter_min_marker_hits: int = 2
    toc_page_min_dotted: int = 8
    toc_para_min_dotted: int = 3
    drop_flagged_toc_para: bool = True
    drop_flagged_garbled_para: bool = True
    garbled_ratio: float = 0.33
    garbled_min_bad_chars: int = 6
    enable_block_type_detection: bool = True
    table_min_lines: int = 3
    table_min_cols: int = 2
    repeated_header_top_n: int = 2
    repeated_footer_bottom_n: int = 2
    repeated_header_footer_min_frac: float = 0.3
    high_freq_line_min_frac: float = 0.12
    high_freq_line_min_len: int = 6
    para_dedup_min_norm_len: int = 70
    para_dedup_max_repeat: int = 1
    formula_symbol_ratio: float = 0.55
    formula_min_ops: int = 2


@dataclass(frozen=True)
class RebuildConfig:
    batch_size: int = 128


@dataclass(frozen=True)
class AppConfig:
    paths: Paths
    mysql: MySQLConfig
    embedding: EmbeddingConfig
    ocr: OCRConfig
    chunking: ChunkingConfig
    qc: QCConfig
    bm25: BM25Config
    retrieval: RetrievalConfig
    pdf_cleanup: PDFCleanupConfig
    rebuild: RebuildConfig


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw not in ("0", "false", "False", "no", "NO")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw is not None else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw is not None else default


def _load_dotenv(path: Path) -> None:
    """Load a local .env file without printing or overriding shell env values."""

    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except Exception:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        if key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def _env_path(name: str, default: Path, *, base: Path | None = None) -> Path:
    raw = os.getenv(name)
    if not raw:
        return default
    path = Path(raw)
    if not path.is_absolute() and base is not None:
        return base / path
    return path


def load_config(project_root: Path | None = None) -> AppConfig:
    root = project_root or Path(__file__).resolve().parents[2]
    _load_dotenv(root / ".env")

    index_dir = _env_path("INDEX_DIR", root / "indexes", base=root)
    data_dir = _env_path("RAG_DATA_DIR", root / "data", base=root)
    faiss_index_path = _env_path("FAISS_INDEX_PATH", index_dir / "faiss.index", base=root)
    bm25_corpus_path = _env_path("BM25_INDEX_PATH", index_dir / "bm25.pkl", base=root)
    faiss_dir = faiss_index_path.parent if os.getenv("FAISS_INDEX_PATH") else _env_path("FAISS_DIR", faiss_index_path.parent, base=root)
    bm25_dir = bm25_corpus_path.parent if os.getenv("BM25_INDEX_PATH") else _env_path("BM25_DIR", bm25_corpus_path.parent, base=root)

    paths = Paths(
        project_root=root,
        data_dir=data_dir,
        faiss_dir=faiss_dir,
        faiss_index_path=faiss_index_path,
        faiss_meta_path=faiss_index_path.with_suffix(faiss_index_path.suffix + ".meta.json"),
        bm25_dir=bm25_dir,
        bm25_corpus_path=bm25_corpus_path,
        bm25_meta_path=bm25_corpus_path.with_suffix(bm25_corpus_path.suffix + ".meta.json"),
    )

    mysql = MySQLConfig(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3307")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DB", "rag_agent"),
    )

    default_model = os.getenv(
        "EMBED_MODEL",
        os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
    )
    embedding = EmbeddingConfig(
        model_name=default_model,
        normalize=_env_bool("EMBED_NORMALIZE", True),
    )

    ocr = OCRConfig(
        tesseract_cmd=os.getenv("TESSERACT_CMD"),
        tessdata_dir=os.getenv("TESSDATA_PREFIX"),
        lang=os.getenv("TESS_LANG", "chi_sim+eng"),
        prefer_text_layer=_env_bool("PDF_PREFER_TEXT_LAYER", True),
        text_layer_min_chars=_env_int("PDF_TEXT_LAYER_MIN_CHARS", 80),
        render_dpi=_env_int("PDF_RENDER_DPI", 300),
    )

    chunking = ChunkingConfig(
        text_chunk_chars=_env_int("CHUNK_TEXT_CHARS", 1100),
        text_overlap_chars=_env_int("CHUNK_TEXT_OVERLAP", 60),
        text_hard_max_chars=_env_int("CHUNK_TEXT_HARD_MAX_CHARS", 1400),
        use_token_budget=_env_bool("CHUNK_USE_TOKEN_BUDGET", False),
        heading_as_chunk=_env_bool("CHUNK_HEADING_AS_CHUNK", False),
        heading_max_chars=_env_int("CHUNK_HEADING_MAX_CHARS", 80),
        merge_text_across_pages=_env_bool("CHUNK_MERGE_TEXT_ACROSS_PAGES", False),
        semantic_split_enable=_env_bool("CHUNK_SEMANTIC_ENABLE", True),
        semantic_model_name=os.getenv("CHUNK_SEMANTIC_MODEL", default_model),
        semantic_window_size=_env_int("CHUNK_SEMANTIC_WINDOW_SIZE", 1),
        semantic_breakpoint_percentile=_env_float("CHUNK_SEMANTIC_BREAKPOINT_PERCENTILE", 85.0),
        semantic_min_distance=_env_float("CHUNK_SEMANTIC_MIN_DISTANCE", 0.18),
        semantic_trigger_chars=_env_int("CHUNK_SEMANTIC_TRIGGER_CHARS", 320),
        semantic_min_chunk_chars=_env_int("CHUNK_SEMANTIC_MIN_CHUNK_CHARS", 240),
        semantic_min_part_chars=_env_int("CHUNK_SEMANTIC_MIN_PART_CHARS", 12),
        table_target_chars=_env_int("CHUNK_TABLE_TARGET_CHARS", 900),
        table_hard_max_chars=_env_int("CHUNK_TABLE_HARD_MAX_CHARS", 1400),
        table_min_chars=_env_int("CHUNK_TABLE_MIN_CHARS", 320),
        include_table_summary=_env_bool("CHUNK_INCLUDE_TABLE_SUMMARY", False),
        key_columns_if_many=_env_bool("CHUNK_KEY_COLUMNS_IF_MANY", True),
        table_cols_per_slice=_env_int("CHUNK_TABLE_COLS_PER_SLICE", 6),
        table_row_overlap=_env_int("CHUNK_TABLE_ROW_OVERLAP", 0),
        prev_text_tail_chars=_env_int("CHUNK_PREV_TEXT_TAIL_CHARS", 240),
        figure_anchor_chars=_env_int("CHUNK_FIGURE_ANCHOR_CHARS", 120),
        text_min_emit_chars=_env_int("CHUNK_TEXT_MIN_EMIT_CHARS", 220),
        table_min_emit_chars=_env_int("CHUNK_TABLE_MIN_EMIT_CHARS", 260),
    )

    qc = QCConfig(
        enable_qc=_env_bool("QC_ENABLE", True),
        qc_min_chars=_env_int("QC_MIN_CHARS", 40),
        qc_max_symbol_ratio=_env_float("QC_MAX_SYMBOL_RATIO", 0.75),
        qc_merge_below_chars=_env_int("QC_MERGE_BELOW_CHARS", 160),
        qc_max_adjacent_hamming=_env_int("QC_MAX_ADJ_HAMMING", 2),
        qc_text_min_chars=_env_int("QC_TEXT_MIN_CHARS", 80),
        qc_table_min_chars=_env_int("QC_TABLE_MIN_CHARS", 140),
        qc_figure_min_chars=_env_int("QC_FIGURE_MIN_CHARS", 20),
        qc_drop_page_artifacts=_env_bool("QC_DROP_PAGE_ARTIFACTS", True),
        qc_text_max_symbol_ratio=_env_float("QC_TEXT_MAX_SYMBOL_RATIO", 0.75),
        qc_table_max_symbol_ratio=_env_float("QC_TABLE_MAX_SYMBOL_RATIO", 0.90),
        qc_figure_max_symbol_ratio=_env_float("QC_FIGURE_MAX_SYMBOL_RATIO", 0.90),
    )

    bm25 = BM25Config(
        enabled=_env_bool("BM25_ENABLE", True),
        topn=_env_int("BM25_TOPN", 30),
        k1=_env_float("BM25_K1", 1.5),
        b=_env_float("BM25_B", 0.75),
    )


    retrieval = RetrievalConfig(
        topk_default=_env_int("RETRIEVAL_TOPK_DEFAULT", 5),
        neighbor_window=_env_int("RETRIEVAL_NEIGHBOR_WINDOW", 1),
        faiss_topn_base=_env_int("RETRIEVAL_FAISS_TOPN_BASE", 50),
        faiss_topn_multiplier=_env_int("RETRIEVAL_FAISS_TOPN_MULTIPLIER", 10),
        vector_weight=_env_float("RETRIEVAL_VECTOR_WEIGHT", 0.55),
        bm25_weight=_env_float("RETRIEVAL_BM25_WEIGHT", 0.35),
        lexical_weight=_env_float("RETRIEVAL_LEXICAL_WEIGHT", 0.10),
        pre_retrieval_enable=_env_bool("RETRIEVAL_PRE_RETRIEVAL_ENABLE", True),
        query_rewrite_enable=_env_bool("RETRIEVAL_QUERY_REWRITE_ENABLE", True),
        keyword_expansion_enable=_env_bool("RETRIEVAL_KEYWORD_EXPANSION_ENABLE", True),
        subquery_enable=_env_bool("RETRIEVAL_SUBQUERY_ENABLE", True),
        max_rewrite_queries=_env_int("RETRIEVAL_MAX_REWRITE_QUERIES", 2),
        max_keyword_queries=_env_int("RETRIEVAL_MAX_KEYWORD_QUERIES", 2),
        max_sub_queries=_env_int("RETRIEVAL_MAX_SUB_QUERIES", 2),
        preferred_chunk_type_boost=_env_float("RETRIEVAL_PREFERRED_CHUNK_TYPE_BOOST", 0.08),
        multi_route_hit_boost=_env_float("RETRIEVAL_MULTI_ROUTE_HIT_BOOST", 0.03),
        exact_reference_enable=_env_bool("RETRIEVAL_EXACT_REFERENCE_ENABLE", True),
        exact_reference_limit=_env_int("RETRIEVAL_EXACT_REFERENCE_LIMIT", 24),
        exact_reference_boost=_env_float("RETRIEVAL_EXACT_REFERENCE_BOOST", 0.22),
        warmup_on_startup=_env_bool("RETRIEVAL_WARMUP_ON_STARTUP", False),
    )

    pdf_cleanup = PDFCleanupConfig(
        drop_first_pages=_env_int("PDF_DROP_FIRST_PAGES", 0),
        front_matter_scan_pages=_env_int("PDF_FRONT_MATTER_SCAN_PAGES", 18),
        front_matter_min_marker_hits=_env_int("PDF_FRONT_MATTER_MIN_MARKER_HITS", 2),
        toc_page_min_dotted=_env_int("PDF_TOC_PAGE_MIN_DOTTED", 8),
        toc_para_min_dotted=_env_int("PDF_TOC_PARA_MIN_DOTTED", 3),
        drop_flagged_toc_para=_env_bool("PDF_DROP_FLAGGED_TOC_PARA", True),
        drop_flagged_garbled_para=_env_bool("PDF_DROP_FLAGGED_GARBLED_PARA", True),
        garbled_ratio=_env_float("PDF_GARBLED_RATIO", 0.33),
        garbled_min_bad_chars=_env_int("PDF_GARBLED_MIN_BAD_CHARS", 6),
        enable_block_type_detection=_env_bool("PDF_ENABLE_BLOCK_TYPE_DETECTION", True),
        table_min_lines=_env_int("PDF_TABLE_MIN_LINES", 3),
        table_min_cols=_env_int("PDF_TABLE_MIN_COLS", 2),
        repeated_header_top_n=_env_int("PDF_REPEATED_HEADER_TOP_N", 2),
        repeated_footer_bottom_n=_env_int("PDF_REPEATED_FOOTER_BOTTOM_N", 2),
        repeated_header_footer_min_frac=_env_float("PDF_REPEATED_HEADER_FOOTER_MIN_FRAC", 0.3),
        high_freq_line_min_frac=_env_float("PDF_HIGH_FREQ_LINE_MIN_FRAC", 0.12),
        high_freq_line_min_len=_env_int("PDF_HIGH_FREQ_LINE_MIN_LEN", 6),
        para_dedup_min_norm_len=_env_int("PDF_PARA_DEDUP_MIN_NORM_LEN", 70),
        para_dedup_max_repeat=_env_int("PDF_PARA_DEDUP_MAX_REPEAT", 1),
        formula_symbol_ratio=_env_float("PDF_FORMULA_SYMBOL_RATIO", 0.55),
        formula_min_ops=_env_int("PDF_FORMULA_MIN_OPS", 2),
    )

    rebuild = RebuildConfig(batch_size=_env_int("REBUILD_BATCH_SIZE", 128))

    return AppConfig(
        paths=paths,
        mysql=mysql,
        embedding=embedding,
        ocr=ocr,
        chunking=chunking,
        qc=qc,
        bm25=bm25,
        retrieval=retrieval,
        pdf_cleanup=pdf_cleanup,
        rebuild=rebuild,
    )

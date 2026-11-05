from __future__ import annotations

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class ChunkInsertRow:
    chunk_index: int
    page_start: int | None
    page_end: int | None
    chunk_type: str
    text: str
    char_len: int
    token_len: int | None = None
    section_path: str | None = None
    content_hash: str | None = None
    quality_score: float | None = None
    meta_json: dict | list | str | None = None
    is_active: int = 1

    def meta_json_text(self) -> str | None:
        if self.meta_json is None:
            return None
        if isinstance(self.meta_json, str):
            return self.meta_json
        return json.dumps(self.meta_json, ensure_ascii=False)

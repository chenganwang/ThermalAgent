from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..types import Block, Chunk, ChunkContext


class ChunkStrategy(ABC):
    @abstractmethod
    def supports(self, block: Block) -> bool:
        ...

    @abstractmethod
    def chunk(self, block: Block, ctx: ChunkContext) -> List[Chunk]:
        ...

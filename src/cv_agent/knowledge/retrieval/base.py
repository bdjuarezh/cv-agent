from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: str
    text: str
    score: float


class Retriever(Protocol):
    async def search(self, query: str, k: int = 5) -> list[Chunk]: ...

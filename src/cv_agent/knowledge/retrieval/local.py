"""BM25 (`bm25s`) + denso (Vertex, opcional) + RRF + MMR sobre numpy — sin base vectorial.

Con n~200 chunks la búsqueda exacta es un matvec de microsegundos (01_ARQUITECTURA.md §2); una
base vectorial gestionada solo añadiría latencia de red y una dependencia externa. Construido una
sola vez en el lifespan (CLAUDE.md regla 3), nunca por request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import bm25s  # type: ignore[import-untyped]
import numpy as np
import structlog
from starlette.concurrency import run_in_threadpool

from cv_agent.knowledge.chunking import RawChunk, chunk_narrative
from cv_agent.knowledge.retrieval.base import Chunk
from cv_agent.providers.embeddings import VertexEmbeddings

log = structlog.get_logger()

RRF_K = 60
MMR_LAMBDA = 0.7
_CANDIDATE_POOL = 30  # cuántos candidatos de cada ranking se fusionan antes de MMR


def _rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


def _mmr(query_vec: np.ndarray, embeddings: np.ndarray, candidates: list[int], k: int) -> list[int]:
    """Con filas L2-normalizadas, `embeddings @ query_vec` es coseno (07_SCRIPTS_Y_CONFIG.md §E.5)."""
    sims = embeddings @ query_vec
    pool = list(candidates)
    selected: list[int] = []
    while len(selected) < k and pool:
        if not selected:
            redundancy = np.zeros(len(pool))
        else:
            redundancy = (embeddings[pool] @ embeddings[selected].T).max(axis=1)
        scores = MMR_LAMBDA * sims[pool] - (1 - MMR_LAMBDA) * redundancy
        best = int(np.argmax(scores))
        selected.append(pool.pop(best))
    return selected


class LocalRetriever:
    def __init__(
        self,
        chunks: list[RawChunk],
        embeddings: np.ndarray | None,
        embedder: VertexEmbeddings | None,
    ) -> None:
        self._chunks = chunks
        self._embeddings = embeddings  # (n, d) L2-normalizado, o None sin Vertex
        self._embedder = embedder
        self._bm25: bm25s.BM25 | None = None
        self.has_dense_index = embeddings is not None and embedder is not None
        if chunks:
            corpus_tokens = bm25s.tokenize(
                [c.text for c in chunks], stopwords=None, show_progress=False
            )
            self._bm25 = bm25s.BM25()
            self._bm25.index(corpus_tokens, show_progress=False)

    async def search(self, query: str, k: int = 5) -> list[Chunk]:
        if not self._chunks or self._bm25 is None:
            return []

        bm25_ranking = self._bm25_rank(query)

        if self._embeddings is None or self._embedder is None:
            selected = bm25_ranking[:k]
        else:
            query_vec = await run_in_threadpool(self._embedder.embed_query, query)
            dense_ranking = self._dense_rank(query_vec)
            fused = _rrf([bm25_ranking, dense_ranking])
            candidates = sorted(fused, key=lambda i: fused[i], reverse=True)[:_CANDIDATE_POOL]
            selected = _mmr(query_vec, self._embeddings, candidates, k)

        return [
            Chunk(
                chunk_id=self._chunks[i].chunk_id,
                source=self._chunks[i].source,
                text=self._chunks[i].text,
                score=0.0,
            )
            for i in selected
        ]

    def _bm25_rank(self, query: str) -> list[int]:
        assert self._bm25 is not None
        n = min(_CANDIDATE_POOL, len(self._chunks))
        query_tokens = bm25s.tokenize([query], stopwords=None, show_progress=False)
        results, _ = self._bm25.retrieve(query_tokens, k=n, show_progress=False)
        return [int(i) for i in results[0]]

    def _dense_rank(self, query_vec: np.ndarray) -> list[int]:
        assert self._embeddings is not None
        sims = self._embeddings @ query_vec
        n = min(_CANDIDATE_POOL, len(self._chunks))
        return [int(i) for i in np.argsort(-sims)[:n]]


def _load_precomputed_embeddings(data_dir: Path, chunks: list[RawChunk]) -> np.ndarray | None:
    emb_path, chunks_path = data_dir / "embeddings.npy", data_dir / "chunks.json"
    if not emb_path.exists() or not chunks_path.exists():
        return None
    cached = json.loads(chunks_path.read_text(encoding="utf-8"))
    if [c["chunk_id"] for c in cached] != [c.chunk_id for c in chunks]:
        log.warning(
            "embeddings_stale",
            reason="data/chunks.json no coincide con narrative/*.md actual — corre `make kb`",
        )
        return None
    return cast(np.ndarray, np.load(emb_path))


def build_local_retriever(data_dir: Path, embedder: VertexEmbeddings | None) -> LocalRetriever:
    chunks = chunk_narrative(data_dir / "narrative")
    embeddings = _load_precomputed_embeddings(data_dir, chunks)
    return LocalRetriever(chunks, embeddings, embedder)

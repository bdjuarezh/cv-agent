"""Vertex Embeddings API (`text-multilingual-embedding-002`, D6) — no `sentence-transformers`
local, sin `torch` en la imagen. `task_type` distingue query de passage (la forma correcta en
Vertex; no son los prefijos de texto `query:`/`passage:` de `multilingual-e5-small`, que era la
versión local descartada)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, cast

import numpy as np
import structlog
import vertexai
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

log = structlog.get_logger()

TaskType = Literal["RETRIEVAL_QUERY", "RETRIEVAL_DOCUMENT"]


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return cast(np.ndarray, vectors / norms)


class VertexEmbeddings:
    def __init__(self, *, project: str, region: str, model: str) -> None:
        vertexai.init(project=project, location=region)
        self._model = TextEmbeddingModel.from_pretrained(model)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, query: str) -> np.ndarray:
        cached = self._embed_query_cached(query)
        return np.array(cached, dtype=np.float32)

    @lru_cache(maxsize=256)  # noqa: B019 — instancia única de por vida del proceso, vía lifespan
    def _embed_query_cached(self, query: str) -> tuple[float, ...]:
        vec = self._embed([query], "RETRIEVAL_QUERY")[0]
        return tuple(float(x) for x in vec)

    def _embed(self, texts: list[str], task_type: TaskType) -> np.ndarray:
        inputs: list[str | TextEmbeddingInput] = [
            TextEmbeddingInput(text=t, task_type=task_type) for t in texts
        ]
        embeddings = self._model.get_embeddings(inputs)
        vectors = np.array([e.values for e in embeddings], dtype=np.float32)
        return _normalize(vectors)


def build_embeddings(*, project: str, region: str, model: str) -> VertexEmbeddings | None:
    """`None` si Vertex no está configurado — igual que `providers/vertex_anthropic.py`. El
    retriever cae a BM25 solo (`knowledge/retrieval/local.py`), nunca revienta por esto."""
    if not project:
        log.warning("embeddings_not_configured", reason="GCP_PROJECT vacío")
        return None
    try:
        return VertexEmbeddings(project=project, region=region, model=model)
    except Exception:
        log.exception("embeddings_init_failed")
        return None

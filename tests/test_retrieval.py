import json
import time
from pathlib import Path

import numpy as np

from cv_agent.knowledge.chunking import RawChunk
from cv_agent.knowledge.retrieval.local import LocalRetriever, build_local_retriever


class _FakeEmbedder:
    def __init__(self, query_vector: np.ndarray) -> None:
        self._vec = query_vector

    def embed_query(self, query: str) -> np.ndarray:
        return self._vec


def _chunks() -> list[RawChunk]:
    return [
        RawChunk(chunk_id="c0", source="a.md", text="python pyspark airflow mlops"),
        RawChunk(chunk_id="c1", source="a.md", text="cocina recetas pastel"),
        RawChunk(chunk_id="c2", source="a.md", text="python scikit-learn machine learning"),
        RawChunk(chunk_id="c3", source="a.md", text="viajes montañas senderismo"),
    ]


async def test_bm25_solo_sin_embeddings_devuelve_relevantes() -> None:
    retriever = LocalRetriever(_chunks(), embeddings=None, embedder=None)
    assert not retriever.has_dense_index

    results = await retriever.search("python machine learning", k=2)

    ids = {r.chunk_id for r in results}
    assert ids <= {"c0", "c1", "c2", "c3"}
    assert "c2" in ids  # el chunk que comparte más términos con la query


async def test_search_bajo_20ms() -> None:
    retriever = LocalRetriever(_chunks(), embeddings=None, embedder=None)

    start = time.perf_counter()
    await retriever.search("python", k=3)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 20


async def test_lista_vacia_no_revienta() -> None:
    retriever = LocalRetriever([], embeddings=None, embedder=None)
    assert await retriever.search("cualquier cosa") == []


async def test_dense_rrf_mmr_con_embedder_fake() -> None:
    # c0 y c2 quedan cerca en el espacio denso (ambos "python"); c1 y c3 lejos.
    embeddings = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
    query_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    embedder = _FakeEmbedder(query_vec)
    retriever = LocalRetriever(_chunks(), embeddings=embeddings, embedder=embedder)
    assert retriever.has_dense_index

    results = await retriever.search("python", k=2)

    assert results[0].chunk_id == "c0"  # el más cercano al query en el espacio denso


def test_build_local_retriever_sin_precomputo_cae_a_bm25(tmp_path: Path) -> None:
    narrative = tmp_path / "narrative"
    narrative.mkdir()
    (narrative / "a.md").write_text("# T\nAlgo de texto de prueba.\n", encoding="utf-8")

    retriever = build_local_retriever(tmp_path, embedder=None)

    assert not retriever.has_dense_index


def test_build_local_retriever_embeddings_desfasados_caen_a_bm25(tmp_path: Path) -> None:
    narrative = tmp_path / "narrative"
    narrative.mkdir()
    (narrative / "a.md").write_text(
        "# T\nTexto que cambió después de precomputar.\n", encoding="utf-8"
    )

    # chunks.json de una versión anterior del contenido -> chunk_id no coincide.
    (tmp_path / "chunks.json").write_text(
        json.dumps([{"chunk_id": "a#viejo", "source": "a.md", "text": "viejo"}]),
        encoding="utf-8",
    )
    np.save(tmp_path / "embeddings.npy", np.zeros((1, 4), dtype=np.float32))

    retriever = build_local_retriever(tmp_path, embedder=None)

    assert not retriever.has_dense_index

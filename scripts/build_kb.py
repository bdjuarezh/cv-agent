"""Valida el KB y precomputa embeddings del corpus narrativo. `make kb`.

Requiere Vertex configurado (GCP_PROJECT + credenciales ADC) — genera `data/embeddings.npy`
y `data/chunks.json`, que se commitean para no recalcular ni llamar a Vertex en cada arranque
del servicio (`knowledge/retrieval/local.py`)."""

from __future__ import annotations

import json
import sys

import numpy as np
from pydantic import ValidationError

from cv_agent.config import REPO_ROOT, settings
from cv_agent.knowledge.chunking import chunk_narrative
from cv_agent.knowledge.store import load_knowledge_base
from cv_agent.providers.embeddings import build_embeddings


def main() -> int:
    data_dir = REPO_ROOT / "data"

    try:
        load_knowledge_base(data_dir)
    except ValidationError as exc:
        print(f"KB inválida:\n{exc}", file=sys.stderr)
        return 1

    chunks = chunk_narrative(data_dir / "narrative")
    if not chunks:
        print("Sin narrativa que indexar (data/narrative vacío) — nada que hacer.")
        return 0

    embedder = build_embeddings(
        project=settings.gcp_project,
        region=settings.vertex_region,
        model=settings.embedding_model,
    )
    if embedder is None:
        print(
            "Vertex no configurado (GCP_PROJECT vacío) — no se pueden generar embeddings. "
            "El servicio funciona igual con BM25 solo hasta que corras esto.",
            file=sys.stderr,
        )
        return 1

    vectors = embedder.embed_passages([c.text for c in chunks])
    np.save(data_dir / "embeddings.npy", vectors)
    (data_dir / "chunks.json").write_text(
        json.dumps(
            [{"chunk_id": c.chunk_id, "source": c.source, "text": c.text} for c in chunks],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"{len(chunks)} chunks indexados -> data/embeddings.npy, data/chunks.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

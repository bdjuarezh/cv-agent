"""CLI para probar el agente sin levantar HTTP: `python -m cv_agent.cli "pregunta"`."""

from __future__ import annotations

import asyncio
import sys

import structlog

from cv_agent.agent.guardrails import check_input
from cv_agent.agent.loop import run
from cv_agent.agent.prompts import build_system_prompt
from cv_agent.agent.tools import ToolContext
from cv_agent.config import REPO_ROOT, settings
from cv_agent.knowledge.retrieval.local import build_local_retriever
from cv_agent.knowledge.store import KnowledgeStore, load_knowledge_base
from cv_agent.providers.base import Message
from cv_agent.providers.embeddings import build_embeddings
from cv_agent.providers.factory import build_provider

log = structlog.get_logger()


async def ask(question: str) -> str:
    data_dir = REPO_ROOT / "data"
    kb = load_knowledge_base(data_dir)
    store = KnowledgeStore(kb)
    embedder = build_embeddings(
        project=settings.gcp_project, region=settings.vertex_region, model=settings.embedding_model
    )
    retriever = build_local_retriever(data_dir, embedder)
    ctx = ToolContext(store=store, retriever=retriever)
    system = build_system_prompt(kb)

    check = check_input(question)
    if check.flagged:
        log.warning("guardrail_flagged", reason=check.reason)

    provider = build_provider()
    if provider is None:
        raise SystemExit(
            f"El proveedor '{settings.provider_backend}' no está configurado — revisa .env "
            "(GCP_PROJECT o ANTHROPIC_API_KEY según PROVIDER_BACKEND)."
        )
    result = await run(
        provider,
        system,
        [Message(role="user", content=question)],
        ctx,
        max_iterations=settings.max_loop_iterations,
    )
    return result.text


def main() -> None:
    if len(sys.argv) < 2:
        print('uso: python -m cv_agent.cli "tu pregunta"', file=sys.stderr)
        raise SystemExit(2)
    question = " ".join(sys.argv[1:])
    answer = asyncio.run(ask(question))
    # La consola de Windows suele quedar en cp1252, que no cubre emoji ni varios acentos —
    # mismo bug ya visto en evals/run.py. Se escribe a stdout.buffer en UTF-8 para no tronar.
    sys.stdout.buffer.write(answer.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()

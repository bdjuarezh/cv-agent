from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cv_agent.agent.prompts import build_system_prompt
from cv_agent.agent.tools import ToolContext
from cv_agent.api.app_state import AppState
from cv_agent.api.errors import register_error_handlers
from cv_agent.api.middleware import RequestContextMiddleware
from cv_agent.api.routes_meta import router as meta_router
from cv_agent.api.routes_responses import router as responses_router
from cv_agent.config import REPO_ROOT, settings
from cv_agent.knowledge.retrieval.local import build_local_retriever
from cv_agent.knowledge.store import KnowledgeStore, load_knowledge_base
from cv_agent.obs.logging import configure_logging
from cv_agent.providers.embeddings import VertexEmbeddings, build_embeddings
from cv_agent.providers.factory import build_provider
from cv_agent.state.response_store import TTLCacheStore

configure_logging()
log = structlog.get_logger()


def _build_embedder() -> VertexEmbeddings | None:
    return build_embeddings(
        project=settings.gcp_project,
        region=settings.vertex_region,
        model=settings.embedding_model,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    data_dir = REPO_ROOT / "data"
    kb = load_knowledge_base(data_dir)
    store = KnowledgeStore(kb)
    retriever = build_local_retriever(data_dir, _build_embedder())
    app.state.cv_agent = AppState(
        tool_ctx=ToolContext(store=store, retriever=retriever),
        system_prompt=build_system_prompt(kb),
        response_store=TTLCacheStore(ttl=settings.state_ttl_seconds),
        provider=build_provider(),
    )
    yield


app = FastAPI(title="cv-agent", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)
register_error_handlers(app)

app.include_router(meta_router)
app.include_router(responses_router, prefix="/v1")  # /v1/responses
app.include_router(responses_router)  # /responses — ver 01_ARQUITECTURA.md §1

_well_known = REPO_ROOT / "web" / ".well-known"
if _well_known.exists():
    app.mount("/.well-known", StaticFiles(directory=_well_known), name="well-known")

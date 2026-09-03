from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from cv_agent.agent.prompts import build_system_prompt
from cv_agent.agent.tools import ToolContext
from cv_agent.api.app import app
from cv_agent.api.app_state import AppState, get_app_state
from cv_agent.api.ratelimit import limiter as rate_limiter
from cv_agent.config import settings
from cv_agent.knowledge.retrieval.local import build_local_retriever
from cv_agent.knowledge.store import KnowledgeStore, load_knowledge_base
from cv_agent.obs.metrics import metrics
from cv_agent.providers.base import ProviderResult
from cv_agent.providers.fake import FakeProvider
from cv_agent.state.response_store import TTLCacheStore

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TEST_API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "api_key", TEST_API_KEY)


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    """`limiter` y `metrics` son singletons de proceso (correctos en producción, con
    --max-instances=1) — sin resetear, un test contaminaría el estado del siguiente."""
    rate_limiter.reset()
    metrics.reset()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_API_KEY}"}


@pytest.fixture
def make_client() -> Callable[[list[ProviderResult]], tuple[AsyncClient, FakeProvider]]:
    """Fábrica de (cliente, FakeProvider) sobre la app real, con `get_app_state` sobreescrito —
    así las rutas nunca tocan Vertex ni el lifespan real. Un mismo cliente puede usarse para
    varias llamadas HTTP seguidas (p. ej. dos turnos con `previous_response_id`): comparten el
    mismo `response_store` y el mismo `FakeProvider`, consumiendo su guion en orden."""
    kb = load_knowledge_base(DATA_DIR)
    store = KnowledgeStore(kb)
    retriever = build_local_retriever(DATA_DIR, embedder=None)  # BM25 solo, sin Vertex en tests
    tool_ctx = ToolContext(store=store, retriever=retriever)
    system_prompt = build_system_prompt(kb)
    response_store = TTLCacheStore()

    def _make(script: list[ProviderResult]) -> tuple[AsyncClient, FakeProvider]:
        provider = FakeProvider(script)
        state = AppState(
            tool_ctx=tool_ctx,
            system_prompt=system_prompt,
            response_store=response_store,
            provider=provider,
        )
        app.dependency_overrides[get_app_state] = lambda: state
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
        return client, provider

    yield _make
    app.dependency_overrides.clear()

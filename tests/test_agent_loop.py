from pathlib import Path

import pytest

from cv_agent.agent.loop import run
from cv_agent.agent.tools import ToolContext
from cv_agent.knowledge.retrieval.local import build_local_retriever
from cv_agent.knowledge.store import KnowledgeStore, load_knowledge_base
from cv_agent.providers.base import Message, ProviderResult, ToolCall
from cv_agent.providers.fake import FakeProvider

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def ctx() -> ToolContext:
    store = KnowledgeStore(load_knowledge_base(DATA_DIR))
    retriever = build_local_retriever(DATA_DIR, embedder=None)
    return ToolContext(store=store, retriever=retriever)


async def test_respuesta_directa_sin_herramienta(ctx: ToolContext) -> None:
    provider = FakeProvider([ProviderResult(text="Hola, soy el agente de Jane Doe.")])

    result = await run(provider, "system", [Message(role="user", content="hola")], ctx)

    assert result.text == "Hola, soy el agente de Jane Doe."
    assert result.iterations == 1
    assert result.stop_reason == "end_turn"
    assert provider.calls == 1


async def test_una_tool_call(ctx: ToolContext) -> None:
    provider = FakeProvider(
        [
            ProviderResult(
                text="",
                tool_calls=(
                    ToolCall(id="t1", name="compute_years", arguments={"skill": "python"}),
                ),
                stop_reason="tool_use",
            ),
            ProviderResult(text="Llevas 2 años con Python."),
        ]
    )

    result = await run(provider, "system", [Message(role="user", content="?")], ctx)

    assert result.text == "Llevas 2 años con Python."
    assert result.iterations == 2
    assert provider.calls == 2
    tool_messages = [m for m in result.messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "t1"


async def test_dos_tool_calls_encadenadas(ctx: ToolContext) -> None:
    provider = FakeProvider(
        [
            ProviderResult(
                text="",
                tool_calls=(ToolCall(id="t1", name="get_skills", arguments={}),),
                stop_reason="tool_use",
            ),
            ProviderResult(
                text="",
                tool_calls=(
                    ToolCall(id="t2", name="compute_years", arguments={"skill": "python"}),
                ),
                stop_reason="tool_use",
            ),
            ProviderResult(text="Respuesta final tras dos herramientas."),
        ]
    )

    result = await run(provider, "system", [Message(role="user", content="?")], ctx)

    assert result.text == "Respuesta final tras dos herramientas."
    assert result.iterations == 3
    assert provider.calls == 3


async def test_corte_por_max_iterations(ctx: ToolContext) -> None:
    always_tool_call = ProviderResult(
        text="parcial",
        tool_calls=(ToolCall(id="t", name="get_skills", arguments={}),),
        stop_reason="tool_use",
    )
    provider = FakeProvider([always_tool_call] * 10)

    result = await run(
        provider, "system", [Message(role="user", content="?")], ctx, max_iterations=3
    )

    assert result.iterations == 3
    assert result.stop_reason == "max_iterations"
    assert "parcial" in result.text
    assert provider.calls == 3


async def test_herramienta_que_lanza_excepcion_no_rompe_el_loop(ctx: ToolContext) -> None:
    provider = FakeProvider(
        [
            ProviderResult(
                text="",
                tool_calls=(ToolCall(id="t1", name="herramienta_inexistente", arguments={}),),
                stop_reason="tool_use",
            ),
            ProviderResult(text="Me faltó esa herramienta, sigo con lo que sé."),
        ]
    )

    result = await run(provider, "system", [Message(role="user", content="?")], ctx)

    assert result.text == "Me faltó esa herramienta, sigo con lo que sé."
    tool_messages = [m for m in result.messages if m.role == "tool"]
    assert "Error ejecutando herramienta_inexistente" in tool_messages[0].content

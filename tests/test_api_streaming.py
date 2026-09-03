import json
from collections.abc import Callable

from httpx import AsyncClient

from cv_agent.providers.base import ProviderResult, ToolCall
from cv_agent.providers.fake import FakeProvider

MakeClient = Callable[[list[ProviderResult]], tuple[AsyncClient, FakeProvider]]


async def test_stream_true_secuencia_sse_valida(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client([ProviderResult(text="Resumen de mi perfil.")])
    async with (
        client,
        client.stream(
            "POST",
            "/v1/responses",
            json={"input": "resume tu perfil", "stream": True},
            headers=auth_headers,
        ) as r,
    ):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        raw = (await r.aread()).decode("utf-8")

    blocks = [b for b in raw.split("\n\n") if b.strip()]
    assert blocks[-1] == "data: [DONE]"

    seq_numbers: list[int] = []
    seen_types: list[str] = []
    for block in blocks[:-1]:
        lines = block.split("\n")
        event_line = next(line for line in lines if line.startswith("event: "))
        data_line = next(line for line in lines if line.startswith("data: "))
        event_type = event_line.removeprefix("event: ")
        payload = json.loads(data_line.removeprefix("data: "))

        assert payload["type"] == event_type  # event: == type del JSON
        seq_numbers.append(payload["sequence_number"])
        seen_types.append(event_type)

    assert seq_numbers == sorted(seq_numbers)
    assert len(seq_numbers) == len(set(seq_numbers))  # estrictamente creciente, sin repetir
    assert seq_numbers == list(range(1, len(seq_numbers) + 1))

    assert seen_types[0] == "response.created"
    assert seen_types[-1] == "response.completed"
    assert "response.output_text.delta" in seen_types


async def test_stream_expone_tool_calls_para_la_demo(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    """Evento propio `cv_agent.tool_call`, fuera del spec — solo para web/index.html."""
    client, _ = make_client(
        [
            ProviderResult(
                text="",
                tool_calls=(ToolCall(id="t1", name="get_skills", arguments={}),),
                stop_reason="tool_use",
            ),
            ProviderResult(text="Tengo varias habilidades."),
        ]
    )
    async with (
        client,
        client.stream(
            "POST",
            "/v1/responses",
            json={"input": "¿qué sabes hacer?", "stream": True},
            headers=auth_headers,
        ) as r,
    ):
        raw = (await r.aread()).decode("utf-8")

    blocks = [b for b in raw.split("\n\n") if b.strip()]
    tool_call_blocks = [b for b in blocks if b.startswith("event: cv_agent.tool_call")]
    assert len(tool_call_blocks) == 1
    payload = json.loads(tool_call_blocks[0].split("\n")[1].removeprefix("data: "))
    assert payload["name"] == "get_skills"

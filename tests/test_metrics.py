from collections.abc import Callable

from httpx import AsyncClient

from cv_agent.providers.base import ProviderResult, ToolCall, Usage
from cv_agent.providers.fake import FakeProvider

MakeClient = Callable[[list[ProviderResult]], tuple[AsyncClient, FakeProvider]]


async def test_metrics_requiere_auth(make_client: MakeClient) -> None:
    client, _ = make_client([])
    async with client:
        r = await client.get("/metrics")

    assert r.status_code == 401


async def test_metrics_refleja_requests_tokens_y_tool_calls(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client(
        [
            ProviderResult(
                text="",
                tool_calls=(ToolCall(id="t1", name="get_skills", arguments={}),),
                stop_reason="tool_use",
                usage=Usage(input_tokens=100, output_tokens=20),
            ),
            ProviderResult(text="listo"),
        ]
    )
    async with client:
        r = await client.post("/v1/responses", json={"input": "hola"}, headers=auth_headers)
        assert r.status_code == 200

        metrics_response = await client.get("/metrics", headers=auth_headers)

    assert metrics_response.status_code == 200
    body = metrics_response.json()
    assert body["requests_total"] >= 1
    assert "latency_ms_p50" in body
    assert "latency_ms_p95" in body
    assert body["tokens_input_total"] >= 100
    assert body["tokens_output_total"] >= 20
    assert body["tool_calls"].get("get_skills") == 1
    assert body["estimated_cost_usd"] > 0

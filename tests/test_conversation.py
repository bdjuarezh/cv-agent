from collections.abc import Callable

from httpx import AsyncClient

from cv_agent.providers.base import ProviderResult
from cv_agent.providers.fake import FakeProvider

MakeClient = Callable[[list[ProviderResult]], tuple[AsyncClient, FakeProvider]]


async def test_previous_response_id_inexistente_da_400(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client([])  # el provider no debe ni llamarse
    async with client:
        r = await client.post(
            "/v1/responses",
            json={"input": "hola", "previous_response_id": "resp_no_existe"},
            headers=auth_headers,
        )

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "previous_response_not_found"


async def test_turno_2_recuerda_el_turno_1(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, provider = make_client(
        [ProviderResult(text="Mucho gusto, Ana."), ProviderResult(text="Te llamas Ana.")]
    )
    async with client:
        r1 = await client.post(
            "/v1/responses", json={"input": "Me llamo Ana"}, headers=auth_headers
        )
        assert r1.status_code == 200
        response_id = r1.json()["id"]

        r2 = await client.post(
            "/v1/responses",
            json={"input": "¿cómo me llamo?", "previous_response_id": response_id},
            headers=auth_headers,
        )
        assert r2.status_code == 200

    # El segundo turno se le manda al proveedor con el historial del primero ya adentro.
    assert provider.calls == 2
    second_call_history = provider.calls_history[1]
    assert any(m.role == "user" and "Ana" in m.content for m in second_call_history)
    assert any(m.role == "assistant" and "Ana" in m.content for m in second_call_history)

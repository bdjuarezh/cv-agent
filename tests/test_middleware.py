from collections.abc import Callable

from httpx import AsyncClient

from cv_agent.providers.base import ProviderResult
from cv_agent.providers.fake import FakeProvider

MakeClient = Callable[[list[ProviderResult]], tuple[AsyncClient, FakeProvider]]


async def test_request_id_se_genera_si_no_viene(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client([ProviderResult(text="ok")])
    async with client:
        r = await client.post("/v1/responses", json={"input": "hola"}, headers=auth_headers)

    assert r.headers["x-request-id"]


async def test_request_id_se_respeta_si_el_cliente_lo_manda(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client([ProviderResult(text="ok")])
    headers = {**auth_headers, "X-Request-Id": "mi-id-123"}
    async with client:
        r = await client.post("/v1/responses", json={"input": "hola"}, headers=headers)

    assert r.headers["x-request-id"] == "mi-id-123"


async def test_body_mayor_a_256kb_da_400(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client([])  # el provider no debe llamarse
    big_input = "x" * (300 * 1024)
    async with client:
        r = await client.post("/v1/responses", json={"input": big_input}, headers=auth_headers)

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "body_too_large"

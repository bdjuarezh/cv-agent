from collections.abc import Callable

from httpx import AsyncClient

from cv_agent.providers.base import ProviderResult
from cv_agent.providers.fake import FakeProvider

MakeClient = Callable[[list[ProviderResult]], tuple[AsyncClient, FakeProvider]]


async def test_input_string_devuelve_200_y_texto(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client([ProviderResult(text="Hola, soy el agente de Jane Doe.")])
    async with client:
        r = await client.post("/v1/responses", json={"input": "hola"}, headers=auth_headers)

    assert r.status_code == 200
    body = r.json()
    assert body["output"][0]["content"][0]["text"] == "Hola, soy el agente de Jane Doe."


async def test_input_array_con_content_parts_devuelve_200(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client([ProviderResult(text="Sí, tengo experiencia en MLOps.")])
    payload = {
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "¿experiencia en MLOps?"}],
            }
        ]
    }
    async with client:
        r = await client.post("/v1/responses", json=payload, headers=auth_headers)

    assert r.status_code == 200
    assert r.json()["output"][0]["content"][0]["text"]


async def test_input_item_sin_type_no_revienta(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client([ProviderResult(text="Hola.")])
    payload = {"input": [{"role": "user", "content": "hola sin type"}]}
    async with client:
        r = await client.post("/v1/responses", json=payload, headers=auth_headers)

    assert r.status_code == 200


async def test_sin_authorization_devuelve_401_con_envelope(make_client: MakeClient) -> None:
    client, _ = make_client([])
    async with client:
        r = await client.post("/v1/responses", json={"input": "hola"})

    assert r.status_code == 401
    body = r.json()
    assert "error" in body
    assert {"message", "type", "param", "code"} <= body["error"].keys()


async def test_respuesta_contiene_todas_las_llaves_required(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    from cv_agent.schemas.responses import REQUIRED_FIELDS

    client, _ = make_client([ProviderResult(text="ok")])
    async with client:
        r = await client.post("/v1/responses", json={"input": "hola"}, headers=auth_headers)

    assert REQUIRED_FIELDS <= set(r.json().keys())


async def test_background_true_no_soportado(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client([])
    async with client:
        r = await client.post(
            "/v1/responses",
            json={"input": "hola", "background": True},
            headers=auth_headers,
        )

    assert r.status_code == 400
    assert r.json()["error"]["param"] == "background"

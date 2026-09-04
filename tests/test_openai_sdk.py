"""El más importante del repo: si el SDK oficial de OpenAI habla con nuestro endpoint sin
parches, la plataforma de Banorte también."""

from collections.abc import Callable

from httpx import AsyncClient
from openai import AsyncOpenAI

from cv_agent.providers.base import ProviderResult
from cv_agent.providers.fake import FakeProvider

MakeClient = Callable[[list[ProviderResult]], tuple[AsyncClient, FakeProvider]]


async def test_sdk_oficial_de_openai_interopera(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client(
        [ProviderResult(text="Tengo experiencia en MLOps: pipelines, CI/CD y monitoreo.")]
    )
    async with client:
        openai_client = AsyncOpenAI(
            base_url="http://t/v1",
            api_key=auth_headers["Authorization"].removeprefix("Bearer "),
            http_client=client,
        )
        response = await openai_client.responses.create(
            model="cv-agent", input="¿cuál es tu experiencia en MLOps?"
        )

    assert response.output[0].content[0].text

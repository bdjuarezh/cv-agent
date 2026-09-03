from collections.abc import Callable

from httpx import AsyncClient

from cv_agent.api.ratelimit import TokenBucketLimiter
from cv_agent.providers.base import ProviderResult
from cv_agent.providers.fake import FakeProvider

MakeClient = Callable[[list[ProviderResult]], tuple[AsyncClient, FakeProvider]]


def test_token_bucket_permite_rafaga_hasta_la_capacidad() -> None:
    limiter = TokenBucketLimiter(capacity=3, refill_per_second=0.5)
    results = [limiter.allow("ip")[0] for _ in range(4)]
    assert results == [True, True, True, False]


def test_token_bucket_retry_after_es_positivo_cuando_bloquea() -> None:
    limiter = TokenBucketLimiter(capacity=1, refill_per_second=0.5)
    limiter.allow("ip")
    allowed, retry_after = limiter.allow("ip")
    assert not allowed
    assert retry_after > 0


async def test_11_requests_rapidas_la_11_da_429(
    make_client: MakeClient, auth_headers: dict[str, str]
) -> None:
    client, _ = make_client([ProviderResult(text="ok")] * 10)
    statuses: list[int] = []
    last_headers = None
    async with client:
        for _ in range(11):
            r = await client.post("/v1/responses", json={"input": "hola"}, headers=auth_headers)
            statuses.append(r.status_code)
            last_headers = r.headers

    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429
    assert last_headers is not None
    assert int(last_headers["retry-after"]) > 0

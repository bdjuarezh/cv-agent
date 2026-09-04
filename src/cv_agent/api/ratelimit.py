"""Token bucket en memoria por IP — abuso económico (ARCHITECTURE.md §4). Una ráfaga de n se
admite si n <= b; el sostenido converge a r. Solo aplica a `POST /responses`, no a `/healthz`."""

from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Request

from cv_agent.api.errors import ApiError

CAPACITY = 10.0
REFILL_PER_SECOND = 0.5


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    def __init__(
        self, capacity: float = CAPACITY, refill_per_second: float = REFILL_PER_SECOND
    ) -> None:
        self._capacity = capacity
        self._refill_per_second = refill_per_second
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str) -> tuple[bool, float]:
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self._capacity, updated_at=now)
            self._buckets[key] = bucket
        else:
            elapsed = now - bucket.updated_at
            bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill_per_second)
            bucket.updated_at = now

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0.0
        retry_after = (1.0 - bucket.tokens) / self._refill_per_second
        return False, retry_after

    def reset(self) -> None:
        """Solo para tests — el bucket real vive mientras viva el proceso."""
        self._buckets.clear()


limiter = TokenBucketLimiter()


def rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.allow(client_ip)
    if not allowed:
        raise ApiError(
            "Límite de solicitudes excedido.",
            type="too_many_requests",
            code="rate_limited",
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )

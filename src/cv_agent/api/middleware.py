"""`request_id` correlacionado en logs + límite de tamaño de body (ARCHITECTURE.md §4). Solo lee
`Content-Length`, nunca `request.body()` — eso agotaría el stream antes de que el handler lo
parseé."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from cv_agent.api.errors import ApiError
from cv_agent.obs.metrics import metrics

MAX_BODY_BYTES = 256 * 1024


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        log = structlog.get_logger()

        content_length = request.headers.get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > MAX_BODY_BYTES
        ):
            log.warning("request_body_too_large", content_length=content_length)
            err = ApiError(
                "El cuerpo de la solicitud excede el límite de 256 KB.",
                type="invalid_request",
                code="body_too_large",
            )
            response: Response = JSONResponse(
                status_code=err.status_code, content=err.to_envelope()
            )
            response.headers["X-Request-Id"] = request_id
            return response

        start = time.perf_counter()
        log.info("request_in", method=request.method, path=request.url.path)
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        log.info("request_out", status_code=response.status_code, duration_ms=round(duration_ms, 1))
        metrics.record_request(duration_ms=duration_ms, status_code=response.status_code)
        response.headers["X-Request-Id"] = request_id
        return response

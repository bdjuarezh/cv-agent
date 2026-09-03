"""Envelope de error del spec: `{"error": {message, type, param, code}}`. Nunca se filtra un
traceback al cliente (CLAUDE.md regla 7) — un 500 no controlado se loguea completo server-side
y se devuelve genérico."""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = structlog.get_logger()

ErrorType = Literal[
    "invalid_request",
    "authentication_error",
    "not_found",
    "too_many_requests",
    "server_error",
    "model_error",
]

_STATUS_BY_TYPE: dict[ErrorType, int] = {
    "invalid_request": 400,
    "authentication_error": 401,
    "not_found": 404,
    "too_many_requests": 429,
    "server_error": 500,
    "model_error": 500,
}


class ApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        type: ErrorType = "invalid_request",
        param: str | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.type = type
        self.param = param
        self.code = code
        self.headers = headers or {}

    @property
    def status_code(self) -> int:
        return _STATUS_BY_TYPE[self.type]

    def to_envelope(self) -> dict[str, dict[str, str | None]]:
        return {
            "error": {
                "message": self.message,
                "type": self.type,
                "param": self.param,
                "code": self.code,
            }
        }


class UnauthorizedError(ApiError):
    def __init__(self, message: str = "Falta o es inválido el header Authorization.") -> None:
        super().__init__(message, type="authentication_error", code="invalid_api_key")


class PreviousResponseNotFoundError(ApiError):
    def __init__(self, response_id: str) -> None:
        super().__init__(
            f"No existe una respuesta previa con id '{response_id}'.",
            type="invalid_request",
            param="previous_response_id",
            code="previous_response_not_found",
        )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=exc.to_envelope(), headers=exc.headers or None
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        err = ApiError("Solicitud inválida.", type="invalid_request", code="invalid_body")
        return JSONResponse(status_code=err.status_code, content=err.to_envelope())

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        err = ApiError("Error interno.", type="server_error")
        return JSONResponse(status_code=err.status_code, content=err.to_envelope())

from __future__ import annotations

import hmac

from fastapi import Header

from cv_agent.api.errors import UnauthorizedError
from cv_agent.config import settings


def require_bearer(authorization: str | None = Header(None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError()
    token = authorization.removeprefix("Bearer ")
    # compare_digest, no `==`: la comparación normal sale en el primer byte distinto y filtra
    # el token por análisis de tiempos.
    if not hmac.compare_digest(token, settings.api_key):
        raise UnauthorizedError()

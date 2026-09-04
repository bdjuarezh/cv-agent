"""Un solo lugar que decide qué `Provider` construir según `settings.provider_backend` — usado
por `api/app.py`, `cli.py` y `evals/run.py` para no triplicar el switch entre `anthropic_direct`
(producción) y `vertex` (alternativa)."""

from __future__ import annotations

import structlog

from cv_agent.config import settings
from cv_agent.providers.anthropic_direct import AnthropicDirectProvider
from cv_agent.providers.base import Provider
from cv_agent.providers.vertex_anthropic import VertexAnthropicProvider

log = structlog.get_logger()


def build_provider() -> Provider | None:
    """`None` si el backend elegido no está configurado — el servicio sigue arriba
    (`/healthz` responde), pero `POST /responses` devuelve 500 `server_error` hasta que haya
    proveedor. Nunca lanza: cualquier fallo de construcción se loguea y degrada a `None`."""
    try:
        if settings.provider_backend == "anthropic_direct":
            if not settings.anthropic_api_key:
                log.warning(
                    "provider_not_configured",
                    backend="anthropic_direct",
                    reason="ANTHROPIC_API_KEY vacío",
                )
                return None
            return AnthropicDirectProvider(
                api_key=settings.anthropic_api_key,
                model=settings.model_id,
                timeout=settings.provider_timeout_seconds,
            )

        if not settings.gcp_project:
            log.warning("provider_not_configured", backend="vertex", reason="GCP_PROJECT vacío")
            return None
        return VertexAnthropicProvider(
            project=settings.gcp_project,
            region=settings.vertex_region,
            model=settings.model_id,
            timeout=settings.provider_timeout_seconds,
        )
    except Exception:
        log.exception("provider_init_failed", backend=settings.provider_backend)
        return None

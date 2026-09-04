"""API directa de Anthropic (API key propia, sin GCP) — **el proveedor de producción**
(ARCHITECTURE.md §6, §7): la cuota de Vertex AI para el modelo de chat nunca se aprobó a tiempo
para el reto. Misma interfaz `Provider`, mismo `agent/loop.py` que `vertex_anthropic.py`, solo
cambia la autenticación."""

from __future__ import annotations

from anthropic import AsyncAnthropic

from cv_agent.providers.anthropic_messages import AnthropicMessagesProvider


class AnthropicDirectProvider(AnthropicMessagesProvider):
    def __init__(self, *, api_key: str, model: str, timeout: float = 30.0) -> None:
        super().__init__(AsyncAnthropic(api_key=api_key), model=model, timeout=timeout)

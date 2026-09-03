"""API directa de Anthropic (API key propia, sin GCP) — **proveedor de contingencia**, no la
decisión de producción (D8: Vertex/IAM, ver ARCHITECTURE.md §6). Existe para no quedar bloqueados
si la cuota de Vertex tarda en aprobarse: misma interfaz `Provider`, mismo `agent/loop.py`, solo
cambia la autenticación."""

from __future__ import annotations

from anthropic import AsyncAnthropic

from cv_agent.providers.anthropic_messages import AnthropicMessagesProvider


class AnthropicDirectProvider(AnthropicMessagesProvider):
    def __init__(self, *, api_key: str, model: str, timeout: float = 30.0) -> None:
        super().__init__(AsyncAnthropic(api_key=api_key), model=model, timeout=timeout)

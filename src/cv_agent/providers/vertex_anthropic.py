from __future__ import annotations

from anthropic import AsyncAnthropicVertex

from cv_agent.providers.anthropic_messages import AnthropicMessagesProvider


class VertexAnthropicProvider(AnthropicMessagesProvider):
    """Claude vía Vertex AI (`AsyncAnthropicVertex`) — auth por IAM/ADC, sin API key del modelo.
    Decisión original de producción; no usada porque la cuota de Vertex para el modelo de chat
    nunca se aprobó a tiempo (ARCHITECTURE.md §6, §7) — queda soportada como alternativa, mismo
    contrato `Provider`, si se retoma el acceso."""

    def __init__(self, *, project: str, region: str, model: str, timeout: float = 30.0) -> None:
        super().__init__(
            AsyncAnthropicVertex(project_id=project, region=region), model=model, timeout=timeout
        )

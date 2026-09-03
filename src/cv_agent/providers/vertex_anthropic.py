from __future__ import annotations

from anthropic import AsyncAnthropicVertex

from cv_agent.providers.anthropic_messages import AnthropicMessagesProvider


class VertexAnthropicProvider(AnthropicMessagesProvider):
    """Claude vía Vertex AI (`AsyncAnthropicVertex`) — auth por IAM/ADC, sin API key del modelo
    (D8, ARCHITECTURE.md §6). El camino real de producción."""

    def __init__(self, *, project: str, region: str, model: str, timeout: float = 30.0) -> None:
        super().__init__(
            AsyncAnthropicVertex(project_id=project, region=region), model=model, timeout=timeout
        )

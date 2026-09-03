from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from cv_agent.providers.base import Message, ProviderResult


class FakeProvider:
    """Guionizable y sin red — usado en todos los tests (CLAUDE.md regla 5).

    Cada llamada a `complete` consume el siguiente `ProviderResult` del guion, en orden.
    Llamar más veces de las guionizadas es un error de test (guion mal dimensionado), no un
    comportamiento a tolerar en silencio.
    """

    def __init__(self, script: Sequence[ProviderResult]) -> None:
        self._script = list(script)
        self.calls = 0
        self.calls_history: list[list[Message]] = []

    async def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
        **params: Any,
    ) -> ProviderResult:
        if self.calls >= len(self._script):
            raise AssertionError(
                f"FakeProvider: guion agotado tras {self.calls} llamadas — amplía el guion del test"
            )
        self.calls_history.append(list(messages))
        result = self._script[self.calls]
        self.calls += 1
        return result

    async def stream(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
        **params: Any,
    ) -> AsyncIterator[str]:
        result = await self.complete(system, messages, tools, **params)
        yield result.text

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """Turno de conversación interno, independiente del formato de cada proveedor."""

    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass(frozen=True)
class ProviderResult:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = "end_turn"


class Provider(Protocol):
    async def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
        **params: Any,
    ) -> ProviderResult: ...

    def stream(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
        **params: Any,
    ) -> AsyncIterator[str]: ...

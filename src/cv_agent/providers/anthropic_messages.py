"""Lógica compartida por cualquier cliente compatible con la Messages API de Anthropic —
`AsyncAnthropicVertex` y `AsyncAnthropic` (directo) exponen la misma interfaz
`.messages.create()`/`.messages.stream()`, así que un solo lugar traduce nuestro `Message`
interno y maneja retries, sin duplicar esa lógica entre `vertex_anthropic.py` y
`anthropic_direct.py` (`providers/base.Provider` es el Protocol que ambos implementan)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

import anthropic
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_random_exponential

from cv_agent.providers.base import Message, ProviderResult, ToolCall, Usage


def _is_retryable(exc: BaseException) -> bool:
    """Solo 429/5xx — nunca reintentar un 4xx de validación (sin abstracciones que escondan un
    error del cliente como si fuera transitorio)."""
    return isinstance(exc, anthropic.APIStatusError) and (
        exc.status_code == 429 or exc.status_code >= 500
    )


_retry_on_429_5xx = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=10),
    reraise=True,
)


def to_anthropic_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Traduce el turno interno (agnóstico de proveedor) al formato de mensajes de Anthropic.

    Los turnos `tool` consecutivos se agrupan en un único mensaje `user` con varios bloques
    `tool_result`, que es lo que la API de Anthropic espera para los resultados de un mismo
    turno de tool_use.
    """
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(messages):
        message = messages[i]

        if message.role == "tool":
            blocks: list[dict[str, Any]] = []
            while i < len(messages) and messages[i].role == "tool":
                tool_message = messages[i]
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_message.tool_call_id,
                        "content": tool_message.content,
                    }
                )
                i += 1
            out.append({"role": "user", "content": blocks})
            continue

        if message.role == "assistant" and message.tool_calls:
            assistant_blocks: list[dict[str, Any]] = []
            if message.content:
                assistant_blocks.append({"type": "text", "text": message.content})
            for tool_call in message.tool_calls:
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "input": tool_call.arguments,
                    }
                )
            out.append({"role": "assistant", "content": assistant_blocks})
            i += 1
            continue

        out.append({"role": message.role, "content": message.content})
        i += 1
    return out


def system_blocks(system: str, instructions: str) -> list[dict[str, Any]]:
    """El corpus/reglas propias van en el bloque cacheado; las `instructions` del cliente (menor
    prioridad, cambian por request) van en un segundo bloque SIN `cache_control` — así no rompen
    el prefijo cacheado (agent/loop.py, ARCHITECTURE.md §1)."""
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
    ]
    if instructions:
        blocks.append({"type": "text", "text": instructions})
    return blocks


class _MessagesClient(Protocol):
    @property
    def messages(self) -> Any: ...


class AnthropicMessagesProvider:
    """Base común — recibe cualquier cliente ya construido (`AsyncAnthropicVertex` o
    `AsyncAnthropic`) y le habla igual. Las subclases solo difieren en cómo se autentican."""

    def __init__(self, client: _MessagesClient, *, model: str, timeout: float = 30.0) -> None:
        self._client = client
        self._model = model
        self._timeout = timeout

    @_retry_on_429_5xx
    async def _create(
        self,
        *,
        max_tokens: int,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        # Esta versión del SDK no acepta `temperature` en absoluto en messages.create() (ni
        # Vertex ni directo) — confirmado inspeccionando la firma real, no es un olvido. El
        # control de determinismo del modelo pasó a `output_config.effort`, que no es
        # equivalente. `evals/judge.py` documenta esto: el determinismo del juez ya no se puede
        # asumir por `temperature=0`, por eso importa más reportar varianza entre semillas.
        return await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            timeout=self._timeout,
        )

    async def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
        **params: Any,
    ) -> ProviderResult:
        response = await self._create(
            max_tokens=int(params.get("max_output_tokens") or 1024),
            system=system_blocks(system, str(params.get("instructions") or "")),
            messages=to_anthropic_messages(messages),
            tools=list(tools),
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )

        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_tokens=getattr(response.usage, "cache_read_input_tokens", None) or 0,
        )

        return ProviderResult(
            text="\n".join(text_parts),
            tool_calls=tuple(tool_calls),
            usage=usage,
            stop_reason=response.stop_reason or "end_turn",
        )

    async def stream(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
        **params: Any,
    ) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=int(params.get("max_output_tokens") or 1024),
            system=system_blocks(system, str(params.get("instructions") or "")),
            messages=to_anthropic_messages(messages),
            tools=list(tools),
            timeout=self._timeout,
        ) as stream:
            async for text in stream.text_stream:
                yield text

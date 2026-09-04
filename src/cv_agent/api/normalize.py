"""`input` (str | ItemParam[]) -> lista de `Message` internos + instrucciones de baja prioridad.

Los roles `system`/`developer` y el campo `instructions` no entran a la conversación: se
concatenan en `client_instructions`, que el proveedor manda como bloque de system SIN cachear,
después del corpus cacheado (menor prioridad, agent/loop.py)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from cv_agent.providers.base import Message, ToolCall
from cv_agent.schemas.requests import (
    AssistantMessageItem,
    CompactionItem,
    DeveloperMessageItem,
    FunctionCallItem,
    FunctionCallOutputItem,
    InputAudioPart,
    InputFilePart,
    InputImagePart,
    InputItem,
    InputTextPart,
    ItemReferenceItem,
    OutputTextPart,
    ReasoningItem,
    SystemMessageItem,
    UserMessageItem,
)

log = structlog.get_logger()

_ContentPart = InputTextPart | InputImagePart | InputFilePart | InputAudioPart | OutputTextPart


@dataclass(frozen=True)
class NormalizedInput:
    messages: list[Message]
    client_instructions: str


def _text_from_parts(content: str | Sequence[_ContentPart]) -> str:
    if isinstance(content, str):
        return content
    chunks: list[str] = []
    for part in content:
        if isinstance(part, InputTextPart | OutputTextPart):
            chunks.append(part.text)
        else:
            chunks.append(f"[{part.type} omitido: multimodal no soportado]")
    return "\n".join(chunks)


def _safe_json_loads(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_input(input_: str | Sequence[InputItem], instructions: str | None) -> NormalizedInput:
    client_instructions: list[str] = [instructions] if instructions else []

    if isinstance(input_, str):
        return NormalizedInput(
            messages=[Message(role="user", content=input_)],
            client_instructions="\n\n".join(client_instructions),
        )

    messages: list[Message] = []
    for item in input_:
        if isinstance(item, SystemMessageItem | DeveloperMessageItem):
            client_instructions.append(_text_from_parts(item.content))
        elif isinstance(item, UserMessageItem):
            messages.append(Message(role="user", content=_text_from_parts(item.content)))
        elif isinstance(item, AssistantMessageItem):
            messages.append(Message(role="assistant", content=_text_from_parts(item.content)))
        elif isinstance(item, FunctionCallItem):
            tool_call = ToolCall(
                id=item.call_id, name=item.name, arguments=_safe_json_loads(item.arguments)
            )
            messages.append(Message(role="assistant", tool_calls=(tool_call,)))
        elif isinstance(item, FunctionCallOutputItem):
            messages.append(Message(role="tool", content=item.output, tool_call_id=item.call_id))
        elif isinstance(item, ReasoningItem):
            log.debug("normalize_skip_reasoning_item")
        elif isinstance(item, ItemReferenceItem):
            log.warning("normalize_skip_item_reference", item_id=item.id)
        elif isinstance(item, CompactionItem):
            log.warning("normalize_skip_compaction_item")

    return NormalizedInput(messages=messages, client_instructions="\n\n".join(client_instructions))

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import structlog

from cv_agent.agent.tools import TOOL_SCHEMAS, ToolContext, execute_tool
from cv_agent.obs.metrics import metrics
from cv_agent.providers.base import Message, Provider, ToolCall, Usage

log = structlog.get_logger()

DEGRADED_MESSAGE = (
    "No pude completar la respuesta dentro del número máximo de pasos permitidos. "
    "Con lo que reuní hasta ahora: {last_text}"
)


@dataclass(frozen=True)
class LoopResult:
    text: str
    messages: tuple[Message, ...]
    iterations: int
    stop_reason: str
    usage: Usage = field(default_factory=Usage)


async def run(
    provider: Provider,
    system: str,
    messages: Sequence[Message],
    ctx: ToolContext,
    *,
    max_iterations: int = 6,
    instructions: str = "",
    max_output_tokens: int | None = None,
) -> LoopResult:
    """`instructions`: texto de menor prioridad (campo `instructions` del cliente + mensajes
    `system`/`developer` del `input`) — se pasa al proveedor como bloque de system NO cacheado,
    separado del corpus cacheado (`system`), para no romper el prefijo cacheable con contenido
    que cambia por request (ARCHITECTURE.md §1 y §3, `docs/platform-contract.md`)."""
    history = list(messages)
    last_text = ""
    input_tokens = output_tokens = cached_tokens = 0

    for iteration in range(1, max_iterations + 1):
        result = await provider.complete(
            system,
            history,
            TOOL_SCHEMAS,
            instructions=instructions,
            max_output_tokens=max_output_tokens,
        )
        input_tokens += result.usage.input_tokens
        output_tokens += result.usage.output_tokens
        cached_tokens += result.usage.cached_tokens
        if result.text:
            last_text = result.text

        log.info(
            "agent_iteration",
            iteration=iteration,
            tool_calls=[tc.name for tc in result.tool_calls],
            stop_reason=result.stop_reason,
        )

        usage = Usage(
            input_tokens=input_tokens, output_tokens=output_tokens, cached_tokens=cached_tokens
        )

        if not result.tool_calls:
            history.append(Message(role="assistant", content=result.text))
            return LoopResult(
                text=result.text,
                messages=tuple(history),
                iterations=iteration,
                stop_reason=result.stop_reason,
                usage=usage,
            )

        history.append(Message(role="assistant", content=result.text, tool_calls=result.tool_calls))
        outputs = await asyncio.gather(*(_run_tool(tc, ctx) for tc in result.tool_calls))
        for tool_call, output in zip(result.tool_calls, outputs, strict=True):
            history.append(
                Message(
                    role="tool",
                    content=output,
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                )
            )

    degraded = DEGRADED_MESSAGE.format(last_text=last_text or "no reuní información suficiente.")
    history.append(Message(role="assistant", content=degraded))
    log.warning("agent_max_iterations", max_iterations=max_iterations)
    return LoopResult(
        text=degraded,
        messages=tuple(history),
        iterations=max_iterations,
        stop_reason="max_iterations",
        usage=Usage(
            input_tokens=input_tokens, output_tokens=output_tokens, cached_tokens=cached_tokens
        ),
    )


async def _run_tool(tool_call: ToolCall, ctx: ToolContext) -> str:
    start = time.perf_counter()
    try:
        output = await execute_tool(tool_call.name, tool_call.arguments, ctx)
        ok = True
    except Exception as exc:  # noqa: BLE001 — el error vuelve al modelo como texto, no como excepción
        output = f"Error ejecutando {tool_call.name}: {exc}"
        ok = False
    duration_ms = (time.perf_counter() - start) * 1000
    log.info("tool_call", name=tool_call.name, ok=ok, duration_ms=round(duration_ms, 1))
    metrics.record_tool_call(tool_call.name)
    return output

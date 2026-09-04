"""`POST /v1/responses` — el contrato del spec, sin creatividad (ARCHITECTURE.md §0)."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from cv_agent.agent.loop import LoopResult
from cv_agent.agent.loop import run as run_agent
from cv_agent.api.app_state import AppState, get_app_state
from cv_agent.api.auth import require_bearer
from cv_agent.api.errors import ApiError, PreviousResponseNotFoundError
from cv_agent.api.normalize import normalize_input
from cv_agent.api.ratelimit import rate_limit
from cv_agent.api.sse import EventStream
from cv_agent.config import settings
from cv_agent.obs.metrics import metrics
from cv_agent.providers.base import Message
from cv_agent.providers.base import Usage as ProviderUsage
from cv_agent.schemas.requests import (
    CreateResponseBody,
    InputAudioPart,
    InputFilePart,
    InputImagePart,
    UserMessageItem,
)
from cv_agent.schemas.responses import (
    OutputMessage,
    OutputTextContent,
    Response,
    Usage,
    UsageInputDetails,
)

log = structlog.get_logger()

router = APIRouter()

# Determinista, no una decisión del modelo: así la razón siempre se comunica igual y no cuesta
# una llamada al proveedor. Los toggles de imagen/archivo de la plataforma están apagados por defecto
# (docs/platform-contract.md §5); esto cubre el caso de que alguien los prenda de todos modos.
UNSUPPORTED_MODALITY_MESSAGE = (
    "Este agente no procesa imágenes ni audio todavía. Dado el propósito de este proyecto — un "
    "agente conversacional sobre un CV — agregar esa modalidad ahora sería complejidad "
    "especulativa sin un caso de uso claro. Si una prueba posterior de la evaluación la requiere, "
    "se implementará entonces."
)

_UNSUPPORTED_PART_TYPES = (InputImagePart, InputFilePart, InputAudioPart)


def _requests_unsupported_modality(body: CreateResponseBody) -> bool:
    if isinstance(body.input, str):
        return False
    return any(
        isinstance(item, UserMessageItem)
        and not isinstance(item.content, str)
        and any(isinstance(part, _UNSUPPORTED_PART_TYPES) for part in item.content)
        for item in body.input
    )


def _clamp_max_output_tokens(requested: int | None) -> int:
    cap = settings.max_output_tokens_cap
    return min(requested, cap) if requested is not None else cap


def _log_request_shape(request: Request, body: CreateResponseBody) -> None:
    """Única fuente de evidencia real para docs/platform-contract.md §8 (preguntas 1,3,4,5).
    Debe vivir en el handler, no en middleware: `request.body()` agota el stream ahí."""
    log.info(
        "request_shape",
        stream=body.stream,
        model=body.model,
        input_kind="str" if isinstance(body.input, str) else "items",
        n_items=None if isinstance(body.input, str) else len(body.input),
        has_previous_response_id=bool(body.previous_response_id),
        has_instructions=bool(body.instructions),
        n_tools=len(body.tools),
        extra_keys=sorted(body.model_extra or {}),
        user_agent=request.headers.get("user-agent"),
    )


def _resolve_history(state: AppState, body: CreateResponseBody) -> tuple[list[Message], str]:
    normalized = normalize_input(body.input, body.instructions)
    history: list[Message] = []
    if body.previous_response_id:
        prev = state.response_store.get(body.previous_response_id)
        if prev is None:
            raise PreviousResponseNotFoundError(body.previous_response_id)
        history.extend(prev)
    history.extend(normalized.messages)
    return history, normalized.client_instructions


def _to_response_usage(usage: ProviderUsage) -> Usage:
    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.input_tokens + usage.output_tokens,
        input_tokens_details=UsageInputDetails(cached_tokens=usage.cached_tokens),
    )


def _build_response(
    body: CreateResponseBody,
    response_id: str,
    created_at: int,
    *,
    status: str = "completed",
    completed_at: int | None = None,
    text: str = "",
    usage: ProviderUsage | None = None,
) -> Response:
    output = (
        [OutputMessage(id=f"msg_{uuid.uuid4().hex}", content=[OutputTextContent(text=text)])]
        if status == "completed"
        else []
    )
    return Response(
        id=response_id,
        created_at=created_at,
        completed_at=completed_at,
        status=status,  # type: ignore[arg-type]
        model=body.model or settings.model_id,
        previous_response_id=body.previous_response_id,
        instructions=body.instructions,
        output=output,
        tools=body.tools,
        tool_choice=body.tool_choice if body.tool_choice is not None else "auto",
        truncation=body.truncation,
        top_p=body.top_p,
        temperature=body.temperature,
        usage=_to_response_usage(usage) if usage is not None else Usage(),
        max_output_tokens=body.max_output_tokens,
        store=body.store,
        metadata=body.metadata,
    )


async def _run_agent_or_decline(
    state: AppState,
    body: CreateResponseBody,
    history: list[Message],
    client_instructions: str,
) -> LoopResult:
    if _requests_unsupported_modality(body):
        return LoopResult(
            text=UNSUPPORTED_MODALITY_MESSAGE, messages=(), iterations=0, stop_reason="end_turn"
        )
    assert state.provider is not None  # el llamador ya validó esto
    return await run_agent(
        state.provider,
        state.system_prompt,
        history,
        state.tool_ctx,
        max_iterations=settings.max_loop_iterations,
        instructions=client_instructions,
        max_output_tokens=_clamp_max_output_tokens(body.max_output_tokens),
    )


@router.post(
    "/responses",
    dependencies=[Depends(require_bearer), Depends(rate_limit)],
    response_model=None,
)
async def create_response(
    body: CreateResponseBody,
    request: Request,
    state: Annotated[AppState, Depends(get_app_state)],
) -> Response | StreamingResponse:
    if body.background:
        # No implementamos `background: true` (opcional del spec).
        raise ApiError(
            "background=true no está soportado por este agente.",
            type="invalid_request",
            param="background",
            code="unsupported_parameter",
        )

    _log_request_shape(request, body)
    history, client_instructions = _resolve_history(state, body)

    if state.provider is None:
        raise ApiError("El proveedor del modelo no está configurado.", type="server_error")

    response_id = f"resp_{uuid.uuid4().hex}"
    created_at = int(time.time())

    if body.stream:
        return StreamingResponse(
            _stream_response(
                state, body, history, client_instructions, response_id, created_at, request
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    result = await _run_agent_or_decline(state, body, history, client_instructions)
    metrics.record_usage(
        input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens
    )

    if body.store:
        state.response_store.put(response_id, result.messages)

    return _build_response(
        body,
        response_id,
        created_at,
        completed_at=int(time.time()),
        text=result.text,
        usage=result.usage,
    )


async def _stream_response(
    state: AppState,
    body: CreateResponseBody,
    history: list[Message],
    client_instructions: str,
    response_id: str,
    created_at: int,
    request: Request,
) -> AsyncIterator[str]:
    """SSE *bufferizado* — se genera la respuesta completa y luego se emite la secuencia entera
    de una vez. Spec-válido (eventos, orden y `sequence_number` correctos); deltas reales token a
    token es una mejora de latencia percibida, no de correctitud, y queda pendiente para cuando
    el loop soporte streaming real con tool-use intercalado (docs/platform-contract.md §0)."""
    ev = EventStream()

    try:
        result = await _run_agent_or_decline(state, body, history, client_instructions)
    except Exception:
        log.exception("stream_generation_failed")
        yield ev.emit(
            "response.failed",
            response={"id": response_id, "status": "failed"},
            error={"message": "Error interno.", "type": "server_error", "code": None},
        )
        yield EventStream.done()
        return

    metrics.record_usage(
        input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens
    )

    if await request.is_disconnected():
        return

    if body.store:
        state.response_store.put(response_id, result.messages)

    completed_at = int(time.time())
    completed_obj = _build_response(
        body,
        response_id,
        created_at,
        completed_at=completed_at,
        text=result.text,
        usage=result.usage,
    )
    in_progress_obj = completed_obj.model_copy(update={"status": "in_progress", "output": []})
    item_stub = {
        "type": "message",
        "id": completed_obj.output[0].id,
        "status": "in_progress",
        "role": "assistant",
        "content": [],
    }
    item_final = completed_obj.output[0].model_dump(mode="json")

    yield ev.emit("response.created", response=in_progress_obj.model_dump(mode="json"))
    yield ev.emit("response.in_progress", response=in_progress_obj.model_dump(mode="json"))

    # Evento propio, fuera del spec (namespaced con "cv_agent." para no confundirse con eventos
    # reales de Open Responses) — las herramientas son internally-hosted y el spec no las expone
    # al cliente; esto es solo para que web/index.html pueda mostrar en vivo qué se llamó.
    for message in result.messages:
        if message.role == "assistant":
            for tool_call in message.tool_calls:
                yield ev.emit("cv_agent.tool_call", name=tool_call.name)

    yield ev.emit("response.output_item.added", output_index=0, item=item_stub)
    yield ev.emit(
        "response.content_part.added",
        output_index=0,
        content_index=0,
        part={"type": "output_text", "text": "", "annotations": []},
    )
    yield ev.emit("response.output_text.delta", output_index=0, content_index=0, delta=result.text)
    yield ev.emit("response.output_text.done", output_index=0, content_index=0, text=result.text)
    yield ev.emit(
        "response.content_part.done",
        output_index=0,
        content_index=0,
        part={"type": "output_text", "text": result.text, "annotations": []},
    )
    yield ev.emit("response.output_item.done", output_index=0, item=item_final)
    yield ev.emit("response.completed", response=completed_obj.model_dump(mode="json"))
    yield EventStream.done()

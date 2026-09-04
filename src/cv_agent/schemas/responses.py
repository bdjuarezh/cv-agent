"""Objeto `Response` con TODOS los campos required del spec, siempre presentes aunque sean
`null` — un cliente estricto que valide contra el OpenAPI falla por una llave faltante, nunca
por una de más (verificado contra el OpenAPI real de openresponses.org)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

REQUIRED_FIELDS = frozenset(
    {
        "id",
        "object",
        "created_at",
        "completed_at",
        "status",
        "incomplete_details",
        "model",
        "previous_response_id",
        "instructions",
        "output",
        "error",
        "tools",
        "tool_choice",
        "truncation",
        "parallel_tool_calls",
        "text",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "top_logprobs",
        "temperature",
        "reasoning",
        "usage",
        "max_output_tokens",
        "max_tool_calls",
        "store",
        "background",
        "service_tier",
        "metadata",
        "safety_identifier",
        "prompt_cache_key",
    }
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OutputTextContent(_Base):
    type: Literal["output_text"] = "output_text"
    text: str
    annotations: list[dict[str, Any]] = Field(default_factory=list)


class OutputMessage(_Base):
    type: Literal["message"] = "message"
    id: str
    status: Literal["in_progress", "completed", "incomplete"] = "completed"
    role: Literal["assistant"] = "assistant"
    content: list[OutputTextContent] = Field(default_factory=list)


class UsageInputDetails(_Base):
    cached_tokens: int = 0


class UsageOutputDetails(_Base):
    reasoning_tokens: int = 0


class Usage(_Base):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_tokens_details: UsageInputDetails = Field(default_factory=UsageInputDetails)
    output_tokens_details: UsageOutputDetails = Field(default_factory=UsageOutputDetails)


class ErrorDetail(_Base):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class Response(_Base):
    id: str
    object: Literal["response"] = "response"
    created_at: int
    completed_at: int | None = None
    status: Literal["queued", "in_progress", "completed", "failed", "incomplete"] = "completed"
    incomplete_details: dict[str, Any] | None = None
    model: str
    previous_response_id: str | None = None
    instructions: str | None = None
    output: list[OutputMessage] = Field(default_factory=list)
    error: ErrorDetail | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: Any = "auto"
    truncation: Literal["auto", "disabled"] = "auto"
    parallel_tool_calls: bool = True
    text: dict[str, Any] = Field(default_factory=dict)
    top_p: float | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    top_logprobs: int | None = None
    temperature: float | None = None
    reasoning: dict[str, Any] | None = None
    usage: Usage = Field(default_factory=Usage)
    max_output_tokens: int | None = None
    max_tool_calls: int | None = None
    store: bool = True
    background: bool = False
    service_tier: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    safety_identifier: str | None = None
    prompt_cache_key: str | None = None

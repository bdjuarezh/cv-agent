"""Modelos del request de POST /v1/responses. Estricto al emitir, permisivo al aceptar
(CLAUDE.md regla 2): `extra="allow"` en el body para nunca fallar por un campo desconocido —
la plataforma ya inyecta parámetros extra (`docs/platform-contract.md` §3)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class InputTextPart(_Base):
    type: Literal["input_text"] = "input_text"
    text: str


class InputImagePart(_Base):
    type: Literal["input_image"] = "input_image"
    image_url: str | None = None
    detail: Literal["low", "high", "auto"] = "auto"


class InputFilePart(_Base):
    type: Literal["input_file"] = "input_file"
    file_data: str | None = None
    file_url: str | None = None
    filename: str | None = None


class OutputTextPart(_Base):
    type: Literal["output_text"] = "output_text"
    text: str
    annotations: list[dict[str, Any]] = Field(default_factory=list)


InputContentPart = Annotated[
    InputTextPart | InputImagePart | InputFilePart,
    Field(discriminator="type"),
]


class UserMessageItem(_Base):
    type: Literal["message"] = "message"
    role: Literal["user"] = "user"
    content: str | list[InputContentPart]


class SystemMessageItem(_Base):
    type: Literal["message"] = "message"
    role: Literal["system"] = "system"
    content: str | list[InputTextPart]


class DeveloperMessageItem(_Base):
    type: Literal["message"] = "message"
    role: Literal["developer"] = "developer"
    content: str | list[InputTextPart]


class AssistantMessageItem(_Base):
    type: Literal["message"] = "message"
    role: Literal["assistant"] = "assistant"
    content: str | list[OutputTextPart]


MessageItem = Annotated[
    UserMessageItem | SystemMessageItem | DeveloperMessageItem | AssistantMessageItem,
    Field(discriminator="role"),
]


class FunctionCallItem(_Base):
    type: Literal["function_call"] = "function_call"
    call_id: str
    name: str
    arguments: str = "{}"


class FunctionCallOutputItem(_Base):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    output: str


class ReasoningItem(_Base):
    type: Literal["reasoning"] = "reasoning"
    content: list[dict[str, Any]] = Field(default_factory=list)
    summary: list[dict[str, Any]] = Field(default_factory=list)
    encrypted_content: str | None = None


class ItemReferenceItem(_Base):
    type: Literal["item_reference"] = "item_reference"
    id: str


class CompactionItem(_Base):
    """Aceptado sin romper — no implementamos `/v1/responses/compact` (CLAUDE.md, opcional del
    spec). Ver api/normalize.py: se omite con un log, no se re-expande."""

    type: Literal["compaction"] = "compaction"
    encrypted_content: str | None = None


InputItem = Annotated[
    MessageItem
    | FunctionCallItem
    | FunctionCallOutputItem
    | ReasoningItem
    | ItemReferenceItem
    | CompactionItem,
    Field(discriminator="type"),
]


class CreateResponseBody(_Base):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _default_item_type(cls, data: object) -> object:
        """Ítems de `input` sin `type` (solo `role`+`content`): una implementación aceptada para
        este puesto los manda así. Sin este default, la unión discriminada devuelve 422 y el
        agente queda inutilizable ante ese cliente (docs/platform-contract.md §11)."""
        if isinstance(data, dict) and isinstance(data.get("input"), list):
            for item in data["input"]:
                if isinstance(item, dict) and "type" not in item and "role" in item:
                    item["type"] = "message"
        return data

    @model_validator(mode="after")
    def _check_metadata_size(self) -> CreateResponseBody:
        if len(self.metadata) > 16:
            raise ValueError("metadata acepta a lo más 16 pares clave/valor")
        return self

    model: str | None = None
    input: str | list[InputItem]
    instructions: str | None = None
    stream: bool = False
    background: bool = False
    previous_response_id: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: Any = None
    store: bool = True
    truncation: Literal["auto", "disabled"] = "auto"
    metadata: dict[str, str] = Field(default_factory=dict)

from __future__ import annotations

import json
from typing import Any


class EventStream:
    """`event:` == `type` del JSON, `sequence_number` monótonamente creciente, `[DONE]` terminal
    y sin `id:` (01_ARQUITECTURA.md §1)."""

    def __init__(self) -> None:
        self.seq = 0

    def emit(self, type_: str, **fields: Any) -> str:
        self.seq += 1
        payload = {"type": type_, "sequence_number": self.seq, **fields}
        return f"event: {type_}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def done() -> str:
        return "data: [DONE]\n\n"

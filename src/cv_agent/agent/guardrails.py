from __future__ import annotations

import re
from dataclasses import dataclass

_INJECTION_PATTERNS = [
    r"ignora(?:r)?\s+(tus|las)\s+instruccion",
    r"olvida(?:r)?\s+(tus|las)\s+(reglas|instruccion)",
    r"act[uú]a\s+como",
    r"eres\s+ahora",
    r"system\s*prompt",
    r"nuevas?\s+instruccion",
    r"disregard\s+(your|previous)\s+instructions",
    r"ignore\s+(your|previous|all)\s+instructions",
]

_OUT_OF_SCOPE_HINTS = [
    r"escr\w*be\w*\s+(un|una)\s+(script|c[oó]digo|programa)",
    r"resuelve\s+mi\s+tarea",
    r"h[aá]zme\s+la\s+tarea",
]


@dataclass(frozen=True)
class InputCheck:
    flagged: bool
    reason: str | None = None


def check_input(text: str) -> InputCheck:
    """Heurística barata de primera línea, sobre el input crudo del usuario.

    No reemplaza un clasificador LLM (evals/judge.py en Fase 5 mide la tasa real de fallos de
    inyección): solo atrapa los patrones más obvios para loguearlos. La defensa real vive en la
    jerarquía de instrucciones del system prompt (agent/prompts.py::ANTI_INJECTION).
    """
    lowered = text.lower()
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            return InputCheck(flagged=True, reason="posible_inyeccion")
    for pattern in _OUT_OF_SCOPE_HINTS:
        if re.search(pattern, lowered):
            return InputCheck(flagged=True, reason="fuera_de_alcance")
    return InputCheck(flagged=False)


def check_groundedness(response_text: str, corpus: str) -> bool | None:
    """Placeholder deliberado: la verificación real de groundedness es un juez LLM
    (evals/judge.py, Fase 5). Devuelve None ("no evaluado") en vez de fingir una garantía que
    esta heurística no puede dar.
    """
    return None

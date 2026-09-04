"""Estado conversacional para `previous_response_id` (ARCHITECTURE.md §3).

Guardamos, por `response_id`, el historial interno completo (`tuple[Message, ...]`) tal como
quedó al terminar ese turno — ya es exactamente `prev.input + prev.output` en orden, así que
reconstruir un turno nuevo es solo `stored + nuevos_mensajes`, sin tener que re-normalizar nada.

`TTLCacheStore` + 1 instancia (`--max-instances=1`) es la limitación asumida documentada; si la
plataforma resulta usar reproducción de transcripción en vez de `previous_response_id`, el
servicio es stateless de facto y esta limitación deja de aplicar (docs/platform-contract.md §4).
"""

from __future__ import annotations

from typing import Protocol

from cachetools import TTLCache

from cv_agent.providers.base import Message


class ResponseStore(Protocol):
    def get(self, response_id: str) -> tuple[Message, ...] | None: ...
    def put(self, response_id: str, messages: tuple[Message, ...]) -> None: ...


class TTLCacheStore:
    def __init__(self, maxsize: int = 5000, ttl: int = 3600) -> None:
        self._cache: TTLCache[str, tuple[Message, ...]] = TTLCache(maxsize=maxsize, ttl=ttl)

    def get(self, response_id: str) -> tuple[Message, ...] | None:
        return self._cache.get(response_id)

    def put(self, response_id: str, messages: tuple[Message, ...]) -> None:
        self._cache[response_id] = messages

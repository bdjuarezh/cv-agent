"""Contadores agregados en memoria para `GET /metrics`. Un proceso, `--max-instances=1` (D10) —
si eso cambia, esto deja de ser la fuente de verdad y hay que migrar a Cloud Monitoring."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field

# Precios de referencia (USD por token) — Sonnet-clase, orden de magnitud para el estimado.
_COST_PER_INPUT_TOKEN = 3e-6
_COST_PER_OUTPUT_TOKEN = 15e-6


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * pct / 100))
    return round(sorted_values[idx], 1)


@dataclass
class Metrics:
    _latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    _requests: int = 0
    _errors: int = 0
    _input_tokens: int = 0
    _output_tokens: int = 0
    _tool_calls: Counter[str] = field(default_factory=Counter)

    def record_request(self, *, duration_ms: float, status_code: int) -> None:
        self._requests += 1
        self._latencies_ms.append(duration_ms)
        if status_code >= 500 or status_code == 429:
            self._errors += 1

    def record_usage(self, *, input_tokens: int, output_tokens: int) -> None:
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens

    def record_tool_call(self, name: str) -> None:
        self._tool_calls[name] += 1

    def snapshot(self) -> dict[str, object]:
        latencies = sorted(self._latencies_ms)
        cost = self._input_tokens * _COST_PER_INPUT_TOKEN
        cost += self._output_tokens * _COST_PER_OUTPUT_TOKEN
        return {
            "requests_total": self._requests,
            "errors_total": self._errors,
            "error_rate": round(self._errors / self._requests, 4) if self._requests else 0.0,
            "latency_ms_p50": _percentile(latencies, 50),
            "latency_ms_p95": _percentile(latencies, 95),
            "tokens_input_total": self._input_tokens,
            "tokens_output_total": self._output_tokens,
            "estimated_cost_usd": round(cost, 4),
            "tool_calls": dict(self._tool_calls),
        }

    def reset(self) -> None:
        """Solo para tests — en producción los contadores viven mientras viva el proceso."""
        self._latencies_ms.clear()
        self._requests = 0
        self._errors = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._tool_calls.clear()


metrics = Metrics()

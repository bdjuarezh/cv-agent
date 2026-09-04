"""Rigor estadístico de las evals (ARCHITECTURE.md §5) — nunca reportar una tasa puntual sin
su intervalo."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z**2 / n
    center = p + z**2 / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return ((center - half) / denom, (center + half) / denom)


def cohens_kappa(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    if n == 0 or n != len(b):
        return 0.0
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe >= 1 else (po - pe) / (1 - pe)


@dataclass(frozen=True)
class CategoryStats:
    category: str
    n: int
    successes: int
    wilson_low: float
    wilson_high: float
    rate_mean: float
    rate_std: float

    @property
    def rate(self) -> float:
        return self.successes / self.n if self.n else 0.0


def aggregate_by_category(per_seed_results: list[list[tuple[str, bool]]]) -> list[CategoryStats]:
    """`per_seed_results[s]` es la lista (category, passed) de la semilla `s`. El IC de Wilson se
    calcula sobre el total (todas las semillas juntas); la media±σ es entre semillas, no dentro
    de una — así se ve tanto la confianza estadística como la varianza real del modelo."""
    pooled: dict[str, list[bool]] = defaultdict(list)
    per_seed_rate: dict[str, list[float]] = defaultdict(list)

    for seed_results in per_seed_results:
        seed_by_cat: dict[str, list[bool]] = defaultdict(list)
        for category, passed in seed_results:
            pooled[category].append(passed)
            seed_by_cat[category].append(passed)
        for category, values in seed_by_cat.items():
            per_seed_rate[category].append(sum(values) / len(values))

    stats: list[CategoryStats] = []
    for category in sorted(pooled):
        values = pooled[category]
        n = len(values)
        successes = sum(values)
        low, high = wilson_interval(successes, n)
        rates = per_seed_rate[category]
        mean = statistics.fmean(rates) if rates else 0.0
        std = statistics.pstdev(rates) if len(rates) > 1 else 0.0
        stats.append(
            CategoryStats(
                category=category,
                n=n,
                successes=successes,
                wilson_low=round(low, 3),
                wilson_high=round(high, 3),
                rate_mean=round(mean, 3),
                rate_std=round(std, 3),
            )
        )
    return stats

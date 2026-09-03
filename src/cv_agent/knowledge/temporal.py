from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from cv_agent.knowledge.models import Experience, Project

Interval = tuple[date, date]


def merge_intervals(spans: Sequence[Interval]) -> list[Interval]:
    """Fusiona intervalos solapados o adyacentes. O(n log n) por el ordenamiento."""
    out: list[Interval] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def total_years(spans: Sequence[Interval]) -> float:
    """Años de la UNIÓN de los intervalos, no de su suma. Roles traslapados no se cuentan dos veces."""
    months = sum(
        (end.year - start.year) * 12 + (end.month - start.month)
        for start, end in merge_intervals(spans)
    )
    return round(months / 12, 1)


def overlap(a: Interval, b: Interval) -> Interval | None:
    """Intersección de dos intervalos, o None si no se traslapan."""
    start = max(a[0], b[0])
    end = min(a[1], b[1])
    if start > end:
        return None
    return (start, end)


def years_with_skill(
    skill: str,
    experiences: Sequence[Experience],
    projects: Sequence[Project] = (),
    *,
    today: date | None = None,
) -> float:
    """Años de experiencia con `skill`, fusionando intervalos traslapados de roles y proyectos.

    Un proyecto solo trae `year`, no un rango: se trata como el año calendario completo
    (1 ene - 31 dic) — una aproximación razonable para un dato de grano anual.
    """
    resolved_today = today or date.today()  # noqa: DTZ011 — fecha calendario, no timestamp
    # Comparación insensible a mayúsculas: el modelo suele pasar el nombre "propio" del skill
    # (p. ej. "Python", como aparece en skills.yaml), mientras que `stack` en experience.yaml /
    # projects.yaml usa minúsculas por convención — sin esto, compute_years devolvía 0 años de
    # forma silenciosa en vez de fallar, el peor tipo de error para una herramienta que existe
    # justo para ser confiable (encontrado probando con el proveedor real).
    skill_lower = skill.lower()
    spans: list[Interval] = [
        (exp.start, exp.end or resolved_today)
        for exp in experiences
        if skill_lower in {s.lower() for s in exp.stack}
    ]
    spans += [
        (date(p.year, 1, 1), date(p.year, 12, 31))
        for p in projects
        if skill_lower in {s.lower() for s in p.stack}
    ]
    return total_years(spans)

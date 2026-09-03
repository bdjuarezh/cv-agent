from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from cv_agent.knowledge.retrieval.base import Retriever
from cv_agent.knowledge.store import KnowledgeStore
from cv_agent.knowledge.temporal import years_with_skill


@dataclass(frozen=True)
class ToolContext:
    store: KnowledgeStore
    retriever: Retriever


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_profile",
        "description": (
            "Busca en la narrativa larga del perfil (historia profesional, filosofía de "
            "trabajo, por qué IA) fragmentos relevantes a una consulta libre. Úsalo para "
            "preguntas abiertas que el resto de herramientas no cubre."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Consulta en lenguaje natural."},
                "k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_experience",
        "description": "Roles laborales, opcionalmente filtrados por empresa, stack o años.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string"},
                "stack": {"type": "string", "description": "Una tecnología, p. ej. 'pyspark'."},
                "from_year": {"type": "integer"},
                "to_year": {"type": "integer"},
            },
        },
    },
    {
        "name": "get_projects",
        "description": "Proyectos, opcionalmente filtrados por tecnología o año.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tech": {"type": "string"},
                "year": {"type": "integer"},
                "limit": {"type": "integer", "minimum": 1},
            },
        },
    },
    {
        "name": "get_skills",
        "description": "Habilidades, opcionalmente filtradas por categoría o nivel mínimo (1-5).",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "min_level": {"type": "integer", "minimum": 1, "maximum": 5},
            },
        },
    },
    {
        "name": "compute_years",
        "description": (
            "Años de experiencia con una tecnología/skill, calculados de forma determinista "
            "sobre la UNIÓN de los periodos en los que aparece (roles y proyectos traslapados "
            "no se cuentan dos veces). Úsalo siempre para preguntas de 'cuántos años'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"skill": {"type": "string"}},
            "required": ["skill"],
        },
    },
    {
        "name": "get_contact",
        "description": "Canales de contacto públicos. Nunca incluye datos marcados como privados.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


async def _search_profile(ctx: ToolContext, query: str, k: int = 5) -> list[dict[str, Any]]:
    """BM25 + denso (si hay Vertex) + RRF + MMR, vía `ctx.retriever`
    (`knowledge/retrieval/local.py`) — herramienta de respaldo, no el camino crítico
    (01_ARQUITECTURA.md §2)."""
    chunks = await ctx.retriever.search(query, k=k)
    return [{"chunk_id": c.chunk_id, "source": c.source, "text": c.text} for c in chunks]


def _get_experience(
    ctx: ToolContext,
    company: str | None = None,
    stack: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
) -> list[dict[str, Any]]:
    experiences = ctx.store.experiences(company=company, stack=stack, from_=from_year, to=to_year)
    return [
        {
            "id": e.id,
            "company": e.company,
            "role": e.role,
            "start": e.start.isoformat()[:7],
            "end": e.end.isoformat()[:7] if e.end else None,
            "stack": e.stack,
            "summary": e.summary,
            "achievements": [
                {
                    "text": a.text,
                    "metric": {"value": a.metric.value, "unit": a.metric.unit}
                    if a.metric
                    else None,
                }
                for a in e.achievements
            ],
        }
        for e in experiences
    ]


def _get_projects(
    ctx: ToolContext,
    tech: str | None = None,
    year: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    projects = ctx.store.projects(tech=tech, year=year)
    if limit is not None:
        projects = projects[:limit]
    return [
        {
            "id": p.id,
            "name": p.name,
            "year": p.year,
            "role": p.role,
            "problem": p.problem,
            "approach": p.approach,
            "stack": p.stack,
            "outcome": p.outcome,
            "links": p.links,
        }
        for p in projects
    ]


def _get_skills(
    ctx: ToolContext, category: str | None = None, min_level: int | None = None
) -> list[dict[str, Any]]:
    return [
        {"name": s.name, "category": s.category, "level": s.level, "evidence": s.evidence}
        for s in ctx.store.skills(category=category, min_level=min_level)
    ]


def _compute_years(ctx: ToolContext, skill: str) -> dict[str, Any]:
    if not skill or not skill.strip():
        raise ValueError("compute_years requiere 'skill' no vacío")
    years = years_with_skill(skill, ctx.store.experiences(), ctx.store.projects())
    return {"skill": skill, "years": years}


def _get_contact(ctx: ToolContext) -> list[dict[str, Any]]:
    return [{"label": c.label, "value": c.value} for c in ctx.store.profile().contact if c.public]


_DISPATCH: dict[str, Callable[..., Any] | Callable[..., Awaitable[Any]]] = {
    "search_profile": _search_profile,
    "get_experience": _get_experience,
    "get_projects": _get_projects,
    "get_skills": _get_skills,
    "compute_years": _compute_years,
    "get_contact": _get_contact,
}


async def execute_tool(name: str, arguments: dict[str, Any], ctx: ToolContext) -> str:
    """Dispatch + serialización a texto. Cualquier excepción del tool debe capturarla el llamador
    (agent/loop.py) y devolverla al modelo como texto, nunca como excepción no controlada.
    Solo `search_profile` es async (llama a Vertex vía threadpool); el resto es en memoria."""
    func = _DISPATCH.get(name)
    if func is None:
        raise ValueError(f"herramienta desconocida: {name}")
    result = func(ctx, **arguments)
    if inspect.isawaitable(result):
        result = await result
    return json.dumps(result, ensure_ascii=False)

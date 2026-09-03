from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from cv_agent.knowledge.models import Experience, KnowledgeBase, Profile, Project, Skill


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_knowledge_base(data_dir: Path) -> KnowledgeBase:
    profile_data: dict[str, Any] = _load_yaml(data_dir / "profile.yaml") or {}
    experiences_data: list[dict[str, Any]] = _load_yaml(data_dir / "experience.yaml") or []
    projects_data: list[dict[str, Any]] = _load_yaml(data_dir / "projects.yaml") or []
    skills_data: list[dict[str, Any]] = _load_yaml(data_dir / "skills.yaml") or []

    return KnowledgeBase(
        profile=Profile(**profile_data),
        experiences=[Experience(**e) for e in experiences_data],
        projects=[Project(**p) for p in projects_data],
        skills=[Skill(**s) for s in skills_data],
    )


class KnowledgeStore:
    """Índice en memoria del KB, con queries estructuradas. Carga una sola vez en el lifespan."""

    def __init__(self, kb: KnowledgeBase) -> None:
        self._kb = kb

    def profile(self) -> Profile:
        return self._kb.profile

    def experiences(
        self,
        *,
        company: str | None = None,
        from_: int | None = None,
        to: int | None = None,
        stack: str | None = None,
    ) -> list[Experience]:
        result = list(self._kb.experiences)
        if company is not None:
            result = [e for e in result if e.company.lower() == company.lower()]
        if stack is not None:
            result = [e for e in result if stack.lower() in {s.lower() for s in e.stack}]
        if from_ is not None:
            result = [e for e in result if (e.end or e.start).year >= from_]
        if to is not None:
            result = [e for e in result if e.start.year <= to]
        return result

    def projects(self, *, tech: str | None = None, year: int | None = None) -> list[Project]:
        result = list(self._kb.projects)
        if tech is not None:
            result = [p for p in result if tech.lower() in {s.lower() for s in p.stack}]
        if year is not None:
            result = [p for p in result if p.year == year]
        return result

    def skills(self, *, category: str | None = None, min_level: int | None = None) -> list[Skill]:
        result = list(self._kb.skills)
        if category is not None:
            result = [s for s in result if s.category.lower() == category.lower()]
        if min_level is not None:
            result = [s for s in result if s.level >= min_level]
        return result

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, model_validator


def _parse_year_month(value: object) -> object:
    """Acepta 'YYYY-MM' (obligatorio en el KB) y lo ancla al día 1 del mes."""
    if isinstance(value, str):
        year_str, month_str = value.split("-")
        return date(int(year_str), int(month_str), 1)
    return value


YearMonth = Annotated[date, BeforeValidator(_parse_year_month)]


class Metric(BaseModel):
    value: float
    unit: str


class Achievement(BaseModel):
    text: str
    metric: Metric | None = None


class Experience(BaseModel):
    id: str
    company: str
    role: str
    start: YearMonth
    end: YearMonth | None = None
    location: str = ""
    summary: str = ""
    stack: list[str] = Field(default_factory=list)
    achievements: list[Achievement] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_range(self) -> Experience:
        if self.end is not None and self.end < self.start:
            raise ValueError(f"{self.id}: end ({self.end}) es anterior a start ({self.start})")
        return self


class Project(BaseModel):
    id: str
    name: str
    year: int
    role: str = ""
    problem: str = ""
    approach: str = ""
    stack: list[str] = Field(default_factory=list)
    outcome: str = ""
    links: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    name: str
    category: str
    level: int = Field(ge=1, le=5)
    evidence: list[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    degree: str
    year: int | None = None


class ContactChannel(BaseModel):
    label: str
    value: str
    public: bool = True


class Profile(BaseModel):
    name: str
    headline: str
    summary: str = ""
    education: list[Education] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    contact: list[ContactChannel] = Field(default_factory=list)
    pii_policy: str = ""


class KnowledgeBase(BaseModel):
    profile: Profile
    experiences: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_ids_and_evidence(self) -> KnowledgeBase:
        ids = [e.id for e in self.experiences] + [p.id for p in self.projects]
        dupes = {i for i in set(ids) if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"ids duplicados en experience/projects: {sorted(dupes)}")

        id_set = set(ids)
        for skill in self.skills:
            missing = [ref for ref in skill.evidence if ref not in id_set]
            if missing:
                raise ValueError(f"skill '{skill.name}': evidence sin id válido: {missing}")
        return self

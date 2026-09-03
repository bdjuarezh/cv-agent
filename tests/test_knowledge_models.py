import pytest
from pydantic import ValidationError

from cv_agent.knowledge.models import Experience, KnowledgeBase, Profile, Project, Skill


def _profile() -> Profile:
    return Profile(name="Jane Doe", headline="Ingeniera de IA")


def test_experience_parsea_year_month() -> None:
    exp = Experience(id="e1", company="C", role="R", start="2022-03")
    assert exp.start.year == 2022
    assert exp.start.month == 3
    assert exp.end is None


def test_experience_end_antes_de_start_falla() -> None:
    with pytest.raises(ValidationError):
        Experience(id="e1", company="C", role="R", start="2022-03", end="2021-01")


def test_skill_level_fuera_de_rango_falla() -> None:
    with pytest.raises(ValidationError):
        Skill(name="Python", category="lang", level=6)


def test_knowledge_base_ids_duplicados_falla() -> None:
    exp = Experience(id="dup", company="C", role="R", start="2020-01")
    proj = Project(id="dup", name="P", year=2020)
    with pytest.raises(ValidationError):
        KnowledgeBase(profile=_profile(), experiences=[exp], projects=[proj])


def test_knowledge_base_evidence_sin_id_valido_falla() -> None:
    exp = Experience(id="e1", company="C", role="R", start="2020-01")
    skill = Skill(name="Python", category="lang", level=4, evidence=["no_existe"])
    with pytest.raises(ValidationError):
        KnowledgeBase(profile=_profile(), experiences=[exp], skills=[skill])


def test_knowledge_base_valida_con_evidence_correcta() -> None:
    exp = Experience(id="e1", company="C", role="R", start="2020-01")
    skill = Skill(name="Python", category="lang", level=4, evidence=["e1"])
    kb = KnowledgeBase(profile=_profile(), experiences=[exp], skills=[skill])
    assert kb.skills[0].evidence == ["e1"]

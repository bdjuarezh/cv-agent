import time
from pathlib import Path

import yaml

from cv_agent.knowledge.store import KnowledgeStore, load_knowledge_base


def _write_kb(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "profile.yaml").write_text(
        yaml.dump({"name": "Jane Doe", "headline": "Ingeniera de IA"}), encoding="utf-8"
    )
    (data_dir / "experience.yaml").write_text(
        yaml.dump(
            [
                {
                    "id": "exp_a",
                    "company": "Acme",
                    "role": "MLE",
                    "start": "2021-01",
                    "end": "2023-01",
                    "stack": ["python", "pyspark"],
                },
                {
                    "id": "exp_b",
                    "company": "Beta",
                    "role": "Senior MLE",
                    "start": "2023-02",
                    "end": None,
                    "stack": ["python", "airflow"],
                },
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "projects.yaml").write_text(
        yaml.dump([{"id": "proj_a", "name": "Scoring", "year": 2022, "stack": ["pyspark"]}]),
        encoding="utf-8",
    )
    (data_dir / "skills.yaml").write_text(
        yaml.dump(
            [{"name": "Python", "category": "lang", "level": 5, "evidence": ["exp_a", "exp_b"]}]
        ),
        encoding="utf-8",
    )


def test_load_knowledge_base_bajo_200ms(tmp_path: Path) -> None:
    _write_kb(tmp_path)
    start = time.perf_counter()
    load_knowledge_base(tmp_path)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 200


def test_store_experiences_filtra_por_stack_y_company(tmp_path: Path) -> None:
    _write_kb(tmp_path)
    store = KnowledgeStore(load_knowledge_base(tmp_path))

    assert {e.id for e in store.experiences(stack="airflow")} == {"exp_b"}
    assert {e.id for e in store.experiences(company="acme")} == {"exp_a"}
    assert {e.id for e in store.experiences(from_=2023)} == {"exp_a", "exp_b"}


def test_store_projects_filtra_por_tech_y_year(tmp_path: Path) -> None:
    _write_kb(tmp_path)
    store = KnowledgeStore(load_knowledge_base(tmp_path))

    assert {p.id for p in store.projects(tech="pyspark")} == {"proj_a"}
    assert store.projects(year=1999) == []


def test_store_skills_filtra_por_min_level(tmp_path: Path) -> None:
    _write_kb(tmp_path)
    store = KnowledgeStore(load_knowledge_base(tmp_path))

    assert {s.name for s in store.skills(min_level=5)} == {"Python"}
    assert store.skills(min_level=6) == []

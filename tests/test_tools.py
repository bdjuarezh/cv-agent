import json
from pathlib import Path

import pytest

from cv_agent.agent.tools import ToolContext, execute_tool
from cv_agent.knowledge.retrieval.local import build_local_retriever
from cv_agent.knowledge.store import KnowledgeStore, load_knowledge_base

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def ctx() -> ToolContext:
    store = KnowledgeStore(load_knowledge_base(DATA_DIR))
    retriever = build_local_retriever(DATA_DIR, embedder=None)
    return ToolContext(store=store, retriever=retriever)


async def test_compute_years_devuelve_ids_rastreables(ctx: ToolContext) -> None:
    out = json.loads(await execute_tool("compute_years", {"skill": "python"}, ctx))
    assert out["skill"] == "python"
    assert out["years"] > 0


async def test_compute_years_skill_vacio_lanza_error(ctx: ToolContext) -> None:
    with pytest.raises(ValueError):
        await execute_tool("compute_years", {"skill": "  "}, ctx)


async def test_get_experience_filtra_por_stack(ctx: ToolContext) -> None:
    out = json.loads(await execute_tool("get_experience", {"stack": "airflow"}, ctx))
    assert all("airflow" in e["stack"] for e in out)
    assert all("id" in e for e in out)


async def test_get_contact_solo_devuelve_publicos(ctx: ToolContext) -> None:
    out = json.loads(await execute_tool("get_contact", {}, ctx))
    profile = ctx.store.profile()
    public_labels = {c.label for c in profile.contact if c.public}
    assert {c["label"] for c in out} == public_labels
    assert "Teléfono" not in {c["label"] for c in out}


async def test_get_skills_min_level(ctx: ToolContext) -> None:
    out = json.loads(await execute_tool("get_skills", {"min_level": 5}, ctx))
    assert all(s["level"] >= 5 for s in out)


async def test_get_projects_limit(ctx: ToolContext) -> None:
    out = json.loads(await execute_tool("get_projects", {"limit": 1}, ctx))
    assert len(out) <= 1


async def test_search_profile_devuelve_chunk_id_y_source(tmp_path: Path) -> None:
    # Narrativa controlada, independiente de data/narrative (que el usuario edita en paralelo).
    narrative_dir = tmp_path / "narrative"
    narrative_dir.mkdir()
    (narrative_dir / "historia.md").write_text(
        "<!-- EJEMPLO — comentario de plantilla que NO debe indexarse -->\n\n"
        "# Por qué me especialicé en IA generativa\n"
        "Un párrafo real sobre IA generativa y modelos de lenguaje.\n",
        encoding="utf-8",
    )
    retriever = build_local_retriever(tmp_path, embedder=None)
    ctx = ToolContext(store=KnowledgeStore(load_knowledge_base(DATA_DIR)), retriever=retriever)

    out = json.loads(await execute_tool("search_profile", {"query": "IA generativa", "k": 3}, ctx))

    assert out
    for chunk in out:
        assert {"chunk_id", "source", "text"} <= chunk.keys()
        assert "plantilla" not in chunk["text"]  # el comentario HTML se filtró


async def test_herramienta_desconocida_lanza_error(ctx: ToolContext) -> None:
    with pytest.raises(ValueError):
        await execute_tool("no_existe", {}, ctx)

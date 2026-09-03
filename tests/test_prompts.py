from pathlib import Path

from cv_agent.agent.prompts import build_system_prompt
from cv_agent.knowledge.store import load_knowledge_base

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def test_corpus_va_al_final_del_prompt() -> None:
    kb = load_knowledge_base(DATA_DIR)
    prompt = build_system_prompt(kb)

    corpus_idx = prompt.index("# CORPUS COMPLETO")
    assert corpus_idx > prompt.index("Jerarquía de instrucciones")
    assert prompt.rfind("# CORPUS COMPLETO") == corpus_idx  # aparece una sola vez, y al final
    assert kb.profile.name in prompt
    assert kb.experiences[0].id in prompt

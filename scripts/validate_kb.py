"""Valida data/*.yaml contra el esquema del KB. `make validate-kb` o `uv run python scripts/validate_kb.py`."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import ValidationError

from cv_agent.knowledge.store import load_knowledge_base


def main() -> int:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    try:
        kb = load_knowledge_base(data_dir)
    except ValidationError as exc:
        print(f"KB inválida:\n{exc}", file=sys.stderr)
        return 1

    print(
        f"KB válida: {len(kb.experiences)} experiencias, {len(kb.projects)} proyectos, "
        f"{len(kb.skills)} skills."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

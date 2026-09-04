"""Chunking de `data/narrative/*.md` para el retriever (ARCHITECTURE.md §1).

~400 palabras por chunk como proxy de tokens (sin añadir un tokenizer solo para esto — a esta
escala no hace falta ser exactos), 80 de solape, sin partir a mitad de frase. Primero trocea por
encabezado (unidad semántica natural); si una sección excede la ventana, se subdivide con solape
por oraciones completas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

WINDOW_WORDS = 400
OVERLAP_WORDS = 80

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class RawChunk:
    chunk_id: str
    source: str
    text: str


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "intro"


def _sections_by_heading(text: str) -> list[tuple[str, str]]:
    """[(encabezado, cuerpo)], saltando secciones vacías. El texto antes del primer encabezado
    queda con encabezado `""` — el llamador lo rellena con el nombre del archivo."""
    sections: list[tuple[str, str]] = []
    heading = ""
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            sections.append((heading, "\n".join(buffer).strip()))
            heading = line.lstrip("#").strip()
            buffer = []
        else:
            buffer.append(line)
    sections.append((heading, "\n".join(buffer).strip()))
    return [(h, b) for h, b in sections if b]


def _split_with_overlap(body: str) -> list[str]:
    sentences = [s for s in _SENTENCE_SPLIT.split(body) if s.strip()]
    if not sentences:
        return []
    word_counts = [len(s.split()) for s in sentences]

    windows: list[str] = []
    start = 0
    n = len(sentences)
    while start < n:
        end = start
        total = 0
        while end < n and total < WINDOW_WORDS:
            total += word_counts[end]
            end += 1
        windows.append(" ".join(sentences[start:end]))
        if end >= n:
            break
        # Retrocede hasta acumular ~OVERLAP_WORDS palabras, en frontera de oración.
        back_words = 0
        new_start = end
        while new_start > start and back_words < OVERLAP_WORDS:
            new_start -= 1
            back_words += word_counts[new_start]
        start = max(new_start, start + 1)  # garantiza avance incluso con una oración gigante
    return windows


def chunk_narrative(narrative_dir: Path) -> list[RawChunk]:
    chunks: list[RawChunk] = []
    if not narrative_dir.exists():
        return chunks

    for path in sorted(narrative_dir.glob("*.md")):
        text = _HTML_COMMENT.sub("", path.read_text(encoding="utf-8"))
        for heading, body in _sections_by_heading(text):
            heading = heading or path.stem
            base_slug = _slug(heading)
            windows = _split_with_overlap(body)
            for idx, window_text in enumerate(windows):
                suffix = f"-{idx}" if len(windows) > 1 else ""
                chunks.append(
                    RawChunk(
                        chunk_id=f"{path.stem}#{base_slug}{suffix}",
                        source=path.name,
                        text=window_text,
                    )
                )
    return chunks

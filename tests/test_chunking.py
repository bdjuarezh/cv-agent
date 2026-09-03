from pathlib import Path

from cv_agent.knowledge.chunking import OVERLAP_WORDS, WINDOW_WORDS, chunk_narrative


def _write(narrative_dir: Path, name: str, content: str) -> None:
    narrative_dir.mkdir(parents=True, exist_ok=True)
    (narrative_dir / name).write_text(content, encoding="utf-8")


def test_directorio_inexistente_no_revienta(tmp_path: Path) -> None:
    assert chunk_narrative(tmp_path / "no_existe") == []


def test_filtra_comentarios_html(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.md",
        "<!-- plantilla, no indexar -->\n# Encabezado\nTexto real.\n",
    )
    chunks = chunk_narrative(tmp_path)
    assert len(chunks) == 1
    assert "plantilla" not in chunks[0].text


def test_secciones_cortas_no_se_dividen(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "# Uno\nPárrafo corto.\n\n# Dos\nOtro párrafo corto.\n")
    chunks = chunk_narrative(tmp_path)
    assert len(chunks) == 2
    assert {c.chunk_id for c in chunks} == {"a#uno", "a#dos"}


def test_seccion_larga_se_divide_con_solape_en_frontera_de_oracion(tmp_path: Path) -> None:
    # ~900 palabras en frases cortas -> debe dar más de un chunk, ninguno cortado a mitad de frase.
    sentence = "Esta es una oración de prueba con palabras suficientes para contar bien. "
    body = sentence * 60  # ~600 palabras
    _write(tmp_path, "a.md", f"# Larga\n{body}\n")

    chunks = chunk_narrative(tmp_path)

    assert len(chunks) > 1
    for c in chunks:
        assert c.text.strip().endswith(".")
        assert len(c.text.split()) <= WINDOW_WORDS + 20  # tolerancia por la última oración

    # Hay solape real: el final de un chunk reaparece al inicio del siguiente.
    first_tail = " ".join(chunks[0].text.split()[-10:])
    assert first_tail in chunks[1].text


def test_overlap_words_menor_que_window_words() -> None:
    assert 0 < OVERLAP_WORDS < WINDOW_WORDS

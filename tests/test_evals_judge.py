import pytest

from cv_agent.providers.base import ProviderResult
from cv_agent.providers.fake import FakeProvider
from evals.judge import JudgeParseError, judge


async def test_judge_parsea_json_valido() -> None:
    provider = FakeProvider(
        [
            ProviderResult(
                text='{"grounded": true, "relevant": true, "refused": false, "reason": "ok"}'
            )
        ]
    )
    verdict = await judge(provider, question="q", answer="a", rubric="r", corpus="c")

    assert verdict.grounded
    assert verdict.relevant
    assert not verdict.refused
    assert verdict.reason == "ok"


async def test_judge_extrae_json_con_texto_alrededor() -> None:
    text = (
        "Aquí está mi veredicto:\n"
        '{"grounded": false, "relevant": true, "refused": true, "reason": "abstención correcta"}'
        "\nFin."
    )
    provider = FakeProvider([ProviderResult(text=text)])

    verdict = await judge(provider, question="q", answer="a", rubric="r", corpus="c")

    assert verdict.refused
    assert not verdict.grounded


async def test_judge_extrae_json_con_llave_extra_despues() -> None:
    """Regresión: el juez a veces agrega texto tras el JSON que contiene su propia '}' (p. ej.
    un ejemplo entre llaves) — tomar hasta el último '}' del texto completo rompía con
    'Extra data' aunque el objeto JSON en sí fuera válido (visto en producción, 2026-09-03)."""
    text = (
        '{"grounded": true, "relevant": true, "refused": false, "reason": "ok"}\n'
        "Nota: si la respuesta fuera de la forma {ejemplo: dato}, sería igual de válida."
    )
    provider = FakeProvider([ProviderResult(text=text)])

    verdict = await judge(provider, question="q", answer="a", rubric="r", corpus="c")

    assert verdict.grounded
    assert verdict.reason == "ok"


async def test_judge_texto_sin_json_lanza_error() -> None:
    provider = FakeProvider([ProviderResult(text="no soy JSON")])
    with pytest.raises(JudgeParseError):
        await judge(provider, question="q", answer="a", rubric="r", corpus="c")


async def test_judge_json_incompleto_lanza_error() -> None:
    provider = FakeProvider([ProviderResult(text='{"grounded": true}')])
    with pytest.raises(JudgeParseError):
        await judge(provider, question="q", answer="a", rubric="r", corpus="c")

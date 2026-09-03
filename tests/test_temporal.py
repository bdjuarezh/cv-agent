from datetime import date

from cv_agent.knowledge.models import Experience, Project
from cv_agent.knowledge.temporal import merge_intervals, overlap, total_years, years_with_skill


def test_merge_disjuntos() -> None:
    spans = [(date(2020, 1, 1), date(2020, 6, 1)), (date(2021, 1, 1), date(2021, 6, 1))]
    assert merge_intervals(spans) == spans


def test_merge_solapados() -> None:
    spans = [(date(2020, 1, 1), date(2020, 8, 1)), (date(2020, 6, 1), date(2021, 1, 1))]
    assert merge_intervals(spans) == [(date(2020, 1, 1), date(2021, 1, 1))]


def test_merge_contenidos() -> None:
    outer = (date(2020, 1, 1), date(2023, 1, 1))
    inner = (date(2021, 1, 1), date(2021, 6, 1))
    assert merge_intervals([outer, inner]) == [outer]


def test_merge_adyacentes() -> None:
    spans = [(date(2020, 1, 1), date(2021, 1, 1)), (date(2021, 1, 1), date(2022, 1, 1))]
    assert merge_intervals(spans) == [(date(2020, 1, 1), date(2022, 1, 1))]


def test_merge_intervalo_abierto_usa_hoy() -> None:
    hoy = date(2026, 9, 3)
    exp = Experience(id="e1", company="C", role="R", start="2024-01", end=None, stack=["python"])
    años = years_with_skill("python", [exp], today=hoy)
    assert años == 2.7  # 32 meses / 12


def test_solapado_da_menos_que_la_suma_ingenua() -> None:
    spans = [
        (date(2020, 1, 1), date(2022, 1, 1)),  # 24 meses
        (date(2021, 1, 1), date(2023, 1, 1)),  # 24 meses, traslapa un año con el anterior
    ]
    suma_ingenua = 24 + 24
    assert total_years(spans) * 12 < suma_ingenua
    assert total_years(spans) == 3.0  # unión real: 2020-01 a 2023-01 = 36 meses


def test_overlap_con_traslape() -> None:
    a = (date(2021, 1, 1), date(2022, 6, 1))
    b = (date(2022, 1, 1), date(2022, 12, 1))
    assert overlap(a, b) == (date(2022, 1, 1), date(2022, 6, 1))


def test_overlap_sin_traslape() -> None:
    a = (date(2020, 1, 1), date(2020, 6, 1))
    b = (date(2021, 1, 1), date(2021, 6, 1))
    assert overlap(a, b) is None


def test_years_with_skill_experiencias_y_proyectos_traslapados() -> None:
    exp = Experience(
        id="e1", company="C", role="R", start="2022-01", end="2023-01", stack=["pyspark"]
    )
    proj = Project(id="p1", name="P", year=2022, stack=["pyspark"])
    # El proyecto (2022 completo) queda contenido en el rol (2022-01 a 2023-01): no debe sumarse aparte.
    assert years_with_skill("pyspark", [exp], [proj]) == 1.0


def test_years_with_skill_es_insensible_a_mayusculas() -> None:
    # Regresión: el modelo suele pasar el nombre "propio" del skill (p. ej. "Python", como
    # aparece en skills.yaml) mientras `stack` usa minúsculas — antes del fix esto daba 0 en
    # silencio en vez de encontrar el match. Encontrado probando con el proveedor real.
    exp = Experience(
        id="e1", company="C", role="R", start="2022-01", end="2023-01", stack=["python"]
    )
    assert years_with_skill("Python", [exp]) == 1.0
    assert years_with_skill("PYTHON", [exp]) == 1.0

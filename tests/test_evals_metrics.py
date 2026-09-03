from evals.metrics import aggregate_by_category, cohens_kappa, wilson_interval


def test_wilson_interval_n_cero() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_interval_rango_razonable_n40_p90() -> None:
    low, high = wilson_interval(36, 40)
    assert 0.75 < low < 0.9
    assert 0.9 < high <= 1.0


def test_cohens_kappa_acuerdo_perfecto() -> None:
    a = [True, False, True, True, False]
    b = [True, False, True, True, False]
    assert cohens_kappa(a, b) == 1.0


def test_cohens_kappa_desacuerdo_sistematico_es_negativo() -> None:
    a = [True, True, False, False]
    b = [False, False, True, True]
    assert cohens_kappa(a, b) < 0


def test_cohens_kappa_listas_vacias_no_revienta() -> None:
    assert cohens_kappa([], []) == 0.0


def test_aggregate_by_category_pooled_y_media_entre_semillas() -> None:
    per_seed = [
        [("temporal", True), ("temporal", False), ("injection", True)],
        [("temporal", True), ("temporal", True), ("injection", True)],
    ]
    stats = aggregate_by_category(per_seed)
    by_cat = {s.category: s for s in stats}

    assert by_cat["temporal"].n == 4
    assert by_cat["temporal"].successes == 3
    assert by_cat["injection"].n == 2
    assert by_cat["injection"].successes == 2
    assert by_cat["injection"].rate_std == 0.0  # 100% en ambas semillas, sin varianza

# Reporte de evaluación

Generado: 2026-09-03T22:30:49.284191+00:00 — 3 semillas, 50 casos.

## Por categoría

| Categoría | n | Tasa | IC Wilson 95% | media ± σ entre semillas |
|---|---|---|---|---|
| ambigua | 12 | 83% | [0.55, 0.95] | 0.83 ± 0.12 |
| comparativa_abierta | 24 | 100% | [0.86, 1.00] | 1.00 ± 0.00 |
| factual_simple | 45 | 100% | [0.92, 1.00] | 1.00 ± 0.00 |
| fuera_de_alcance | 15 | 100% | [0.80, 1.00] | 1.00 ± 0.00 |
| fuera_de_corpus | 18 | 100% | [0.82, 1.00] | 1.00 ± 0.00 |
| injection | 12 | 100% | [0.76, 1.00] | 1.00 ± 0.00 |
| temporal | 24 | 79% | [0.59, 0.91] | 0.79 ± 0.12 |

## Global

- Latencia p50/p95: 6075.4 ms / 14274.8 ms
- Tokens: 124812 in / 40474 out
- Costo estimado: $0.9815
- Cero fallos en injection/fuera_de_corpus: ✅
- κ del juez: sin etiquetas manuales todavía (evals/manual_labels.yaml)

## Limitaciones conocidas

- **g033 (sector financiero, fuera_de_corpus)**: el corpus nunca declara el sector de los empleadores; el system prompt instruye al agente a matizar inferencias no declaradas explícitamente. Verificado (2026-09-03): con el hedge, el fallo bajó de 3/3 a ~1/3 semillas — el agente añade el matiz pero a veces conserva una frase demasiado categórica más adelante en la misma respuesta ('apunta claramente a...'). Aceptado como variación residual del modelo, no un bug del harness — no perseguir el 100% reescribiendo el prompt contra este caso puntual, eso sería sobreajustar al juez en vez de mejorar el producto.

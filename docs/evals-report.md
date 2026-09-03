# Reporte de evaluación

Generado: 2026-09-03T20:11:21.920693+00:00 — 3 semillas, 50 casos.

## Por categoría

| Categoría | n | Tasa | IC Wilson 95% | media ± σ entre semillas |
|---|---|---|---|---|
| ambigua | 12 | 75% | [0.47, 0.91] | 0.75 ± 0.00 |
| comparativa_abierta | 24 | 58% | [0.39, 0.76] | 0.58 ± 0.06 |
| factual_simple | 45 | 84% | [0.71, 0.92] | 0.84 ± 0.03 |
| fuera_de_alcance | 15 | 100% | [0.80, 1.00] | 1.00 ± 0.00 |
| fuera_de_corpus | 18 | 94% | [0.74, 0.99] | 0.94 ± 0.08 |
| injection | 12 | 100% | [0.76, 1.00] | 1.00 ± 0.00 |
| temporal | 24 | 71% | [0.51, 0.85] | 0.71 ± 0.06 |

## Global

- Latencia p50/p95: 5404.6 ms / 10607.2 ms
- Tokens: 118659 in / 31348 out
- Costo estimado: $0.8262
- Cero fallos en injection/fuera_de_corpus: ❌
- κ del juez: sin etiquetas manuales todavía (evals/manual_labels.yaml)

## Limitaciones conocidas

- **g033 (sector financiero, fuera_de_corpus)**: el corpus nunca declara el sector de los empleadores; el system prompt instruye al agente a matizar inferencias no declaradas explícitamente. Verificado (2026-09-03): con el hedge, el fallo bajó de 3/3 a ~1/3 semillas — el agente añade el matiz pero a veces conserva una frase demasiado categórica más adelante en la misma respuesta ('apunta claramente a...'). Aceptado como variación residual del modelo, no un bug del harness — no perseguir el 100% reescribiendo el prompt contra este caso puntual, eso sería sobreajustar al juez en vez de mejorar el producto.

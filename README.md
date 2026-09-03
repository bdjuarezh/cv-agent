# cv-agent

Servicio HTTP que implementa el spec [Open Responses](https://www.openresponses.org/)
(`POST /v1/responses`) y expone un agente conversacional sobre un CV: experiencia, proyectos,
habilidades y trayectoria, con aritmética temporal determinista y respaldo de búsqueda híbrida
sobre la narrativa larga.

Decisiones técnicas y sus porqués: **[ARCHITECTURE.md](./ARCHITECTURE.md)**.

## Arquitectura, en una línea

```
Cliente  ──POST /v1/responses (SSE o JSON)──▶  cv-agent  ──Messages API──▶  Claude (API de Anthropic)
                                                    │
                                                    └──▶ herramientas internas sobre el CV
```

El corpus completo del CV vive en el system prompt (con prompt caching), no en una base
vectorial — el porqué está en `ARCHITECTURE.md` §1. Las herramientas resuelven lo que un LLM hace
mal por su cuenta: fechas, conteos y agregaciones son deterministas, nunca aritmética del modelo.

## Correr en local

Requiere [`uv`](https://docs.astral.sh/uv/) y una API key de Anthropic (`ANTHROPIC_API_KEY`) —
el modelo se sirve vía la API directa de Anthropic (`PROVIDER_BACKEND=anthropic_direct`).

```bash
uv sync
cp .env.example .env        # llena ANTHROPIC_API_KEY y los demás valores
make lint typecheck test    # corre con FakeProvider, sin tocar la red
make dev                    # levanta en :8080
curl localhost:8080/healthz # {"status": "ok"}
```

Para que el agente responda de verdad necesitas:

1. Una API key de Anthropic (console.anthropic.com) en `ANTHROPIC_API_KEY`.
2. Tu propio contenido en `data/*.yaml` y `data/narrative/*.md` — el repo trae una plantilla de
   ejemplo, no un CV real. El esquema está documentado en `src/cv_agent/knowledge/models.py`.
3. Opcional — mejor recall en `search_profile`: un proyecto de GCP con la API de Vertex
   Embeddings habilitada (`GCP_PROJECT`, autenticación por
   `gcloud auth application-default login`) y `make kb` para precomputar los embeddings de la
   narrativa (`data/embeddings.npy` + `data/chunks.json`). Sin esto el retriever cae a búsqueda
   léxica (BM25) sola, sin fallar — `search_profile` es respaldo, no el camino crítico
   (`ARCHITECTURE.md` §1).

El servicio también soporta Claude vía Vertex AI (`PROVIDER_BACKEND=vertex`, auth por IAM, sin
API key del modelo) — es la alternativa original, no usada en producción porque la cuota de
Vertex para el modelo de chat quedó rechazada durante el reto (`ARCHITECTURE.md` §7). Mismo
`Provider` Protocol para ambos backends, se elige por variable de entorno.

Prueba rápida por CLI, sin levantar HTTP:

```bash
uv run python -m cv_agent.cli "¿cuántos años llevas trabajando con Python?"
```

## Desplegar

Cloud Run, imagen construida por Cloud Build desde el `Dockerfile` del repo (no requiere Docker
local):

```bash
export PROJECT=tu-proyecto REGION=northamerica-south1
./infra/00_enable_apis.sh
./infra/01_setup_iam.sh
./infra/02_setup_secrets.sh      # genera y guarda la API key en Secret Manager
./infra/04_deploy.sh             # o gcloud run deploy directo, ver el script
```

Verificación end to end contra la URL pública:

```bash
export API_KEY=<la que generó setup_secrets.sh>
./scripts/smoke.sh https://tu-servicio.run.app
```

## Evaluación

`evals/golden.yaml` tiene un set de casos categorizados (factual, temporal/agregación,
comparativa, fuera de corpus, fuera de alcance, inyección, ambigua), evaluados con una
combinación de aserciones deterministas y un juez LLM validado contra etiquetas humanas
(`evals/manual_labels.yaml`, kappa de Cohen).

```bash
make eval   # usa el proveedor real — cuesta dinero, no lo corre CI
```

Reporta tasa de éxito por categoría con intervalo de Wilson, media ± desviación entre semillas
(el modelo no corre a `temperature=0`, así que la varianza es información, no ruido), y el kappa
del juez. Salida completa en `docs/evals-report.md` tras la primera corrida.

## Tests

```bash
make test        # FakeProvider, sin red — corre en CI en cada push
make lint         # ruff
make typecheck    # mypy --strict sobre src/
```

`tests/test_openai_sdk.py` apunta el SDK oficial de `openai` contra el endpoint en proceso — es
la prueba de que un cliente ajeno, no solo el nuestro, puede hablarle a este servicio.

## Limitaciones conocidas

Ver `ARCHITECTURE.md` §7 — resumen: estado conversacional en memoria de un solo proceso (no
activa con el cliente real observado), `search_profile` cae a búsqueda léxica sin embeddings
precomputados, algunos límites operativos del cliente (timeout, tamaño máximo, concurrencia) se
diseñaron con valores conservadores propios en vez de cifras confirmadas por la plataforma
consumidora, y el streaming es bufferizado (spec-válido) en vez de incremental token a token.

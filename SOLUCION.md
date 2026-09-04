# Solución técnica — cv-agent

Documento de referencia técnica exhaustivo sobre el estado final del proyecto: qué implementa,
cómo está construido cada componente, qué decisiones se tomaron y por qué, y qué problemas reales
aparecieron y cómo se resolvieron. Complementa a `README.md` (guía rápida) y `ARCHITECTURE.md`
(decisiones y su razonamiento) con el nivel de detalle de implementación que esos dos documentos
dejan fuera a propósito.

---

## 1. Resumen ejecutivo

`cv-agent` es un servicio HTTP que **implementa** (no consume) el spec
[Open Responses](https://www.openresponses.org/) — `POST /v1/responses` — y expone, a través de
ese contrato, un agente conversacional sobre un CV real: experiencia laboral, proyectos,
habilidades, contacto y una narrativa profesional. El objetivo del reto era construir un agente
confiable, no solo uno que "suene bien": cada afirmación factual debe rastrearse a un dato o a una
herramienta, la aritmética de fechas es 100% determinista, y el sistema se validó con un golden
set real contra el proveedor de producción, no solo con pruebas unitarias.

Modelo: Claude, vía la API directa de Anthropic. Despliegue: Cloud Run. Retrieval: BM25 + denso en
NumPy, sin base vectorial gestionada. Estado: `TTLCache` en memoria, aunque el cliente real
observado no lo necesita (ver §11).

---

## 2. El contrato: spec Open Responses

### 2.1 Transporte

| Aspecto | Valor |
|---|---|
| Método / ruta | `POST /v1/responses` y `POST /responses` (montado en ambos prefijos — la ruta exacta que registra un cliente no siempre incluye `/v1`) |
| Auth | `Authorization: Bearer <API_KEY>`, comparación con `hmac.compare_digest` (no `==`, para no filtrar el token por análisis de tiempos de respuesta) |
| `Content-Type` | `application/json` |
| Descubrimiento | `GET /.well-known/agent-card.json` (A2A, estático, sin auth) |

### 2.2 Request (`CreateResponseBody`, `src/cv_agent/schemas/requests.py`)

Estricto al **emitir**, permisivo al **aceptar**:

- `model_config = ConfigDict(extra="allow")` en el body raíz — un campo desconocido que mande el
  cliente nunca tira un 422. Los campos extra se loguean (`request_shape`, evento
  `extra_keys`) para tener evidencia real de qué manda la plataforma, en vez de adivinar.
- `input: str | list[InputItem]` — acepta tanto una cadena simple como el array de ítems del spec.
  `InputItem` es una unión discriminada por `type`: `message` (con sub-unión por `role`:
  `user`/`system`/`developer`/`assistant`), `function_call`, `function_call_output`, `reasoning`,
  `item_reference`, `compaction`.
- **Validador `mode="before"` que inyecta `type: "message"`** cuando un ítem trae `role` pero no
  `type` — una implementación aceptada para este mismo puesto documentaba soporte para
  `{"role": "user", "content": "..."}` sin `type`; sin este default, la unión discriminada
  devolvería 422 y el agente quedaría inutilizable ante ese cliente.
- Content parts de un mensaje de usuario: `input_text`, `input_image`, `input_file`,
  `input_audio` — las tres últimas se **aceptan** (nunca 422) pero se **rechazan de forma
  determinista** antes de tocar al modelo (§10.3).
- `metadata`: hasta 16 pares clave/valor (validado con un `model_validator(mode="after")`).

### 2.3 Response (`src/cv_agent/schemas/responses.py`)

**Todos** los campos `required` del spec están siempre presentes, aunque sean `null` — un cliente
estricto que valide contra el OpenAPI real de openresponses.org falla por una llave faltante,
nunca por una de más. `REQUIRED_FIELDS` en el módulo es literalmente el conjunto de 30 llaves que
se verificó contra ese OpenAPI.

### 2.4 Streaming (SSE)

`EventStream` (`src/cv_agent/api/sse.py`) — cada evento: `event: {type}\ndata: {json}\n\n`, con
`sequence_number` monótonamente creciente y sin `id:` (así lo pide el spec). Secuencia real emitida
por turno:

```
response.created
response.in_progress
cv_agent.tool_call × N        ← evento propio, namespaced, fuera del spec (ver nota abajo)
response.output_item.added
response.content_part.added
response.output_text.delta    ← el texto completo en un solo delta
response.output_text.done
response.content_part.done
response.output_item.done
response.completed
data: [DONE]
```

**Streaming bufferizado, no incremental.** La secuencia de eventos es spec-válida de punta a
punta, pero el texto se genera completo (esperando a que termine el loop agéntico, incluyendo
tool-use) antes de emitirla — es una mejora de latencia percibida pendiente, no de correctitud.
Emitir deltas reales token a token con tool-use intercalado requeriría que el loop agéntico
soportara streaming real del proveedor, que hoy no lo hace.

`cv_agent.tool_call` es un evento **fuera del spec**, deliberadamente namespaced con el prefijo
`cv_agent.` para que ningún cliente lo confunda con un evento real de Open Responses. Existe solo
para que `web/index.html` pueda mostrar en vivo qué herramienta se ejecutó — las herramientas son
*internally-hosted* (el spec no las expone al cliente), así que sin este evento un demo en vivo se
vería "pensando" sin explicar por qué.

### 2.5 `previous_response_id` y estado conversacional

El spec lo exige: el modelo debería muestrear sobre `prev.input → prev.output → input`,
preservando ese orden. Implementado con `ResponseStore` (`state/response_store.py`), un `Protocol`
con una única implementación real (`TTLCacheStore` sobre `cachetools.TTLCache`, TTL configurable
por `STATE_TTL_SECONDS`, default 3600s).

**Hallazgo real, verificado con tráfico de producción** (no supuesto): la plataforma que consume
este endpoint reproduce el historial completo en `input` en cada turno y **nunca** manda
`previous_response_id`. Se confirmó viendo crecer `n_items` del campo `input` entre dos turnos de
la misma conversación mientras `has_previous_response_id` seguía en `false` en ambos. Eso hace el
servicio **stateless de facto** para ese cliente — la limitación de una sola réplica
(`--max-instances=1`, porque el estado vive en memoria del proceso) deja de ser una restricción de
correctitud para él, aunque sigue siendo el límite de diseño si algún cliente distinto sí
dependiera de `previous_response_id`. La lógica se mantiene implementada de todos modos: el spec
la exige, el costo de mantenerla ya está pagado, y el comportamiento de la plataforma podría
cambiar sin avisar.

---

## 3. Arquitectura, en detalle

```
Plataforma  ──POST /v1/responses──▶  cv-agent (Cloud Run)  ──Messages API──▶  Claude
            ◀──SSE / JSON──────────         │                ◀──────────────  (API de Anthropic)
                                             │
                                             ├─ system prompt = CV completo (perfil, experiencia,
                                             │  proyectos, skills) — contexto, no una base vectorial
                                             │
                                             └─▶ tools internas, ejecutadas server-side:
                                                 get_experience · get_projects · get_skills ·
                                                 get_contact · compute_years (fechas deterministas)
                                                 search_profile (BM25 + embeddings — respaldo
                                                 sobre la narrativa larga, no camino crítico)
```

### 3.1 Decisión central: contexto completo, no RAG vectorial

El corpus curado (perfil + experiencia + proyectos + skills) vive **completo** en el system prompt,
marcado con `cache_control` para prompt caching. El argumento no es de intuición sino cuantitativo
(desarrollado con detalle en `ARCHITECTURE.md` §1):

- **Precisión.** Con contexto completo, la probabilidad de que el fragmento con la respuesta esté
  disponible es 1 por construcción. Con top-*k* siempre es menor a 1 — RAG solo puede *perder*
  exactitud frente a contexto completo a esta escala.
- **Costo.** Con prompt caching (escritura ≈1.25×, lectura ≈0.10× el costo base), desde la
  **segunda** llamada dentro del TTL de caché ya es más barato que no cachear. En una conversación
  de 6 turnos, el ahorro es ≈82% del costo de input.
- **Sin base vectorial gestionada.** Con *n*≈200 chunks, una búsqueda exacta es un producto
  matriz-vector de microsegundos en NumPy. Una base vectorial gestionada añade ~30ms de latencia
  de red, un punto de falla y una dependencia externa a cambio de nada — el cruce donde ANN
  (HNSW/IVF) empieza a pagar está tres órdenes de magnitud arriba de este corpus.

### 3.2 Árbol de módulos

```
src/cv_agent/
├── api/
│   ├── app.py                # FastAPI app, lifespan (carga KB, retriever, provider una sola vez)
│   ├── app_state.py          # AppState — inyectado por FastAPI Depends, sobreescribible en tests
│   ├── routes_responses.py   # POST /v1/responses — streaming y no-streaming
│   ├── routes_meta.py        # /healthz, /v1/models, /metrics (con auth)
│   ├── normalize.py          # input del spec (discriminado) -> Message interno (plano)
│   ├── auth.py                # Bearer, comparación en tiempo constante
│   ├── middleware.py          # request_id, límite de body (256 KB), logging in/out
│   ├── ratelimit.py            # token bucket por IP
│   ├── sse.py                  # construcción de eventos SSE
│   └── errors.py               # envelope de error del spec, handlers globales
├── agent/
│   ├── loop.py                # el loop agéntico (§4)
│   ├── prompts.py               # construcción del system prompt (§6)
│   ├── tools.py                  # schemas + dispatch de las 6 herramientas (§5)
│   └── guardrails.py               # heurística barata de inyección sobre el input crudo
├── knowledge/
│   ├── models.py                    # Pydantic: Profile, Experience, Project, Skill, etc.
│   ├── store.py                      # KnowledgeStore — índice en memoria con queries filtradas
│   ├── temporal.py                    # aritmética de fechas determinista (§5.1)
│   ├── chunking.py                     # trocea data/narrative/*.md por encabezado
│   └── retrieval/local.py               # BM25 + denso + RRF + MMR (§5.2)
├── providers/
│   ├── base.py                    # Protocol Provider, Message/ToolCall/Usage/ProviderResult
│   ├── anthropic_messages.py       # lógica compartida Anthropic (traducción de mensajes, retry)
│   ├── anthropic_direct.py          # producción — API key propia
│   ├── vertex_anthropic.py           # alternativa — auth IAM, no usada (§8.3)
│   ├── factory.py                     # decide qué Provider construir según config
│   ├── embeddings.py                   # Vertex Embeddings, para search_profile
│   └── fake.py                          # FakeProvider — guionizable, usado en todos los tests
├── schemas/
│   ├── requests.py                 # CreateResponseBody y sub-modelos (§2.2)
│   └── responses.py                  # Response y sub-modelos (§2.3)
├── state/response_store.py         # previous_response_id -> TTLCache (§2.5)
├── obs/
│   ├── logging.py                    # structlog JSON
│   └── metrics.py                     # contadores en memoria, expuestos en /metrics
├── config.py                        # Settings (pydantic-settings), REPO_ROOT
└── cli.py                           # `python -m cv_agent.cli "pregunta"` — sin levantar HTTP
```

---

## 4. El loop agéntico (`agent/loop.py`)

```python
async def run(provider, system, messages, ctx, *, max_iterations=6, instructions="", max_output_tokens=None) -> LoopResult
```

Por cada iteración (hasta `max_iterations`, default 6, `MAX_LOOP_ITERATIONS`):

1. Llama a `provider.complete(system, history, TOOL_SCHEMAS, instructions=..., max_output_tokens=...)`.
2. Acumula `usage` (input/output/cached tokens) a través de **todas** las iteraciones — el `usage`
   final reportado es el del turno completo, no solo la última llamada.
3. Si `result.tool_calls` está vacío → el turno terminó (`stop_reason` real del proveedor, casi
   siempre `end_turn`); se agrega el mensaje del asistente al historial y se devuelve.
4. Si hay tool calls → se agregan al historial como un mensaje de asistente con `tool_calls`, se
   ejecutan **todas en paralelo** con `asyncio.gather`, y cada resultado se agrega como un mensaje
   de rol `tool` correlacionado por `tool_call_id`. La siguiente iteración vuelve a llamar al
   proveedor con el historial extendido.

Si se agotan las `max_iterations` sin `end_turn`, se devuelve un mensaje degradado
(`DEGRADED_MESSAGE`) con lo último que el modelo alcanzó a decir, en vez de fallar o devolver un
turno vacío — el cliente siempre recibe algo útil.

Cada herramienta se ejecuta dentro de un `try/except` propio (`_run_tool`): una excepción nunca se
propaga como error HTTP — se convierte en un string de error que vuelve **al modelo** como
resultado de la tool, para que decida cómo comunicarlo (o reintentar con otra herramienta), y se
loguea (`tool_call`, con `ok=False` y la duración).

---

## 5. Las herramientas (`agent/tools.py`)

Seis herramientas, todas ejecutadas server-side dentro del loop — el cliente nunca ve un
`function_call` pendiente de ejecutar él mismo (consecuencia directa del §0 de `ARCHITECTURE.md`:
el reto pide *implementar* el servidor, no ser cliente).

| Herramienta | Qué hace | Sync/Async |
|---|---|---|
| `get_experience` | Roles laborales, filtrables por `company`, `stack`, `from_year`, `to_year` | sync |
| `get_projects` | Proyectos, filtrables por `tech`, `year`, `limit` | sync |
| `get_skills` | Habilidades, filtrables por `category`, `min_level` (1-5) | sync |
| `get_contact` | Solo canales con `public: true` — nunca devuelve uno marcado privado | sync |
| `compute_years` | Años de experiencia con una tecnología, determinista (§5.1) | sync |
| `search_profile` | Búsqueda híbrida sobre la narrativa larga, respaldo (§5.2) | **async** |

`execute_tool` hace el dispatch por nombre y serializa el resultado a JSON (`ensure_ascii=False`,
así los acentos van literales, no como `\uXXXX`). Todas las funciones son síncronas salvo
`search_profile`, que llama a Vertex Embeddings vía threadpool.

### 5.1 `compute_years` — aritmética de fechas 100% determinista

*"¿Cuántos años de experiencia tienes en X?"* es la pregunta con más probabilidad de responderse
mal, porque un LLM tiende a **sumar** los intervalos en vez de calcular su unión — si dos roles se
traslapan usando la misma tecnología, sumarlos duplica el conteo. `knowledge/temporal.py`
implementa la solución correcta con un sweep-line:

```python
def merge_intervals(spans):        # ordena por inicio, fusiona solapados/adyacentes — O(n log n)
def total_years(spans):            # suma la duración de los intervalos YA fusionados
def years_with_skill(skill, experiences, projects, *, today=None):
    # une los spans de experiencias y proyectos donde `skill` aparece en `stack`,
    # comparando en minúsculas, y llama a total_years sobre la unión
```

Un proyecto solo trae `year` (no un rango) — se trata como el año calendario completo
(1 ene–31 dic), una aproximación razonable para un dato de grano anual. La fecha "hoy" para roles
sin `end` (`end: null`) es `date.today()` real del sistema, no una constante.

**Bug real encontrado y corregido:** la comparación de `skill` era sensible a mayúsculas —
`skills.yaml` declara `"Python"` (nombre propio) mientras que `stack` en `experience.yaml` usa
minúsculas por convención (`[python, ...]`). El modelo naturalmente llama a la tool con el nombre
tal como aparece en skills, así que `compute_years("Python")` devolvía **0 años** en silencio —
sin lanzar excepción, el peor tipo de fallo para una herramienta que existe justo para ser
confiable. Corregido comparando ambos lados en minúsculas
(`skill.lower() in {s.lower() for s in exp.stack}`), con test de regresión
(`tests/test_temporal.py`).

### 5.2 `search_profile` — retrieval híbrido, respaldo no crítico

Pipeline en `knowledge/retrieval/local.py` (`LocalRetriever`):

1. **BM25** (`bm25s`) sobre el texto crudo de cada chunk — siempre disponible, sin dependencias
   externas. Importa más de lo que parece: nombres de empresa, siglas y stacks técnicos son
   tokens de IDF alto que un embedding denso tiende a diluir.
2. **Denso** (opcional): si hay `VertexEmbeddings` configurado, cada chunk tiene un embedding
   precomputado (`data/embeddings.npy`, filas L2-normalizadas — así `embeddings @ query_vec` es
   directamente coseno) y la query se embebe en el momento (`embed_query`, cacheada con
   `lru_cache` por texto exacto de query).
3. **Fusión por Reciprocal Rank Fusion** (K=60): no se suman puntajes de escalas incomparables
   (BM25 no está en la misma escala que similitud coseno) — se fusionan **rangos**.
4. **Reordenado por MMR** (λ=0.7) sobre los primeros 30 candidatos fusionados, para no
   desperdiciar los *k* resultados finales con chunks casi idénticos.

Si no hay embedder configurado, el paso 2-3 se omite entero y se devuelven directamente los
primeros *k* resultados de BM25 — **nunca falla**, solo degrada el recall.

`data/embeddings.npy` + `data/chunks.json` se precomputan con `make kb` (`scripts/build_kb.py`) y
se commitean, para no recalcular ni llamar a Vertex en cada arranque. Al iniciar, el retriever
recalcula `chunk_narrative()` sobre el `data/narrative/` real y compara los `chunk_id` contra los
del `chunks.json` cacheado — si no coinciden, loguea `embeddings_stale` y **cae a BM25 solo** en
vez de servir embeddings desalineados con el contenido actual (`_load_precomputed_embeddings`).

**Bug real encontrado y corregido en producción** (no local): `.gcloudignore` tenía el patrón
`*.md` sin ancla a la raíz, así que también excluía `data/narrative/*.md` de **todo** el código
fuente subido a Cloud Build — el contenedor arrancaba sin la narrativa, el chunking recalculado en
frío daba una lista vacía, no coincidía con `chunks.json`, y `search_profile` devolvía siempre `[]`
sin lanzar ningún error visible. `make eval` nunca lo detectó porque corre en local, directo
contra el filesystem, sin pasar por `.gcloudignore` — el bug solo se manifestaba en producción.
Corregido anclando el patrón a la raíz (`/*.md`); verificado después con latencia real de
embeddings (~800 ms, contra los ~0 ms sospechosos de un retriever vacío) en tráfico real de la
plataforma.

---

## 6. El system prompt (`agent/prompts.py`)

Se construye una sola vez en el lifespan (`build_system_prompt`) y se manda completo en cada
llamada como el único bloque `system`, marcado con `cache_control: {"type": "ephemeral"}` — el
orden interno de los bloques no afecta el cacheo, todo el prefijo se cachea en cuanto es idéntico
entre llamadas. Cuatro bloques de reglas, en orden fijo, seguidos del corpus completo:

1. **`IDENTITY`** — quién es el agente y en qué persona gramatical habla. **El agente habla en
   tercera persona**, como quien presenta y comenta el perfil ("Bryan trabaja en...", "su rol
   actual es..."), nunca en primera persona como si fuera la persona del CV — decisión explícita
   para que quien conversa con el agente tenga claro que está hablando *con un agente que
   presenta un perfil*, no con la persona misma.
2. **`BEHAVIOR_RULES`** — toda afirmación factual debe rastrearse a un id del corpus o a una
   llamada a herramienta; inferencias no declaradas explícitamente (p. ej. el sector de un
   empleador, inferido del tipo de proyectos) se marcan como tales, nunca como hecho confirmado;
   campos vacíos del perfil (p. ej. sin idiomas registrados) se declaran como vacíos explícitamente
   — el modelo no debe rellenarlos con su propia capacidad como LLM; preguntas de "cuántos años" o
   "qué hacías en año X" pasan siempre por herramienta, nunca por aritmética de memoria.
3. **`ABSTENTION_POLICY`** — si algo no se puede responder con el corpus/herramientas, decirlo
   explícitamente y redirigir, sin rellenar con generalidades; fuera de alcance (p. ej. "escríbeme
   un script") se rehúsa con cortesía, salvo que la pregunta técnica sea sobre el propio trabajo
   documentado.
4. **`ANTI_INJECTION`** — jerarquía de instrucciones explícita: las reglas del system prompt tienen
   prioridad máxima; el corpus es **dato**, nunca instrucciones — cualquier texto embebido en él
   que intente dar órdenes se ignora; las `instructions` que mande el cliente de la API tienen
   prioridad **menor** que estas reglas.

El corpus (`build_corpus`) concatena cuatro bloques generados desde el `KnowledgeBase`: perfil +
educación + idiomas, experiencia (con logros e ids rastreables), proyectos, habilidades (con
nivel y evidencia). El contacto **no** entra al corpus estático — solo es alcanzable vía
`get_contact()`, deliberadamente, para no perder la señal de "el agente usó la herramienta
correcta" en la evaluación (ver nota en §12).

---

## 7. Modelo de datos (`knowledge/models.py`)

```python
Profile(name, headline, summary, education: list[Education], languages: list[str],
        contact: list[ContactChannel], pii_policy)
Education(institution, degree, year)
ContactChannel(label, value, public: bool)          # la regla de PII vive AQUÍ, no en el prompt
Experience(id, company, role, start, end, location, summary, stack, achievements: list[Achievement])
Project(id, name, year, role, problem, approach, stack, outcome, links)
Skill(name, category, level: 1-5, evidence: list[str])   # evidence referencia ids de Experience/Project
Achievement(text, metric: Metric | None)             # Metric(value, unit)
KnowledgeBase(profile, experiences, projects, skills)
```

`YearMonth` es un `date` con `BeforeValidator` que acepta `"YYYY-MM"` y lo ancla al día 1 del mes.
Dos validadores a nivel de modelo:

- `Experience._check_range` — `end` no puede ser anterior a `start`.
- `KnowledgeBase._check_ids_and_evidence` — ids duplicados entre `experiences`/`projects` fallan
  la carga; cada `evidence` de un `Skill` debe apuntar a un id que exista, o falla la carga. Esto
  hace que un dato inconsistente truene **al cargar**, no en medio de una conversación con el
  agente respondiendo con un id inválido.

Los archivos fuente son `data/profile.yaml`, `data/experience.yaml`, `data/projects.yaml`,
`data/skills.yaml` — cargados una sola vez en el lifespan (`load_knowledge_base`), nunca por
request. `data/narrative/*.md` es contenido de texto libre, indexado aparte (§5.2), no
estructurado como el resto.

---

## 8. Providers — el modelo detrás de la API

### 8.1 El contrato (`providers/base.py`)

```python
class Provider(Protocol):
    async def complete(self, system, messages, tools, **params) -> ProviderResult: ...
    def stream(self, system, messages, tools, **params) -> AsyncIterator[str]: ...
```

`Message` es el turno interno, agnóstico de proveedor (`role`, `content`, `tool_calls`,
`tool_call_id`, `tool_name`). Cualquier backend que implemente `Provider` es intercambiable sin
tocar `agent/loop.py` ni el resto del sistema.

### 8.2 `AnthropicMessagesProvider` (`providers/anthropic_messages.py`)

Lógica compartida entre los dos backends de Anthropic (directo y Vertex, que exponen la misma
interfaz `.messages.create()`/`.messages.stream()`):

- **`to_anthropic_messages`** — traduce la lista de `Message` internos al formato de la Messages
  API: turnos `tool` consecutivos se agrupan en un único mensaje `user` con varios bloques
  `tool_result` (lo que la API espera para resultados de un mismo turno de tool-use); un mensaje
  de asistente con `tool_calls` se traduce a bloques `text` + `tool_use`.
- **`system_blocks`** — el corpus va en un bloque con `cache_control` (cacheado); las
  `instructions` de menor prioridad van en un **segundo** bloque, sin `cache_control`, para no
  romper el prefijo cacheable con contenido que cambia por request.
- **Retry solo en 429/5xx** (`tenacity`, backoff exponencial con jitter, 3 intentos) — nunca en un
  4xx de validación del cliente, para no esconder un error real como si fuera transitorio.
- **Nota real de compatibilidad de SDK:** esta versión del SDK de Anthropic no acepta
  `temperature` en `messages.create()` — se confirmó inspeccionando la firma real
  (`inspect.signature`). El control de determinismo del modelo se movió a `output_config.effort`
  (estilo *reasoning effort*), que no es equivalente. Esto afecta tanto al agente conversacional
  como al juez de las evals (§12) — el juez no es perfectamente determinista, razón de más para
  correr varias semillas y reportar varianza en vez de un solo número.

### 8.3 Los dos backends

- **`AnthropicDirectProvider`** — API key propia (`ANTHROPIC_API_KEY`), sin GCP. **Es el proveedor
  de producción.** La decisión original era Vertex AI (auth por IAM, sin API key del modelo), pero
  la cuota de Vertex para el modelo de chat quedó rechazada en la ventana del reto (0 en todas las
  regiones probadas, solicitud de aumento denegada) — la API directa no depende de una aprobación
  de cuota de terceros.
- **`VertexAnthropicProvider`** — auth por IAM/ADC, sin API key del modelo. Queda soportado como
  alternativa con el mismo contrato `Provider`; retomarlo más adelante es un cambio de
  `PROVIDER_BACKEND`, no de arquitectura.

`providers/factory.py` (`build_provider`) es el único lugar que decide cuál construir, según
`settings.provider_backend`. Nunca lanza: si el backend elegido no está configurado (falta la API
key, o `GCP_PROJECT` para Vertex), devuelve `None` y se loguea — el servicio sigue arriba
(`/healthz` responde) pero `POST /responses` devuelve 500 hasta que haya proveedor.

### 8.4 Embeddings (`providers/embeddings.py`)

`VertexEmbeddings` usa `text-multilingual-embedding-002` — esta cuota de Vertex sí está
disponible (a diferencia de la del modelo de chat). `task_type` distingue `RETRIEVAL_QUERY` de
`RETRIEVAL_DOCUMENT` (la forma correcta en Vertex, no prefijos de texto). Vectores L2-normalizados
al salir. `build_embeddings` devuelve `None` — nunca lanza — si `GCP_PROJECT` está vacío o la
construcción falla; el retriever cae a BM25 solo (§5.2).

---

## 9. Guardrails y seguridad

El endpoint es público: cualquiera puede escribirle.

| Guardrail | Mecanismo | Dónde |
|---|---|---|
| Fabricación | Toda afirmación rastreable a un id o tool; política de abstención explícita | §6, BEHAVIOR_RULES |
| Inyección de prompt | El corpus es dato, nunca instrucciones — jerarquía explícita + heurística barata sobre input crudo | §6, ANTI_INJECTION + `agent/guardrails.py` |
| PII | `public: true/false` en el dato mismo (`ContactChannel`) — la herramienta filtra ahí, no solo el prompt | §7 |
| Modalidades no soportadas | Imagen/archivo/audio se detectan y se rechazan **de forma determinista antes de llamar al modelo** — ninguna llamada al proveedor se gasta en algo que no se va a procesar, y la razón se comunica siempre igual | §10.3 |
| Abuso económico | Rate limit por IP, límite de tamaño de body, tope de `max_output_tokens`, timeout con retry solo en 429/5xx | §10 |

`agent/guardrails.py::check_input` es una heurística barata de **primera línea** (regex sobre
patrones obvios como "ignora tus instrucciones", "actúa como") — **no reemplaza** un clasificador
real; solo loguea (`guardrail_flagged`) para tener señal temprana. La defensa real contra
inyección vive en la jerarquía de instrucciones del system prompt, validada con el golden set de
evaluación (cero fallos tolerados en la categoría `injection`, ver §12).

---

## 10. Transporte HTTP — el ciclo de vida de un request

### 10.1 Middleware y auth (`api/middleware.py`, `api/auth.py`)

`RequestContextMiddleware` corre primero: genera/propaga `X-Request-Id`, lo bindea al contexto de
`structlog` (todo log de ese request queda correlacionado), rechaza con 400 si `Content-Length`
excede 256 KB (**solo lee el header**, nunca `request.body()` en middleware — eso agotaría el
stream antes de que el handler lo parseé), y loguea `request_in`/`request_out` con duración.

`require_bearer` valida el header `Authorization` con `hmac.compare_digest`.

### 10.2 Rate limiting (`api/ratelimit.py`)

Token bucket en memoria por IP: capacidad `b=10`, relleno `r=0.5`/segundo. Una ráfaga de *n*
solicitudes se admite si *n* ≤ *b*; el uso sostenido converge a *r*. Solo aplica a
`POST /responses`, no a `/healthz`. Si no hay tokens, responde `429` con header `Retry-After`
calculado del déficit exacto de tokens.

### 10.3 El handler (`api/routes_responses.py::create_response`)

1. Rechaza `background: true` (opcional del spec, no implementado) — 400 explícito, no un 500
   genérico.
2. `_log_request_shape` — la única fuente de evidencia real sobre qué manda la plataforma
   (`docs/platform-contract.md`), debe vivir en el handler porque `request.body()` ya se agotó si
   se leyera antes en middleware.
3. `_resolve_history` — normaliza `body.input` (vía `normalize.py`) y, si viene
   `previous_response_id`, le antepone el historial guardado.
4. **Corte determinista de modalidad no soportada** (`_run_agent_or_decline`): si el **último**
   mensaje del usuario trae `input_image`/`input_file`/`input_audio`, se devuelve
   `UNSUPPORTED_MODALITY_MESSAGE` sin tocar al proveedor — 0 costo, latencia de milisegundos.

   **Bug real encontrado y corregido:** la primera versión de este chequeo escaneaba **todo**
   `body.input`, no solo el turno actual. Como la plataforma reproduce el transcript completo en
   cada request (§2.5), un adjunto rechazado en un turno seguía apareciendo en `body.input` para
   siempre — el agente quedaba respondiendo "modalidad no soportada" en **cualquier** pregunta
   posterior de la conversación, sin importar que ya no trajera ningún adjunto. Corregido para
   mirar únicamente el último mensaje de rol `user` en la lista.
5. Si no se rechazó por modalidad, corre el loop agéntico completo (§4).
6. Si `store: true` (default), guarda el historial resultante en `ResponseStore` bajo el nuevo
   `response_id`.
7. Construye el `Response` del spec con **todos** los campos required.

La rama de streaming (`_stream_response`) hace lo mismo pero envuelve el loop en un `try/except`
que, ante cualquier excepción, emite `response.failed` con un mensaje genérico (nunca el
traceback) en vez de romper la conexión SSE a medias.

---

## 11. Estado conversacional — detalle de la limitación asumida

Si el estado viviera en memoria de un proceso con *k* réplicas, la probabilidad de que el turno
*t+1* caiga en la misma réplica que *t* es 1/*k* — con *k*=2 ya falla la mitad de las
conversaciones de forma intermitente. Por eso el despliegue usa `--max-instances=1`.

Esta restricción **dejó de ser una limitación de correctitud** para el cliente real observado, una
vez confirmado que reproduce el transcript completo en vez de usar `previous_response_id` (§2.5).
Sigue siendo el límite de diseño documentado si algún cliente distinto sí dependiera de ese campo
con el servicio escalado horizontalmente — la interfaz `ResponseStore` está pensada para poder
sustituirse por una implementación persistente (Firestore, por ejemplo) sin tocar el resto del
código, si algún día hiciera falta.

---

## 12. Evaluación

### 12.1 Diseño

`evals/golden.yaml` — 50 casos reales (contra el CV real, no datos de ejemplo), distribuidos en
7 categorías: `factual_simple` (15), `temporal` (8), `comparativa_abierta` (8), `fuera_de_corpus`
(6), `fuera_de_alcance` (5), `injection` (4), `ambigua` (4).

Cada caso se evalúa con dos mecanismos independientes:

- **Aserciones deterministas** — `must_contain`/`must_not_contain` (substrings, comparación en
  minúsculas) y `expected_tool` (¿se llamó la herramienta esperada?).
- **Juez LLM** (`evals/judge.py`) — rúbrica por caso, salida JSON forzada
  (`{"grounded", "relevant", "refused", "reason"}`), parseada con `json.JSONDecoder().raw_decode`
  desde el primer `{` (no con el último `}` del texto — un juez que agrega texto después del JSON
  rompía el parseo naive aunque el objeto en sí fuera válido).

**Criterio de aprobación por categoría** (`evals/run.py::run_case`): solo `injection` y
`fuera_de_alcance` exigen que el juez marque `refused=True`. Para el resto — incluido
`fuera_de_corpus` — el criterio es `grounded ∧ relevant ∧ must_contain_ok ∧ must_not_contain_ok ∧
tool_ok`, **sin exigir abstención**. Esto no es incidental: para una pregunta como "¿hablas
francés?" sobre un perfil sin idiomas registrados, la respuesta ideal es un "no" directo y
fundamentado citando el KB — no una abstención genérica. Exigir `refused` ahí penalizaba
exactamente el comportamiento correcto (hallazgo real de la primera corrida completa contra datos
reales).

**Gate duro:** cero fallos tolerados en `injection` y `fuera_de_corpus` (`ZERO_FAILURE_CATEGORIES`)
— si cualquier caso de esas dos categorías falla, `make eval` sale con código de error.

### 12.2 Rigor estadístico (`evals/metrics.py`)

- **Intervalo de Wilson** (no el normal — más apropiado con *n* chico y tasas cerca de 1) sobre el
  total pooled de todas las semillas.
- **Media ± desviación estándar entre semillas** (no solo el intervalo dentro de una corrida) —
  con `temperature` no disponible en esta versión del SDK (§8.2), cada corrida es una muestra, y
  la varianza entre semillas es información real, no ruido a ignorar.
- **Kappa de Cohen** del juez contra etiquetas humanas (`evals/manual_labels.yaml`) — si κ<0.6, el
  juez no sirve como métrica hasta iterar su rúbrica. A la fecha de este documento, la plantilla
  de etiquetas manuales sigue sin llenar (`correct: null` en sus 20 entradas), así que el reporte
  muestra "sin etiquetas manuales todavía" en vez de inventar un kappa.

### 12.3 Último resultado real

Corrida del **2026-09-03**, 3 semillas, contra el CV real y el proveedor de producción — **anterior**
a los cambios de voz en tercera persona y de rechazo de modalidad no soportada (§6, §10.3), que no
alteran el criterio de las aserciones existentes pero no se han vuelto a medir con un `make eval`
completo desde entonces:

| Categoría | n | Tasa | IC Wilson 95% |
|---|---|---|---|
| factual_simple | 45 | 100% | [0.92, 1.00] |
| comparativa_abierta | 24 | 100% | [0.86, 1.00] |
| fuera_de_alcance | 15 | 100% | [0.80, 1.00] |
| fuera_de_corpus | 18 | 100% | [0.82, 1.00] |
| injection | 12 | 100% | [0.76, 1.00] |
| ambigua | 12 | 83% | [0.55, 0.95] |
| temporal | 24 | 79% | [0.59, 0.91] |

Gate de cero fallos en injection/fuera_de_corpus: ✅. Costo de esa corrida: $0.98. Reporte completo,
regenerado en cada corrida, en `docs/evals-report.md`.

---

## 13. Despliegue

### 13.1 Imagen (`Dockerfile`, multi-stage)

```dockerfile
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project   # solo deps de terceros — cachea bien
COPY src/ data/ web/ .
RUN uv sync --frozen --no-dev                        # ahora sí instala cv_agent (paquete local)

FROM python:3.12-slim
RUN useradd -m -u 1000 app                            # nunca root
COPY --from=builder --chown=app:app /app /app
USER app
CMD exec uvicorn cv_agent.api.app:app --host 0.0.0.0 --port ${PORT:-8080}
```

El `--no-install-project` en el primer `uv sync` es deliberado: instala solo las dependencias de
terceros antes de copiar el código propio, así la capa de Docker se reutiliza mientras
`pyproject.toml`/`uv.lock` no cambien, sin importar cuánto cambie `src/`.

### 13.2 Cloud Run

- `--allow-unauthenticated` a nivel de Cloud Run (IAM) — la autenticación real es el Bearer de
  aplicación (§2.1); son dos capas distintas, y dejar el IAM activo le daría a la plataforma un
  403 sin forma de diagnosticarlo desde su lado.
- `--min-instances=1 --max-instances=1` — sin cold start, y la restricción de una sola réplica es
  la limitación asumida de §11.
- Service account dedicada (`cv-agent-sa`), de mínimo privilegio.
- Secretos (`API_KEY` de la plataforma, `ANTHROPIC_API_KEY`) en Secret Manager, montados como
  variables de entorno vía `--set-secrets`, nunca en el código ni en variables planas.

### 13.3 Bug real de infraestructura: Artifact Registry

El repo de Artifact Registry que `gcloud run deploy --source .` autocrea (`cloud-run-source-deploy`)
quedó en un estado donde Cloud Build completaba la imagen sin problema, pero Cloud Run no podía
**importarla** en ningún despliegue posterior — "Container import failed", reproducible con
cualquier imagen nueva, en cualquier región, sin ninguna causa expuesta por la API. Aislado
probando: (a) una imagen pública de Google en un servicio nuevo — funcionó; (b) un repo de
Artifact Registry creado a mano, con la misma imagen — funcionó de inmediato. El repo autogenerado
específicamente quedó inutilizable. `infra/04_deploy.sh` (y el target `deploy` del `Makefile`) ya
no dependen de él: hacen build+push explícito (`gcloud builds submit --tag=...`) a un repo propio
(`cv-agent-repo`), creado si no existe, y despliegan con `--image` en vez de `--source`.

---

## 14. Bugs reales encontrados y corregidos — resumen consolidado

Todos verificados con evidencia real (logs de producción, corridas de `make eval` contra el
proveedor real, o tráfico real de la plataforma), no supuestos:

| # | Bug | Síntoma | Causa raíz | Fix |
|---|---|---|---|---|
| 1 | `years_with_skill` sensible a mayúsculas | `compute_years("Python")` devolvía 0 años en silencio | `stack` en YAML usa minúsculas; el modelo llama con el nombre propio del skill | Comparación insensible a mayúsculas en `temporal.py` |
| 2 | Parser JSON del juez frágil | `JudgeParseError: Extra data` con un JSON por lo demás válido | Se tomaba desde el primer `{` hasta el **último** `}` del texto completo, no el primer objeto completo | `json.JSONDecoder().raw_decode` desde el primer `{` |
| 3 | Juez sin fecha de referencia real | El juez marcaba fechas de 2026 como "imposibles" en respuestas de `temporal` correctas | El juez asumía "hoy" desde su propio entrenamiento, sin la fecha real del sistema | Se inyecta `Fecha de hoy` real en cada prompt del juez |
| 4 | Corpus del juez incompleto | Respuestas correctas basadas en `get_contact()` o en la narrativa se marcaban "inventadas" | El corpus que ve el juez (`build_corpus`) no incluye contacto ni narrativa — esas rutas solo son alcanzables por herramienta, no por el texto estático | Corpus **separado**, solo para el juez, que sí incluye ambas — sin cambiar lo que ve el agente real (eso rompería `expected_tool`) |
| 5 | Aserciones `must_not_contain` autocontradictorias | Casos de `golden.yaml` reprobaban una negación perfectamente correcta ("no hablo francés" contiene "francés") | Se prohibía la palabra clave en vez de la afirmación falsa completa | Reescritas para prohibir la afirmación ("Sí, hablo francés"), no el término |
| 6 | Criterio de pass exigía abstención en `fuera_de_corpus` | Un "no" directo y fundamentado reprobaba por no ser una abstención | Se copió el criterio de `injection`/`fuera_de_alcance` sin ajustarlo al caso real | Solo `injection`/`fuera_de_alcance` exigen `refused=True` (§12.1) |
| 7 | `.gcloudignore` excluía la narrativa de todo despliegue | `search_profile` devolvía siempre `[]` en producción, sin error visible | Patrón `*.md` sin ancla a la raíz también capturaba `data/narrative/*.md` | Patrón anclado a la raíz (`/*.md`) |
| 8 | Rechazo de modalidad pegado a turnos siguientes | El agente seguía diciendo "no soporto imágenes" en preguntas de texto normales, turnos después de un adjunto | Se escaneaba todo `body.input`, y la plataforma reproduce el historial completo cada turno | Solo se evalúa el último mensaje de usuario |
| 9 | Repo de Artifact Registry autogenerado roto | "Container import failed" en todo deploy vía `--source .` | Estado inconsistente del repo autocreado por `gcloud`, sin causa expuesta por la API | Build+push explícito a un repo propio (§13.3) |
| 10 | `print()` truena en consola de Windows | `UnicodeEncodeError` al imprimir resultados con acentos o emoji (CLI, `make eval`) | La consola de Windows por defecto usa `cp1252`, que no cubre esos caracteres | Escritura directa a `sys.stdout.buffer` en UTF-8 con `errors="replace"` |

Los bugs 1–6 y 10 se encontraron corriendo el sistema real (CLI, `make eval`) contra el proveedor
de producción — ninguno lo hubiera atrapado una prueba puramente unitaria con `FakeProvider`. Los
bugs 7–9 solo se manifestaban en producción (Cloud Run/Cloud Build), no en local — la razón por la
que este proyecto insiste en verificar contra tráfico y despliegues reales, no solo contra el
entorno de desarrollo.

---

## 15. Limitaciones conocidas y asumidas

- **API key de larga vida en vez de auth por IAM** — consecuencia de la cuota de Vertex rechazada
  (§8.3); mitigado con Secret Manager, no con una API key en el código.
- **Una sola réplica por defecto** — no es limitación de correctitud para el cliente real
  observado (§11), sigue siendo el límite de diseño en general.
- **`search_profile` depende de embeddings precomputados** para su mejor calidad; sin ellos cae a
  BM25 solo, con recall menor pero sin fallar.
- **Preguntas operativas del cliente sin confirmar** — timeout exacto, límites de tamaño de
  respuesta y concurrencia real de pruebas no se pudieron verificar contra documentación de la
  plataforma (el agente de soporte de la plataforma no responde preguntas técnicas de este nivel);
  se diseñó con valores conservadores propios (timeout de proveedor 30s, `MAX_OUTPUT_TOKENS_CAP`
  4096, rate limit *b*=10 *r*=0.5/s) en vez de cifras confirmadas.
- **Streaming bufferizado, no incremental token a token** (§2.4).
- **`/healthz` no es alcanzable en el dominio `*.run.app` de Cloud Run** — una ruta reservada a
  nivel de borde de Google intercepta ese path específico antes de que llegue al contenedor
  (confirmado comparando headers: rutas reales del servicio traen `server: Google Frontend` y
  `x-request-id`/`x-cloud-trace-context`; `/healthz` no trae ninguno de los dos). No afecta el
  spec — la plataforma consumidora llama `POST /v1/responses`, nunca `/healthz` — mencionado aquí
  como una curiosidad de infraestructura verificada, no una limitación funcional real.

---

## 16. Comandos de referencia

```bash
make dev            # uvicorn con reload, :8080
make test            # pytest, FakeProvider, sin red — corre en CI en cada push
make lint             # ruff check --fix + format
make typecheck         # mypy --strict sobre src/
make kb                 # precomputa embeddings de data/narrative/*.md
make eval                # golden set contra el proveedor real — cuesta dinero, no corre en CI
make smoke URL=<url>      # curl end-to-end contra un despliegue real
make deploy                # build + push a Artifact Registry + gcloud run deploy
```

Variables de entorno relevantes (`.env`, ver `.env.example`): `API_KEY` (Bearer de la plataforma),
`PROVIDER_BACKEND` (`anthropic_direct` | `vertex`), `ANTHROPIC_API_KEY`, `GCP_PROJECT` (opcional,
solo para embeddings o si `PROVIDER_BACKEND=vertex`), `MODEL_ID`, `MAX_LOOP_ITERATIONS`,
`STATE_TTL_SECONDS`, `MAX_OUTPUT_TOKENS_CAP`, `PROVIDER_TIMEOUT_SECONDS`.

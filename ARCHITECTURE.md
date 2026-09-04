# Arquitectura — Agente de CV

Este documento explica las decisiones técnicas del proyecto y sus porqués. Está escrito para
quien evalúa el reto: qué se decidió, qué alternativas se descartaron, y con qué evidencia.

## 0. El contrato: servidor

El reto pide registrar un endpoint público compatible con [Open Responses](https://www.openresponses.org/).
Eso invierte el rol habitual puesto que normalmente uno *consume* `POST /v1/responses` y aquí se *implementa*.

```
Plataforma  ──POST /v1/responses──▶  Este servicio  ──Messages API──▶  Claude (API de Anthropic)
            ◀──SSE / JSON──────────                 ◀──────────────
                                          │
                                          └──▶ herramientas internas (base de conocimiento del CV)
```

Consecuencia de diseño: las herramientas (`search_profile`, `get_experience`, `compute_years`, …)
son *internally-hosted* — el loop agéntico corre dentro del servidor. El cliente manda un mensaje
y recibe un `message` final; nunca se le devuelve un `function_call` esperando que él lo ejecute.

## 1. Decisión central: ¿RAG vectorial o contexto completo?

La respuesta para nuestro corpus es **no usar una base vectorial como camino crítico**.

**Argumento de precisión.** Sea $C$ el tamaño del corpus (CV + proyectos + narrativa) y $N$ la
ventana de contexto del modelo. Descomponiendo la exactitud condicionando en el evento $R$ = "el
fragmento con la respuesta está en lo recuperado":

$$P(\text{correcto}) = P(\text{correcto}\mid R)\,P(R) + P(\text{correcto}\mid \neg R)\,P(\neg R)$$

Con contexto completo, $P(R)=1$ por construcción. Con top-$k$, $P(R)<1$ y
$P(\text{correcto}\mid\neg R)\approx 0$ si el guardrail de abstención funciona (es decir que no va a alucinar).
RAG solo puede *perder* exactitud salvo que $C>N$ o que domine la degradación tipo
*lost-in-the-middle* — algo que no ocurre con nuestro caso de uso.

**Argumento de costo.** El contraargumento obvio es pagar $C$ tokens de input en cada llamada.
Con *prompt caching*, escritura $\approx 1.25C$, lectura $\approx 0.10C$. Sobre $m$ llamadas
dentro del TTL de caché.

Desde la **segunda** llamada dentro del TTL, el caché ya gana. En una conversación de 6 turnos el
ahorro es ≈82% del costo de input.

**Decisión: híbrido en tres capas.**

1. **Corpus curado completo** en el system prompt, marcado con `cache_control` — el modelo
   siempre "ve" todo el CV.
2. **Herramientas estructuradas** (`get_experience`, `get_projects`, `get_skills`,
   `compute_years`) para lo que un LLM hace mal: fechas, conteos, agregaciones.
3. **Retriever híbrido BM25 + denso** (`search_profile`) como *respaldo* para consultas
   semánticas de cola larga sobre la narrativa larga — no es el camino crítico.

**Sin base vectorial gestionada.** Con $n\approx 200$ chunks y $d=384$ dimensiones, la búsqueda
exacta es un producto matriz-vector de ~$1.5\times10^5$ FLOPs (~50 μs en NumPy). Una base
vectorial gestionada añade latencia de red (~30 ms), un punto de falla y una dependencia externa
a cambio de nada. El cruce donde ANN (HNSW/IVF) empieza a pagar está en $n\gtrsim 10^5$ — tres
órdenes de magnitud arriba de este corpus.

La fusión BM25+denso usa **Reciprocal Rank Fusion** ($K=60$) — no se suman puntajes de escalas
incomparables, se fusionan rangos — y diversidad vía **MMR** ($\lambda=0.7$) para no desperdiciar
contexto con chunks casi idénticos. BM25 importa más de lo que parece: nombres de empresa, siglas
y stacks técnicos son tokens raros de IDF alto que un embedding denso diluye.

## 2. El detalle que separa un agente correcto de uno que alucina

*"¿Cuántos años de experiencia tienes en X?"* es la pregunta más probable  y la
que más se podría responder mal, porque los LLMs suman intervalos que se traslapan. Si hubo tres roles
con periodos $[s_i,e_i]$ usando la misma tecnología y dos se traslapan, la respuesta no es
$\sum_i(e_i-s_i)$ — es la medida de la unión:

$$T(X) = \Big|\bigcup_{i:\,X\in\text{stack}_i}[s_i,e_i]\Big|$$

Se calcula con un sweep-line: ordenar por inicio ($O(n\log n)$), fusionar intervalos solapados,
sumar longitudes. **Nunca se deja que el modelo haga esta aritmética** — es una herramienta
determinista (`compute_years`), no una instrucción de prompt. El mismo principio aplica a conteo
de proyectos, ordenamiento cronológico e intersección de periodos ("¿qué hacías en 2022?").

## 3. Estado conversacional

El spec exige `previous_response_id`: el modelo se muestrea sobre
`prev.input → prev.output → input`, preservando ese orden.

**Trampa de infraestructura conocida.** Si el estado vive en memoria del proceso y el servicio
escala a $k$ réplicas, la probabilidad de que el turno $t+1$ caiga en la misma réplica es $1/k$ —
con $k=2$ ya falla la mitad de las conversaciones de forma intermitente.

**Lo que de verdad hace la plataforma que consume este endpoint** (verificado con tráfico real,
no supuesto): reproduce el historial completo en `input` en cada turno, sin usar
`previous_response_id` — se confirmó viendo crecer el número de ítems del `input` entre dos
turnos de una misma conversación mientras `previous_response_id` seguía ausente. Eso hace el
servicio **stateless de facto** para ese cliente: la restricción de una sola réplica deja de ser
necesaria para la corrección.

`previous_response_id` se implementa de todos modos, con una interfaz (`ResponseStore`)
intercambiable por una implementación persistente (Firestore) si algún día hace falta — el spec
lo exige, y un cliente distinto podría usarlo. Costo de mantenerlo: cero, ya que la lógica ya
existía.

## 4. Guardrails

El endpoint es público: cualquiera puede escribirle.

- **Fabricación.** Toda afirmación factual debe rastrearse a un id del corpus o a una llamada a
  herramienta. El corpus se presenta con esa disciplina; el system prompt tiene una política de
  abstención explícita.
- **Inyección de prompt.** El corpus es *dato*, nunca instrucciones — el system prompt establece
  esa jerarquía explícitamente, más una heurística barata de primera línea sobre el input crudo.
  El golden set de evaluación incluye casos de inyección con tolerancia cero a fallos.
- **Fuera de alcance.** Rechazo cortés y redirección al perfil, sin ser rígido: si la pregunta
  técnica es sobre el propio trabajo, sí se responde.
- **PII.** Qué es público (LinkedIn, GitHub, correo profesional) y qué no (teléfono, domicilio) es
  una regla en el dato mismo (`contact[].public`), no solo en el prompt — así la herramienta que
  expone contacto no puede filtrar algo marcado privado aunque el prompt fallara.
- **Abuso económico.** Rate limiting por IP (token bucket), límite de tamaño de body, tope a
  `max_output_tokens`, timeout con reintento (backoff + jitter) solo en 429/5xx — nunca en errores
  de validación del cliente.
- **Modalidades no soportadas.** Imagen, archivo y audio en el input se detectan y se rechazan
  de forma determinista antes de llamar al modelo — no es una decisión del LLM, así que la razón
  se comunica siempre igual y ninguna llamada al proveedor se gasta en algo que no se va a
  procesar. Solo se evalúa el último turno del usuario, no todo el historial (§8).

## 5. Evaluación

Golden set categorizado (factual, temporal/agregación, comparativa/abierta, fuera de corpus,
fuera de alcance, inyección, ambigua), evaluado con una combinación de aserciones deterministas
(`must_contain`/`must_not_contain`, herramienta esperada) y un juez LLM con rúbrica y salida JSON
estructurada.

**Rigor estadístico.** Con $n$ preguntas y tasa observada $\hat p$, no se reporta "X% de
exactitud" a secas — se reporta el intervalo de Wilson (mejor que el normal con $n$ chico y
$\hat p$ cerca de 1). Con `temperature>0`, cada corrida es una muestra: se corren varias semillas
y se reporta media ± desviación entre ellas, no solo el intervalo dentro de una corrida.

**El juez se valida, no se asume.** Un subconjunto de casos se etiqueta a mano y se calcula el
kappa de Cohen contra el veredicto del juez. Si $\kappa<0.6$, el juez no sirve como métrica hasta
iterar su rúbrica — reportarlo es una señal de rigor, no un detalle opcional.

## 6. Stack y por qué

| Capa | Elección | Por qué |
|---|---|---|
| Modelo | Claude vía API directa de Anthropic (`AsyncAnthropic`) | La cuota de Vertex AI para el modelo de chat quedó rechazada en la ventana del reto (§7) — la API directa no depende de una aprobación de cuota de terceros. `Provider` es un Protocol (`providers/base.py`); `providers/vertex_anthropic.py` implementa el mismo contrato vía `AnthropicVertex` y queda soportado como alternativa si se retoma el acceso a Vertex |
| Retrieval | `bm25s` + embeddings de Vertex + NumPy | Sin base vectorial (§1); sin dependencia de un modelo de embeddings local en la imagen — la cuota de *embeddings* de Vertex sí está disponible, a diferencia de la del modelo de chat |
| Web | FastAPI + Pydantic v2 | Uniones discriminadas nativas — esenciales para los ítems polimórficos del spec — más async real y OpenAPI gratis |
| Estado | `cachetools.TTLCache` tras una interfaz intercambiable | Simple, suficiente para el cliente real observado (§3); intercambiable sin tocar el resto del código |
| Observabilidad | JSON estructurado correlacionado por `request_id` | Trazable de punta a punta sin agente adicional |
| Despliegue | Cloud Run, always-on, service account de mínimo privilegio | Sin cold start, sin API keys de larga vida, superficie de permisos mínima |

## 7. Limitaciones conocidas y asumidas

- **API key de larga vida en vez de auth por IAM.** La decisión original era Vertex AI
  (`AnthropicVertex`, sin API keys del modelo — auth por service account). La cuota de Vertex
  para el modelo de chat fue rechazada durante la ventana del reto (0 en todas las regiones
  probadas, solicitud de aumento denegada), así que la producción corre sobre la API directa de
  Anthropic con una API key en Secret Manager. `providers/base.Provider` es un Protocol — ambos
  backends lo implementan (`vertex_anthropic.py`, `anthropic_direct.py`) y se eligen por
  `PROVIDER_BACKEND` sin tocar el resto del código, así que retomar Vertex más adelante es un
  cambio de configuración, no de arquitectura.
- **Una sola réplica por defecto.** El estado de `previous_response_id` vive en memoria del
  proceso. Como el cliente real observado no depende de esto (§3), no es una limitación activa
  hoy, pero sigue siendo el límite de diseño si algún cliente sí lo usara con el servicio escalado
  horizontalmente.
- **`search_profile` es respaldo, no el camino crítico.** Su calidad depende de que el retriever
  denso tenga embeddings precomputados; si no los hay, cae a búsqueda léxica (BM25) sin fallar,
  con recall menor.
- **Preguntas operativas del cliente sin confirmar.** El timeout exacto del cliente, límites de
  tamaño de respuesta y la concurrencia real de pruebas no se pudieron verificar contra
  documentación de la plataforma — se diseñó con valores conservadores propios (timeout de
  proveedor de 30s, tope de tokens de salida, rate limiting por IP) en vez de cifras confirmadas.
- **Streaming bufferizado, no incremental token a token.** La secuencia de eventos SSE es
  spec-válida y se cumple end to end, pero el texto se genera completo antes de emitir los
  eventos — es una mejora de latencia percibida pendiente, no de correctitud.

## 8. Lo que reveló el tráfico real (encontrado y corregido)

Desplegar contra la plataforma real, no solo correr `make eval` en local, sacó a la luz dos bugs
que ningún test local hubiera atrapado:

- **`.gcloudignore` excluía `data/narrative/*.md` de todo despliegue.** El patrón `*.md` sin
  ancla a la raíz también capturaba la narrativa que el contenedor sí necesita en runtime — el
  contenedor arrancaba sin ella, el chunking recalculado en frío no coincidía con
  `data/chunks.json`, y `search_profile` devolvía siempre una lista vacía sin fallar visiblemente.
  `make eval` nunca lo detectó porque corre en local, directo contra el filesystem, sin pasar por
  `.gcloudignore`. Confirmado con tráfico real (`docs/platform-contract.md` §10b) tras el fix:
  `search_profile` con latencia real de embeddings (~800 ms) en vez de los 0 ms sospechosos de un
  retriever vacío.
- **El rechazo de modalidad no soportada se pegaba a todos los turnos siguientes.** La plataforma
  reproduce el transcript completo en `input` en cada turno (§3) — un adjunto rechazado en un
  turno quedaba en `body.input` para siempre, y la comprobación determinista (§4) escaneaba todo
  el historial en vez de solo el turno actual, así que el agente seguía respondiendo "modalidad no
  soportada" en cualquier pregunta posterior. Corregido para mirar únicamente el último mensaje
  del usuario.

Ambos bugs comparten un patrón: pasaban toda prueba local (unitarias, `make eval`) y solo se
manifestaban con el comportamiento real de la plataforma consumidora — la razón por la que este
proyecto insiste en verificar contra tráfico real en vez de confiar solo en el entorno de
desarrollo.

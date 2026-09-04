# Solución técnica — cv-agent

Este documento describe en profundidad el estado final del proyecto: qué implementa, cómo está
construido cada componente, y qué problemas reales aparecieron durante el desarrollo y cómo se
resolvieron. `README.md` es la guía rápida y `ARCHITECTURE.md` cubre las decisiones y su
razonamiento; aquí entra el nivel de detalle de implementación que esos dos dejan fuera a
propósito.

---

## 1. Resumen ejecutivo

`cv-agent` es un servicio HTTP que implementa el spec Open Responses (`POST /v1/responses`) y
expone, a través de ese contrato, un agente conversacional sobre un CV real: experiencia laboral,
proyectos, habilidades, contacto y una narrativa profesional. El reto pedía construir el lado del
servidor del spec, no consumirlo desde un cliente, y el objetivo detrás de cada decisión fue la
confiabilidad: toda afirmación factual se puede rastrear a un dato o a una herramienta, la
aritmética de fechas es determinista en vez de dejársela al modelo, y el sistema se validó con un
golden set contra el proveedor real, no solo con pruebas unitarias.

El modelo es Claude, servido por la API directa de Anthropic. El servicio corre en Cloud Run. Sobre
la narrativa larga corre un pipeline propio de RAG (retrieval-augmented generation): BM25 más
búsqueda densa, fusionados por RRF y reordenados por MMR, sobre una base vectorial local y
autogestionada con NumPy en vez de un servicio gestionado de terceros (decisión justificada por la
escala del corpus, no por evitar RAG; sección 6). El estado conversacional vive en un `TTLCache` en
memoria, aunque el cliente real que se observó en producción termina sin necesitarlo (sección 12).

---

## 2. El contrato: spec Open Responses

### Transporte

El endpoint responde en `POST /v1/responses` y también en `POST /responses`, montado en ambos
prefijos porque la ruta que registra un cliente no siempre incluye el `/v1`. La autenticación es
un `Authorization: Bearer <API_KEY>`, comparado con `hmac.compare_digest` (no `==`, para no
filtrar el token por análisis de tiempos de respuesta). El descubrimiento del agente se hace vía
`GET /.well-known/agent-card.json`, un archivo estático sin autenticación.

### El request

`CreateResponseBody` sigue la regla de ser estricto al emitir y permisivo al aceptar. El body raíz
permite campos extra sin fallar (`extra="allow"`) y los loguea, así queda evidencia real de qué
manda la plataforma en vez de tener que adivinarlo. El campo `input` acepta tanto una cadena
simple como el array de ítems del spec, modelado como una unión discriminada por `type`: mensajes
(con sub-unión por `role`), llamadas a función, resultados de función, razonamiento, referencias a
ítems previos, y compactación.

Un validador que corre antes de la validación normal le inyecta `type: "message"` a un ítem que
trae `role` pero no `type` (una implementación aceptada para este mismo puesto documentaba soporte
para mensajes sin ese campo; sin el default, la unión discriminada devolvería un 422 y dejaría el
agente inutilizable frente a ese cliente).

Las content parts de un mensaje de usuario incluyen `input_text`, `input_image`, `input_file` e
`input_audio`. Las últimas tres se aceptan sin problema a nivel de esquema, pero se rechazan más
adelante, antes de que el modelo llegue a verlas (sección 11).

### La respuesta

`Response` siempre incluye todos los campos que el spec marca como required, aunque su valor sea
`null` (un cliente que valide estrictamente contra el OpenAPI de openresponses.org falla por una
llave faltante, nunca por una de más). El módulo declara literalmente el conjunto de treinta
llaves que se verificaron contra ese OpenAPI.

### Streaming

Cada evento SSE tiene la forma `event: {type}\ndata: {json}\n\n`, con un número de secuencia
creciente y sin `id:`, como pide el spec. La secuencia real que se emite en un turno es:

```
response.created
response.in_progress
cv_agent.tool_call × N        ← evento propio, fuera del spec
response.output_item.added
response.content_part.added
response.output_text.delta    ← el texto completo llega en un solo delta
response.output_text.done
response.content_part.done
response.output_item.done
response.completed
data: [DONE]
```

El streaming está bufferizado: la secuencia de eventos cumple el spec de punta a punta, pero el
texto se genera completo (incluyendo cualquier llamada a herramienta en el camino) antes de emitir
nada. Streaming incremental real, token por token con tool-use intercalado, requeriría que el loop
agéntico soportara streaming del proveedor (pendiente, mejora de latencia percibida, no de
correctitud).

`cv_agent.tool_call` es un evento que no pertenece al spec (prefijo propio, para que ningún
cliente lo confunda con un evento real de Open Responses). Sirve solo para que la demo en
`web/index.html` muestre en vivo qué herramienta se está ejecutando, ya que las herramientas
corren del lado del servidor y el spec no las expone al cliente.

### Estado conversacional y `previous_response_id`

El spec espera que el modelo muestree sobre el historial previo más el nuevo input, preservando
ese orden. Está implementado con un `ResponseStore` sobre `cachetools.TTLCache` (TTL configurable,
una hora por defecto).

El hallazgo real, verificado con tráfico de producción, es que la plataforma que consume este
endpoint reproduce el historial completo en `input` en cada turno y nunca manda
`previous_response_id`: se confirmó viendo crecer el número de ítems del campo `input` entre dos
turnos de la misma conversación mientras `has_previous_response_id` se mantenía en `false` los dos
turnos. Eso hace que el servicio sea, en la práctica, stateless para ese cliente (la restricción de
correr con una sola réplica, necesaria mientras el estado viva en memoria de proceso, deja de
importar para la corrección de las respuestas, aunque sigue siendo el límite de diseño si algún día
un cliente distinto sí depende de ese campo). La lógica de `previous_response_id` se mantiene
implementada de todos modos (el spec la exige y el costo de tenerla ya está pagado).

---

## 3. Arquitectura

```
Plataforma  ──POST /v1/responses──▶  cv-agent (Cloud Run)  ──Messages API──▶  Claude
            ◀──SSE / JSON──────────         │                ◀──────────────  (API de Anthropic)
                                             │
                                             ├─ system prompt = CV completo (perfil, experiencia,
                                             │  proyectos, skills), directo en el contexto
                                             │
                                             └─▶ tools internas, ejecutadas server-side:
                                                 get_experience · get_projects · get_skills ·
                                                 get_contact · compute_years (fechas deterministas)
                                                 search_profile (RAG: BM25 + embeddings, RRF y
                                                 MMR sobre la narrativa larga)
```

### Contexto completo para el CV estructurado, complementado con RAG (base vectorial local)

El corpus curado (perfil, experiencia, proyectos y skills) vive completo en el system prompt,
marcado para prompt caching, y la narrativa larga se cubre con el pipeline de RAG de
`search_profile` (sección 6). Con $R$ = "el fragmento correcto está en lo recuperado":

$$P(\text{correcto}) = P(\text{correcto}\mid R)\,P(R) + P(\text{correcto}\mid \neg R)\,P(\neg R)$$

Para el corpus estructurado, contexto completo da $P(R)=1$ por construcción, mientras que
cualquier top-$k$ da $P(R)<1$; es la razón de mandarlo directo en vez de recuperarlo. En costo, con
prompt caching (escritura
$\approx 1.25C$, lectura $\approx 0.10C$ del tamaño del corpus $C$), el ahorro sobre $m$ llamadas
dentro del TTL es:

$$\text{ahorro} = 1 - \frac{1.25C + 0.10C\,(m-1)}{C\cdot m}$$

que para $m=6$ turnos da $\approx 82\%$ de input. Con $n\approx 200$ chunks, una búsqueda exacta
es $O(nd)\approx 1.5\times 10^5$ FLOPs ($\sim$50 μs en NumPy); un índice aproximado (HNSW/IVF)
solo empieza a pagar en $n\gtrsim 10^5$, tres órdenes de magnitud arriba de este corpus.

### Árbol de módulos

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
│   ├── loop.py                # el loop agéntico
│   ├── prompts.py               # construcción del system prompt
│   ├── tools.py                  # schemas + dispatch de las herramientas
│   └── guardrails.py               # heurística barata de inyección sobre el input crudo
├── knowledge/
│   ├── models.py                    # Pydantic: Profile, Experience, Project, Skill, etc.
│   ├── store.py                      # KnowledgeStore — índice en memoria con queries filtradas
│   ├── temporal.py                    # aritmética de fechas determinista
│   ├── chunking.py                     # trocea data/narrative/*.md por encabezado
│   └── retrieval/local.py               # BM25 + denso + RRF + MMR
├── providers/
│   ├── base.py                    # Protocol Provider, Message/ToolCall/Usage/ProviderResult
│   ├── anthropic_messages.py       # lógica compartida Anthropic (traducción de mensajes, retry)
│   ├── anthropic_direct.py          # producción — API key propia
│   ├── vertex_anthropic.py           # alternativa — auth IAM, no usada en producción
│   ├── factory.py                     # decide qué Provider construir según config
│   ├── embeddings.py                   # Vertex Embeddings, para search_profile
│   └── fake.py                          # FakeProvider — guionizable, usado en todos los tests
├── schemas/
│   ├── requests.py                 # CreateResponseBody y sub-modelos
│   └── responses.py                  # Response y sub-modelos
├── state/response_store.py         # previous_response_id -> TTLCache
├── obs/
│   ├── logging.py                    # structlog JSON
│   └── metrics.py                     # contadores en memoria, expuestos en /metrics
├── config.py                        # Settings (pydantic-settings), REPO_ROOT
└── cli.py                           # `python -m cv_agent.cli "pregunta"` — sin levantar HTTP
```

---

## 4. El loop agéntico

`agent/loop.py` expone una sola función, `run`, que recibe el proveedor, el system prompt, el
historial de mensajes y el contexto de herramientas, y devuelve un `LoopResult` con el texto
final, el historial completo, cuántas iteraciones tomó, y el uso de tokens acumulado.

En cada iteración (hasta un máximo configurable, seis por defecto) se llama al proveedor con el
historial actual y las herramientas disponibles. Si la respuesta no trae llamadas a herramientas,
el turno terminó: se agrega el mensaje del asistente al historial y se devuelve. Si sí las trae,
se agregan todas al historial, se ejecutan en paralelo con `asyncio.gather`, y cada resultado se
agrega como un mensaje de rol `tool` correlacionado por su id de llamada; la siguiente iteración
vuelve a llamar al proveedor con ese historial extendido. El uso de tokens se acumula a lo largo
de todas las iteraciones, así que lo reportado al final es el costo real del turno completo, no
solo de la última llamada.

Si se agotan las iteraciones sin que el modelo termine el turno, se devuelve un mensaje que
explica que no se pudo completar la respuesta y comparte lo último que el modelo alcanzó a decir
(en vez de fallar o devolver algo vacío). Cada ejecución de herramienta está envuelta en su propio
manejo de errores: si algo truena, el error se convierte en texto y se le devuelve al modelo como
resultado de esa herramienta, en vez de propagarse como un error HTTP.

---

## 5. Las herramientas

Hay seis, todas ejecutadas del lado del servidor dentro del loop (el cliente nunca recibe una
llamada a función pendiente de ejecutar él mismo, porque el reto pide implementar el servidor, no
actuar como cliente).

| Herramienta | Qué hace |
|---|---|
| `get_experience` | Roles laborales, filtrables por empresa, tecnología o rango de años |
| `get_projects` | Proyectos, filtrables por tecnología, año o con un límite de resultados |
| `get_skills` | Habilidades, filtrables por categoría o nivel mínimo |
| `get_contact` | Solo devuelve los canales marcados como públicos |
| `compute_years` | Años de experiencia con una tecnología, calculados de forma determinista |
| `search_profile` | Búsqueda híbrida sobre la narrativa larga, como respaldo |

Todas son funciones síncronas salvo `search_profile`, que llama a Vertex Embeddings a través de un
threadpool. El resultado de cada una se serializa a JSON con los acentos escritos literalmente en
vez de como secuencias de escape.

### `compute_years`: aritmética de fechas determinista

La pregunta "¿cuántos años de experiencia tienes en X?" es probablemente la que más fácil se
responde mal, porque un modelo de lenguaje tiende a sumar los intervalos en vez de calcular su
unión: si dos roles se traslapan usando la misma tecnología, sumarlos duplica ese periodo. Con
$[s_i,e_i]$ los periodos donde aparece la tecnología $X$:

$$T(X) = \left|\bigcup_i [s_i,e_i]\right|$$

Se calcula con un sweep-line (ordenar por $s_i$, fusionar solapados o adyacentes, sumar
duraciones), $O(n\log n)$. Un proyecto en el CV solo trae un año, no un rango, así que se trata
como el año calendario completo (una simplificación razonable para un dato con esa granularidad).
La fecha de "hoy" para roles sin fecha de fin es la fecha real del sistema, y la comparación del
nombre de la tecnología ignora mayúsculas (el stack de cada experiencia se declara en minúsculas,
mientras que el modelo suele nombrar la tecnología tal como aparece en la lista de habilidades).

### `search_profile`: retrieval híbrido como respaldo

El pipeline en `knowledge/retrieval/local.py` combina BM25 sobre el texto crudo de cada fragmento
(siempre disponible, sin depender de ningún servicio externo, y particularmente útil para nombres
de empresa, siglas y tecnologías) con una búsqueda densa opcional cuando hay un modelo de
embeddings de Vertex configurado. Los dos rankings se combinan y se reordenan antes de devolver
los resultados finales; el mecanismo exacto se explica en la siguiente sección. Si no hay embedder
configurado, el paso denso se omite y se devuelven los primeros resultados de BM25 (el retriever
nunca falla, en el peor caso solo pierde algo de recall).

Los embeddings y los fragmentos se precomputan con `make kb` y se guardan en el repositorio, para
no recalcularlos ni llamar a Vertex en cada arranque. Al iniciar, el retriever vuelve a trocear la
narrativa actual y compara esos fragmentos contra los ya guardados; si no coinciden, asume que el
índice quedó desactualizado y cae a BM25 solo, en vez de servir embeddings que ya no corresponden
al contenido real.

---

## 6. Por qué esto sí es RAG

`search_profile` es un pipeline real de RAG (retrieval-augmented generation): búsqueda léxica y
densa, fusión de rankings, reordenado por diversidad, construido a mano sobre NumPy con una base
vectorial local. Recupera pasajes relevantes de la narrativa larga y se los entrega al modelo como
contexto antes de generar la respuesta, complementando al corpus estructurado del CV, que va
directo al contexto porque a esa escala no hace falta recuperarlo.

El puntaje de recuperación combina tres pasos. Score léxico, por término $q_i$ de la consulta:

$$\text{score}_{\text{BM25}}(D,Q) = \sum_{q_i \in Q} \text{IDF}(q_i)\cdot\frac{f(q_i,D)(k_1+1)}{f(q_i,D)+k_1\left(1-b+b\frac{|D|}{\text{avgdl}}\right)}$$

(IDF castiga palabras frecuentes en el corpus, premia las raras: nombres de empresa, siglas).
Score denso, con vectores normalizados a norma unitaria:

$$\text{score}_{\text{denso}}(q,d) = \cos(q,d) = q \cdot d$$

Los dos no están en la misma escala, así que el score final no es su suma sino su fusión por
posición (Reciprocal Rank Fusion):

$$\text{score}_{\text{final}}(d) = \sum_{i\,\in\,\{\text{BM25},\,\text{denso}\}} \frac{1}{k+r_i(d)}, \quad k=60$$

con $r_i(d)$ la posición de $d$ en el ranking $i$. Sobre los 30 mejores por $\text{score}_{\text{final}}$,
un último paso reordena por diversidad:

$$\text{MMR}(d) = \lambda\cdot\text{sim}(d,q) - (1-\lambda)\max_{d'\in S}\text{sim}(d,d'), \quad \lambda=0.7$$

con $S$ lo ya seleccionado (primer término: relevancia; segundo: penaliza parecerse a algo ya
elegido; $\lambda$ cerca de 1 favorece relevancia sobre diversidad).

---

## 7. El system prompt

`agent/prompts.py` construye el system prompt una sola vez, en el arranque del servicio, y lo
manda completo en cada llamada como un único bloque marcado para caché (el orden interno de los
bloques no afecta ese cacheo: todo el prefijo se cachea completo en cuanto es idéntico entre
llamadas). Hay cuatro bloques de reglas, en orden fijo, seguidos del corpus completo.

El primero define la identidad del agente y, en particular, en qué persona gramatical habla: en
tercera persona, como quien presenta y comenta el perfil de alguien más, nunca en primera persona
como si el agente fuera esa persona (así queda claro que se está hablando con un agente que
presenta un perfil, no con la persona del CV misma).

El segundo bloque son las reglas de comportamiento: toda afirmación factual tiene que poder
rastrearse a un id del corpus o a lo que devuelva una herramienta; si el agente va a inferir algo
que el corpus no declara de forma explícita (el sector de un empleador, a partir del tipo de
proyectos que hizo, por ejemplo) tiene que marcarlo como inferencia, nunca presentarlo como un
hecho confirmado; si un campo del perfil está vacío, hay que decirlo así en vez de rellenarlo con
la capacidad general del modelo de lenguaje; y las preguntas de "cuántos años" o "qué hacías en
tal año" siempre pasan por herramienta, nunca por aritmética de memoria.

El tercer bloque es la política de abstención: si algo no se puede responder con lo que hay
disponible, decirlo y redirigir a lo que sí se sabe, sin rellenar con generalidades vacías; una
petición fuera de alcance se rehúsa con cortesía, salvo que la pregunta técnica sea sobre el propio
trabajo documentado en el perfil.

El cuarto bloque establece la jerarquía de instrucciones que protege contra inyección de prompt:
las reglas del system prompt tienen prioridad máxima, el corpus es dato y nunca instrucciones, y
cualquier texto dentro de él que intente dar órdenes se ignora; lo que mande el cliente en el campo
de instrucciones tiene menor prioridad que todo lo anterior.

El corpus en sí concatena el perfil con su educación e idiomas, la experiencia con sus logros e ids
rastreables, los proyectos, y las habilidades con su nivel y evidencia. El contacto queda fuera de
ese texto estático a propósito (solo es alcanzable llamando a la herramienta dedicada, lo que
permite verificar en las evaluaciones que el agente de verdad la usa cuando corresponde, en vez de
contestar de memoria).

---

## 8. Modelo de datos

El esquema en `knowledge/models.py` define un perfil con nombre, título, resumen, educación,
idiomas y una lista de canales de contacto; cada canal declara explícitamente si es público, y esa
regla vive ahí, en el dato mismo, no solo como una instrucción del prompt. La experiencia laboral
tiene compañía, rol, fechas de inicio y fin, ubicación, resumen, stack tecnológico y una lista de
logros (cada uno con un texto y opcionalmente una métrica numérica). Los proyectos tienen nombre,
año, rol, el problema que resolvían, el enfoque, el stack y el resultado. Las habilidades tienen
nombre, categoría, un nivel del uno al cinco, y una lista de ids que sirven como evidencia de dónde
se usó esa habilidad.

Las fechas se guardan en formato año-mes y se anclan internamente al día uno de ese mes. Hay dos
validaciones a nivel de todo el conjunto de datos: una experiencia no puede terminar antes de
empezar, y los ids tienen que ser únicos entre experiencias y proyectos, con cada referencia de
evidencia en una habilidad apuntando a un id que de verdad exista (esto hace que un dato
inconsistente falle al cargar el conocimiento, no a mitad de una conversación con el agente citando
un id que no existe).

Los archivos fuente son los YAML en `data/`, cargados una sola vez al arrancar el servicio. La
narrativa larga, en cambio, es texto libre en archivos Markdown dentro de `data/narrative/`, y se
indexa aparte para el retriever en vez de vivir como datos estructurados.

---

## 9. Providers: el modelo detrás de la API

El contrato es un `Protocol` de Python con dos métodos (uno para completar un turno, otro para
transmitirlo en streaming) más un `Message` interno agnóstico de proveedor. Cualquier backend que
implemente esa interfaz es intercambiable sin tocar el loop agéntico ni el resto del sistema.

La lógica compartida entre los dos backends de Anthropic (directo y vía Vertex, que exponen la
misma interfaz de Messages API) vive en `anthropic_messages.py`. Ahí se traduce la lista de
mensajes internos al formato que espera esa API, agrupando turnos consecutivos de herramienta en un
único mensaje con varios resultados; el corpus se manda en un bloque marcado para caché, mientras
que las instrucciones de menor prioridad van en un segundo bloque sin esa marca (para no romper el
prefijo cacheable con contenido que cambia en cada request). Los reintentos solo aplican a errores
429 o 5xx, nunca a un 4xx de validación del cliente.

Un detalle real de compatibilidad: esta versión del SDK de Anthropic no acepta el parámetro
`temperature` en la llamada de creación de mensajes (confirmado inspeccionando la firma real de la
función). El control de determinismo se movió a otro parámetro con semántica distinta, así que ni
el agente conversacional ni el juez de las evaluaciones corren con temperatura fija en cero; el
juez no es perfectamente determinista, razón de más para correr varias semillas y reportar
varianza en vez de confiar en un solo número.

El proveedor de producción es la API directa de Anthropic, con una API key propia y sin dependencia
de GCP. La decisión original era Vertex AI (auth por IAM, sin API key del modelo), pero la cuota de
Vertex para el modelo de chat quedó rechazada durante la ventana del reto en todas las regiones
probadas, así que se cambió a la API directa. El backend de Vertex se mantiene implementado y
soportado, con el mismo contrato (cambiar entre uno y otro es solo una variable de entorno).

Un único módulo, `factory.py`, decide qué proveedor construir según la configuración, y nunca lanza
una excepción: si falta la credencial correspondiente, devuelve `None` y lo registra en el log. El
servicio sigue arriba y responde en `/healthz`, pero el endpoint principal devuelve un error hasta
que haya un proveedor configurado.

Los embeddings para el retriever de respaldo usan un modelo multilingüe de Vertex, cuya cuota sí
está disponible aunque la del modelo de chat no lo estuviera. Igual que el resto de piezas
opcionales, si no hay proyecto de GCP configurado la construcción del embedder devuelve `None` en
vez de fallar, y el retriever cae a BM25 solo.

---

## 10. Guardrails y seguridad

El endpoint es público, así que cualquiera puede escribirle. Contra fabricación de información, la
defensa es que toda afirmación debe rastrearse a un dato o a una herramienta, reforzada por la
política de abstención explícita del prompt. Contra inyección de prompt, el corpus se trata siempre
como dato y nunca como instrucciones, con esa jerarquía establecida explícitamente en el system
prompt y reforzada por una heurística barata que revisa el input crudo en busca de patrones obvios
como "ignora tus instrucciones" (esa heurística no reemplaza ninguna defensa real, solo deja una
señal temprana en los logs; la defensa que de verdad importa es la jerarquía de instrucciones,
validada con el golden set exigiendo cero fallos en esa categoría).

Sobre información privada, qué canal de contacto es público y cuál no es una regla que vive en el
dato mismo, así que la herramienta que expone contacto filtra ahí y no depende únicamente de que el
prompt se comporte bien. Contra abuso económico hay límite de tamaño de solicitud, límite de tokens
de salida, rate limiting por IP, y reintentos con backoff solo ante errores del proveedor que tiene
sentido reintentar.

Un guardrail adicional es el rechazo de modalidades que el agente no soporta. Cuando el último
mensaje del usuario trae una imagen, un archivo o audio, el sistema lo detecta y responde con una
explicación fija antes de siquiera llamar al modelo (no es una decisión que tome el LLM caso por
caso, así que la razón se comunica siempre igual y ninguna llamada al proveedor se desperdicia en
algo que de todos modos no se iba a procesar).

---

## 11. El ciclo de vida de un request

Antes de llegar al handler, un middleware genera o propaga un identificador de request, lo asocia
al contexto de logging, y rechaza con un error explícito cualquier solicitud cuyo `Content-Length`
exceda 256 KB (leyendo solo ese header, nunca el cuerpo completo en el middleware, porque leerlo
ahí agotaría el stream antes de que el handler pudiera parsearlo).

Rate limiting: token bucket por IP, capacidad $b=10$, relleno $r=0.5$/s. Admite ráfaga $n\le b$;
sostenido converge a $r$. Sin tokens:

$$\text{Retry-After} = \frac{1-\text{tokens}}{r}$$

Dentro del handler, primero se rechaza cualquier solicitud con `background: true` (no
implementado). Después se registra la forma del request (qué campos trae, si es streaming, cuántos
ítems tiene el input) como evidencia real de cómo llama la plataforma. Luego se normaliza el input
y se resuelve el historial, uniendo lo que venga guardado bajo un `previous_response_id` con los
mensajes nuevos del request actual.

Antes de correr el loop agéntico se hace el corte determinista de modalidad no soportada, mirando
únicamente el último mensaje de usuario del request (no el historial completo, que en cada llamada
trae también los turnos anteriores de la conversación).

Si no hubo corte por modalidad, corre el loop agéntico completo. Si la solicitud pide guardar el
resultado, el historial se guarda bajo un nuevo id de respuesta, y se construye el objeto de
respuesta con todos los campos que el spec exige. La rama de streaming hace lo mismo pero envuelve
el loop en un manejo de errores que, ante cualquier excepción, emite un evento de fallo con un
mensaje genérico en vez de romper la conexión a medias o filtrar un traceback.

---

## 12. Sobre el estado conversacional y la limitación de una sola réplica

Con $k$ réplicas y estado en memoria de proceso:

$$P(\text{mismo turno} \to \text{misma réplica}) = \frac{1}{k}$$

Con $k=2$ ya falla la mitad de las conversaciones de forma intermitente. Por eso el despliegue
corre con una sola instancia.

Esa restricción dejó de ser un problema de corrección para el cliente real observado, una vez
confirmado que reproduce el historial completo en vez de depender de `previous_response_id`. Sigue
siendo el límite de diseño documentado si algún cliente distinto sí llegara a depender de ese campo
con el servicio corriendo en varias réplicas (la interfaz del almacén de respuestas está pensada
para poder cambiarse por una implementación persistente, como Firestore, sin tocar el resto del
código si hiciera falta).

---

## 13. Evaluación

### Diseño

El golden set (`evals/golden.yaml`) tiene cincuenta casos escritos contra el CV real, repartidos en
siete categorías: quince factuales simples, ocho temporales, ocho comparativos o abiertos, seis de
preguntas fuera del corpus, cinco fuera del alcance del agente, cuatro de intentos de inyección, y
cuatro ambiguos.

Cada caso se evalúa por dos caminos independientes: aserciones deterministas (la respuesta contiene
ciertos términos, no contiene otros, y se llamó la herramienta esperada cuando aplica) y un juez
basado en el mismo modelo, con rúbrica por caso, forzado a un JSON con cuatro campos (si la
respuesta está fundamentada, si es relevante, si el agente se abstuvo, y una razón breve).

El criterio de aprobación varía por categoría. Solo inyección y fuera de alcance exigen que el juez
marque la respuesta como abstención; para el resto, incluida fuera del corpus, se exige
fundamentación, relevancia y las aserciones deterministas, sin exigir abstención (para una pregunta
como si el agente habla francés sobre un perfil sin idiomas registrados, la respuesta ideal es un
"no" fundamentado citando el corpus, no una abstención genérica; exigirla penalizaba exactamente el
comportamiento correcto). El gate duro: cero fallos tolerados en inyección y fuera del corpus, o
`make eval` termina con error.

### Rigor estadístico

Con $n$ preguntas y tasa observada $\hat p$, el intervalo de Wilson ($z=1.96$):

$$\text{IC}_{95\%} = \frac{\hat p + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat p(1-\hat p)}{n}+\frac{z^2}{4n^2}}}{1+\frac{z^2}{n}}$$

Como esta versión del SDK no permite fijar la temperatura en cero, cada corrida es una muestra, no
una medición exacta (se reportan media y desviación estándar entre varias semillas además del
intervalo). El juez se valida contra etiquetas puestas a mano con el kappa de Cohen:

$$\kappa = \frac{p_o - p_e}{1 - p_e}$$

con $p_o$ la concordancia observada y $p_e$ la esperada por azar; $\kappa<0.6$ invalida al juez
como métrica hasta ajustar su rúbrica. Esas etiquetas manuales todavía no se han llenado, así que
el reporte lo dice explícitamente en vez de inventar un número.

### Último resultado real

Corrida del 3 de septiembre de 2026, tres semillas, contra el CV real y el proveedor de producción
(anterior a los cambios de voz en tercera persona y de rechazo de modalidad no soportada, que no
deberían alterar el criterio de las aserciones existentes pero tampoco se han vuelto a medir con
una corrida completa desde entonces):

| Categoría | n | Tasa | IC Wilson 95% |
|---|---|---|---|
| factual_simple | 45 | 100% | [0.92, 1.00] |
| comparativa_abierta | 24 | 100% | [0.86, 1.00] |
| fuera_de_alcance | 15 | 100% | [0.80, 1.00] |
| fuera_de_corpus | 18 | 100% | [0.82, 1.00] |
| injection | 12 | 100% | [0.76, 1.00] |
| ambigua | 12 | 83% | [0.55, 0.95] |
| temporal | 24 | 79% | [0.59, 0.91] |

El gate de cero fallos en inyección y fuera del corpus se cumplió, con un costo total de esa
corrida de 0.98 dólares. El reporte completo se regenera en cada corrida y queda en
`docs/evals-report.md`.

---

## 14. Despliegue

La imagen se construye en dos etapas. La primera instala las dependencias de terceros antes de
copiar el código propio (así esa capa de Docker se reutiliza mientras no cambien las dependencias,
sin importar cuánto cambie el código fuente); solo después se instala el paquete local en sí. La
segunda etapa parte de una imagen limpia, crea un usuario sin privilegios de root, copia lo ya
construido, y arranca el servidor con uvicorn.

En Cloud Run, la autenticación de la plataforma de Google Cloud está desactivada a propósito
(`--allow-unauthenticated`), porque la autenticación real la maneja la aplicación con el Bearer
token; son dos capas distintas, y dejar activa la de Google le daría a la plataforma consumidora un
error que no podría diagnosticar desde su lado. El servicio corre con una sola instancia siempre
activa, sin arranque en frío, usando una cuenta de servicio dedicada con privilegios mínimos. Los
secretos (API key de la plataforma y de Anthropic) viven en Secret Manager y se montan como
variables de entorno, nunca escritos en el código.

El script de despliegue y el target correspondiente del Makefile construyen y suben la imagen de
forma explícita a un repositorio propio de Artifact Registry antes de desplegar, en vez de dejar
que `gcloud run deploy --source .` cree y use uno automáticamente.

---

## 15. Bugs reales, resumidos

La siguiente tabla junta los problemas reales que aparecieron durante el desarrollo, todos
verificados con evidencia concreta (logs de producción, corridas del golden set contra el proveedor
real, o tráfico real de la plataforma), no supuestos a partir de leer el código:

| # | Bug | Síntoma | Causa | Solución |
|---|---|---|---|---|
| 1 | Comparación de skill sensible a mayúsculas | `compute_years("Python")` devolvía cero años sin error | El stack en los YAML usa minúsculas; el modelo llama con el nombre propio del skill | Comparar ambos lados en minúsculas |
| 2 | Parser del JSON del juez frágil | Error de parseo con un JSON por lo demás válido | Se tomaba el texto hasta la última llave de cierre en vez del primer objeto completo | Usar el decodificador de JSON desde la primera llave de apertura |
| 3 | El juez no conocía la fecha real | Marcaba fechas correctas de 2026 como imposibles | Asumía "hoy" a partir de su propio entrenamiento | Inyectar la fecha real del sistema en cada prompt del juez |
| 4 | Corpus del juez incompleto | Respuestas correctas basadas en contacto o narrativa se marcaban como inventadas | El corpus que ve el juez no incluye lo que solo es alcanzable por herramienta | Darle al juez un corpus aparte que sí las incluya, sin tocar lo que ve el agente |
| 5 | Aserciones que se contradecían a sí mismas | Una negación correcta reprobaba por contener la palabra prohibida | Se prohibía el término en vez de la afirmación falsa completa | Reescribir las aserciones para prohibir la afirmación, no el término |
| 6 | Criterio de aprobación exigía abstención donde no correspondía | Un "no" fundamentado reprobaba por no ser una abstención | Se copió el criterio de otras categorías sin ajustarlo | Solo las categorías que de verdad requieren rehusar exigen abstención |
| 7 | Narrativa excluida del despliegue | El retriever de respaldo devolvía siempre una lista vacía en producción | Un patrón de exclusión de archivos sin ancla a la raíz capturaba también los datos que sí hacían falta | Anclar el patrón a la raíz del repositorio |
| 8 | Rechazo de modalidad pegado a turnos siguientes | El agente seguía rechazando preguntas normales después de un adjunto rechazado | Se revisaba todo el historial en vez de solo el turno actual | Revisar únicamente el último mensaje del usuario |
| 9 | Repositorio de Artifact Registry autogenerado roto | Fallo de importación en todo despliegue por el flujo por defecto | Estado inconsistente del repositorio que crea `gcloud` automáticamente | Construir y subir la imagen a un repositorio propio |
| 10 | Falla al imprimir en consola de Windows | Error de codificación con acentos o emoji en la salida de la CLI y de las evaluaciones | La consola de Windows usa por defecto una codificación que no cubre esos caracteres | Escribir directo al flujo de salida en UTF-8 |

Los primeros seis y el último aparecieron corriendo el sistema real (la CLI, las evaluaciones)
contra el proveedor de producción; ninguno lo hubiera detectado una prueba puramente unitaria con
el proveedor simulado. Los tres restantes solo se manifestaban en producción, no en local, lo que
explica por qué este proyecto insiste en verificar contra despliegues y tráfico reales en vez de
confiar únicamente en el entorno de desarrollo.

---

## 16. Limitaciones conocidas

El proyecto corre con una API key de larga vida en vez de autenticación por IAM, consecuencia de la
cuota de Vertex rechazada (se mitiga guardándola en Secret Manager en vez de en el código). Sigue
limitado a una sola réplica por defecto, aunque eso dejó de afectar la corrección para el cliente
real observado. El retriever de respaldo depende de tener embeddings precomputados para su mejor
calidad; sin ellos cae a búsqueda léxica sola, con menos recall pero sin fallar. Varios parámetros
operativos del cliente (timeout exacto, límites de tamaño de respuesta, concurrencia real de
pruebas) no se pudieron confirmar contra documentación de la plataforma, así que se diseñaron con
valores conservadores propios en vez de cifras confirmadas. El streaming sigue bufferizado en vez
de incremental token por token.

Una curiosidad de infraestructura, verificada pero sin impacto funcional real: la ruta `/healthz`
no es alcanzable en el dominio de Cloud Run (algo en el borde de la red de Google intercepta ese
path específico antes de que llegue al contenedor, confirmado comparando los headers de esa
respuesta contra los de cualquier otra ruta del servicio). No afecta nada porque la plataforma
consumidora nunca llama a `/healthz`, solo al endpoint principal.

---

## 17. Comandos de referencia

```bash
make dev            # uvicorn con reload, :8080
make test            # pytest, proveedor simulado, sin red — corre en CI en cada push
make lint             # ruff check --fix + format
make typecheck         # mypy --strict sobre src/
make kb                 # precomputa embeddings de data/narrative/*.md
make eval                # golden set contra el proveedor real — cuesta dinero, no corre en CI
make smoke URL=<url>      # curl end-to-end contra un despliegue real
make deploy                # build + push a Artifact Registry + gcloud run deploy
```

Variables de entorno relevantes, documentadas en `.env.example`: `API_KEY` para el Bearer de la
plataforma, `PROVIDER_BACKEND` para elegir entre la API directa y Vertex, `ANTHROPIC_API_KEY`,
`GCP_PROJECT` (opcional, solo hace falta para embeddings o si se usa Vertex como backend del
modelo), `MODEL_ID`, y los parámetros operativos: máximo de iteraciones del loop, TTL del estado
conversacional, tope de tokens de salida, y timeout del proveedor.

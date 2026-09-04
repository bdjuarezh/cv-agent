# Contrato de integración — Plataforma Reto IA Banorte

**Estado:** verificado de punta a punta — transporte, manejo de estado y ahora también la
completitud del round-trip (herramientas + respuesta final) confirmados con tráfico real contra
el despliegue final; faltan timeout, límites y concurrencia, que solo responde el agente Guía
**Última actualización:** 2026-09-03
**Fuentes:** formulario "Añadir un agente" (captura 2026-09-03) · spec Open Responses
(openresponses.org) · agente Guía _(pendiente)_ · logs de producción (4 turnos reales, 2026-09-03)

> Este documento es la fuente de verdad sobre cómo la plataforma llama a nuestro agente.
> Cada afirmación lleva su origen. Las marcadas ❓ son suposiciones que **no** deben tratarse
> como hechos hasta verificarse.

**Leyenda:** ✅ verificado · 🔶 inferido de una implementación aceptada · ❓ sin verificar todavía ·
❌ sin fuente posible de verificar (limitación asumida, documentada en `ARCHITECTURE.md`) ·
⚠️ implicación crítica

🔶 significa: una solución que fue aceptada para este mismo puesto se comporta así, luego la
plataforma al menos lo tolera. **No** significa que sea el mínimo requerido ni que siga vigente.

---

## 0. Arquitectura del proyecto, en breve

Este documento cubre el contrato con la plataforma; el porqué de cada decisión técnica está en
**[`ARCHITECTURE.md`](../ARCHITECTURE.md)**. Resumen para orientarse sin saltar de documento:

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

- **Servidor, no cliente.** El reto pide *implementar* `POST /v1/responses`, no consumirlo — el
  loop agéntico corre dentro del servicio; el cliente nunca recibe un `function_call` para
  ejecutar él mismo (`ARCHITECTURE.md` §0).
- **Contexto completo en vez de RAG.** El CV entero cabe cómodo en el system prompt con prompt
  caching — a esta escala, indexar en una base vectorial añade complejidad sin mejorar recall
  (`ARCHITECTURE.md` §1, con el argumento cuantitativo).
- **Aritmética temporal determinista.** "¿Cuántos años con X?" nunca lo calcula el modelo —
  siempre `compute_years` sobre la unión de intervalos reales (`knowledge/temporal.py`).
- **`search_profile` es respaldo, no el camino crítico.** Recupera la narrativa larga
  (`data/narrative/*.md`) bajo demanda vía BM25 + embeddings + RRF + MMR; si no hay embeddings
  precomputados, cae a BM25 solo, sin fallar.
- **Provider intercambiable.** `Provider` es un Protocol; en producción corre sobre la API directa
  de Anthropic (`PROVIDER_BACKEND=anthropic_direct`) — Vertex AI queda soportado como alternativa
  con el mismo contrato, no usada porque su cuota de chat no se aprobó a tiempo para el reto.
- **Stateless de facto.** Confirmado con tráfico real (§4, §10) — la plataforma reproduce el
  transcript completo en cada turno, nunca usa `previous_response_id`.
- **Despliegue.** Cloud Run (`--allow-unauthenticated` + Bearer propio), API keys en Secret
  Manager, service account de mínimo privilegio, sin API keys de larga vida del lado de Vertex si
  se retoma ese backend.

---

## 1. Transporte

| Aspecto | Valor | Fuente |
|---|---|---|
| Método | `POST` | ✅ Spec |
| Ruta | `{URL base}/responses` | ✅ Formulario, texto literal |
| Protocolo | HTTPS | ✅ Cloud Run |
| `Content-Type` | `application/json` | ✅ Spec |

⚠️ La ruta es `{base}/responses`, **no** necesariamente `/v1/responses`. Mitigación aplicada:
el router se monta en ambos prefijos, así que funciona con la base registrada con `/v1` o sin él.

**URL base registrada:** `https://cv-agent-898708863647.northamerica-south1.run.app/v1`

---

## 2. Autenticación

| Aspecto | Valor | Fuente |
|---|---|---|
| Esquema | `Authorization: Bearer <key>` | ✅ Formulario: "Se envía como `Authorization: Bearer …`" |
| Almacenamiento | Cifrado del lado de la plataforma | ✅ Formulario |
| Header alterno | No aplica | ✅ |

⚠️ El servicio de Cloud Run debe desplegarse con `--allow-unauthenticated`. Esa bandera quita el
IAM de Cloud Run, **no** nuestra auth Bearer de aplicación. Son dos capas distintas; si el IAM
queda activo, la plataforma recibe 403 sin forma de diagnosticarlo desde su lado.

---

## 3. Campos del request

| Campo | Comportamiento | Fuente |
|---|---|---|
| `model` | **Opcional.** Puede llegar ausente o vacío | ✅ Formulario: "opcional" |
| `instructions` | Instrucciones de sistema enviadas con cada solicitud | ✅ Formulario |
| Parámetros extra | JSON arbitrario inyectado en el body (ej. `temperature`, `reasoning.effort`) | ✅ Formulario |
| `input` | Array de ítems (`input_kind: "items"`), 1 ítem en el primer turno. Sin evidencia todavía de si trae `type` o no, ni de `content` como string/parts | ✅ Log real |
| `stream` | `true` en la primera llamada real | ✅ Log real |
| `tools` | `n_tools: 0` — no lo manda | ✅ Log real |
| `metadata` | Aceptado; puede devolverse con campos propios | 🔶 |

⚠️ Nunca fallar por `model` ausente ni por un valor desconocido. Una solución aceptada devuelve un
string compuesto inventado (`"career-agent-v1:<modelo>"`), luego el valor no se valida contra un
catálogo. 🔶

⚠️ **Ítems de `input` sin campo `type`.** Una solución aceptada documenta soporte para
`{"role": "user", "content": "..."}` sin `type`. Nuestra unión discriminada exige `type` y
devolvería 422. Mitigación aplicada: validador `mode="before"` que inyecta `type: "message"`
cuando falta y hay `role`. Ver `07_SCRIPTS_Y_CONFIG.md` E.1. 🔶

⚠️ Los parámetros extra hacen que `extra="allow"` en `CreateResponseBody` sea obligatorio. Con
`extra="forbid"` el agente devolvería 422 y quedaría inutilizable. Se eligió `allow` sobre `ignore`
para poder registrar qué campos manda la plataforma que no modelamos.

---

## 4. Estado de la conversación

| Aspecto | Valor | Fuente |
|---|---|---|
| Configurable | Sí, desplegable en el formulario | ✅ Formulario |
| Opción vista | "Reproducir transcripción…" | ✅ Formulario (texto truncado en la captura) |
| Opción elegida | (la que quedó por defecto — probablemente "reproducir transcripción") | ✅ Confirmado por comportamiento real, ver abajo |
| Otras opciones del desplegable | `_(pendiente)_` | ❓ — no importa ya para el diseño, solo por completitud |

✅ **Confirmado con dos mensajes reales de la misma conversación** (§10): turno 1 tenía
`n_items: 1`, turno 2 tenía `n_items: 2` — el array `input` creció, reproduciendo el historial
completo. `has_previous_response_id` fue `false` en ambos turnos. La plataforma **no usa
`previous_response_id`** — usa reproducción de transcripción. El servicio es **stateless de
facto**: `--max-instances=1` deja de ser una restricción de correctitud (D10 actualizada en
`00_ENTREGABLES.md`), aunque se mantiene por ahora por simplicidad de despliegue.

`previous_response_id` se queda implementado de todos modos: el spec lo exige, el desplegable
podría cambiarse de opción sin avisar, y el costo de mantenerlo ya está pagado.

---

## 5. Multimodalidad

| Aspecto | Valor | Fuente |
|---|---|---|
| Entrada de imágenes | Toggle, apagado por defecto | ✅ Formulario |
| Entrada de archivos | Toggle, apagado por defecto | ✅ Formulario |
| Entrega de archivos | "URL de capacidad" | ✅ Formulario |
| Configuración elegida | Ambos apagados | — |

No se requiere soporte multimodal. Aun así se parsean `input_image` e `input_file` sin reventar,
por si alguien enciende los toggles.

---

## 6. Descubrimiento

| Aspecto | Valor | Fuente |
|---|---|---|
| Tarjeta de agente | `/.well-known/agent-card.json` (A2A) | ✅ Formulario |
| Qué autocompleta | Nombre, descripción y URL de Open Responses | ✅ Formulario |
| Obligatorio | No; el formulario se puede llenar a mano | ✅ |
| Campos que lee exactamente | `_(pendiente)_` | ❓ |

Implementada como endpoint estático sin auth. La ruta confiable de registro sigue siendo llenar
el formulario manualmente.

---

## 7. Prompt suggestions

Hasta 8 líneas, mostradas sobre el compositor cuando se selecciona el agente. Es lo primero que
verá y clicará un evaluador.

Registradas:

```
_(pendiente — ver 08_CONTRATO_PLATAFORMA.md §4 para las 8 propuestas)_
```

---

## 8. Preguntas abiertas

⚠️ **El agente Guía de la plataforma no responde preguntas técnicas de este nivel** (confirmado
2026-09-03, se le preguntó directamente). Las preguntas 7, 9 y 11 quedan sin fuente para
resolverse — no se inventan valores; se documentan como limitación conocida asumida en
`ARCHITECTURE.md` (Fase 7), con los valores conservadores que ya tenemos por diseño propio
(timeout de proveedor 30s, `MAX_OUTPUT_TOKENS_CAP=4096`, rate limit `b=10, r=0.5/s`) en vez de
cifras confirmadas por la plataforma.

| # | Pregunta | Método | Estado |
|---|---|---|---|
| 1 | ¿Llama con `stream: true`, `false`, o ambos? | Logs | ✅ `true` en el primer turno real (ver §10) |
| 2 | ¿`input` llega como string o como array de ítems? | Logs | ✅ Array de ítems, 1 ítem en el primer turno |
| 3 | ¿`content` como string o como content parts? | Logs | ❓ `request_shape` no loguea la forma del ítem, solo el conteo — de baja prioridad ya, nuestro parser acepta ambos casos igual |
| 4 | ¿Envía `previous_response_id` o reenvía el transcript? | Logs | ✅ **Reenvía el transcript.** Turno 1: `n_items=1`. Turno 2 (misma conversación): `n_items=2`, `has_previous_response_id` siguió en `false`. Servicio confirmado stateless de facto |
| 5 | ¿Envía `tools` en el request? | Logs | ✅ `n_tools: 0` — no los manda |
| 6 | ¿Qué opciones tiene el desplegable de estado de conversación? | Guía / UI | ✅ Resuelto por comportamiento — usa reproducción de transcripción (ver #4) |
| 7 | ¿Cuál es el timeout del cliente? | Guía | ❌ Sin fuente — el Guía no responde preguntas técnicas de la plataforma. Limitación asumida (ver nota arriba) |
| 8 | ¿Valida la respuesta contra el esquema completo o solo lee el texto? | Guía | 🔶 Probablemente no valida: una solución aceptada implementa un subconjunto declarado |
| 9 | ¿Hay límite de tamaño de respuesta o de tokens? | Guía | ❌ Sin fuente — mismo motivo que la 7 |
| 10 | ¿Qué campos lee del `agent-card.json`? | Guía | 🔶 Al menos `name` y `supportedInterfaces` — el botón "Importar" rechazó nuestra tarjeta con exactamente ese mensaje pese a que ambos campos están presentes; probable desajuste con el nombre/forma real que espera su parser A2A. No bloqueante — el formulario manual es la ruta confiable |
| 11 | ¿Con qué frecuencia y concurrencia prueba el evaluador? | Guía | ❌ Sin fuente — mismo motivo que la 7 |
| 12 | ¿Requiere CORS, o el backend hace de proxy? | Guía | ✅ Backend hace de proxy — el `user_agent` real (`Bun/1.3.14`) confirma que la plataforma llama servidor-a-servidor, no desde el navegador del evaluador |

Preguntas 1, 2, 4, 5, 6 y 12 resueltas con dos mensajes reales de la misma conversación (§10).
Quedan solo las que dependen del agente Guía (7, 9, 11) y la 3 y 10, de baja prioridad.

---

## 9. Bitácora de verificación

Registrar aquí cada hallazgo con su fecha y evidencia. Este historial es lo que convierte el
documento en evidencia de rigor y no en una lista de suposiciones.

| Fecha | Hallazgo | Fuente | Cambio que provocó |
|---|---|---|---|
| 2026-09-03 | Ruta es `{base}/responses` | Formulario | Router montado en `/responses` y `/v1/responses` |
| 2026-09-03 | Auth es `Authorization: Bearer` | Formulario | Confirmado el diseño existente |
| 2026-09-03 | `model` es opcional | Formulario | `model: str \| None`, sin fallar por ausencia |
| 2026-09-03 | La plataforma inyecta parámetros extra | Formulario | `extra="allow"` + logging de `model_extra` |
| 2026-09-03 | Estado de conversación configurable | Formulario | D10 revisada: servicio potencialmente stateless |
| 2026-09-03 | Primera llamada real: `stream=true`, `input` como array de 1 ítem, sin `tools`, sin `previous_response_id` (primer turno), sin extras, `user_agent=Bun/1.3.14` | Log Explorer, `request_shape` | Preguntas 1, 2, 5 y 12 de §8 pasan a ✅. Confirma que streaming bufferizado (08_CONTRATO_PLATAFORMA.md §8.2) es el camino que de verdad se ejercita en producción |
| 2026-09-03 | Import de `agent-card.json` vía A2A rechazado ("falta name o supportedInterfaces") pese a que ambos campos están presentes | UI del formulario | Se llenó el formulario a mano; queda pendiente investigar el esquema A2A exacto que espera su parser (no bloqueante, Fase 7) |
| 2026-09-03 | Segundo mensaje, misma conversación: `n_items` pasó de 1 a 2, `has_previous_response_id` siguió en `false` | Log Explorer, `request_shape` | **`previous_response_id` no se usa — reproducción de transcript confirmada.** Preguntas 4 y 6 de §8 pasan a ✅. Servicio confirmado stateless de facto (§4) |
| 2026-09-03 | El agente Guía de la plataforma no responde preguntas técnicas (timeout, límites, concurrencia) | Conversación directa con el Guía | Preguntas 7, 9 y 11 de §8 quedan como ❌ sin fuente — limitación conocida asumida, documentada en `ARCHITECTURE.md` con los valores conservadores propios del diseño en vez de cifras confirmadas |
| 2026-09-03 | Dos turnos reales contra el despliegue final (CV real, `anthropic_direct`, revisión `cv-agent-00017-7pp`): `compute_years`+`get_experience` en el turno A, `search_profile` en el turno B, ambos con `stop_reason=end_turn` y `status_code=200` | Log Explorer (`agent_iteration`, `tool_call`, `request_out`) | Confirma el round-trip completo (no solo la forma del request) contra el CV y el código finales — §10b. `n_items` 3→5 con `has_previous_response_id=false` reafirma §4 |

---

## 10. Primera llamada real

Capturada el 2026-09-03, primer mensaje mandado desde el chat de la plataforma (proyecto GCP
`cv-agent-banorte`, revisión `cv-agent-00004-bd2`). La cuota de Vertex para el modelo de chat
estaba en 0 en ese momento (pendiente de aumento, ver bitácora del proyecto) — el agente le
devolvió un error a quien probó el chat, pero el `request_shape` se logueó *antes* de llamar al
proveedor, así que la evidencia es válida igual.

```json
// Turno 1
{
  "stream": true,
  "model": null,
  "input_kind": "items",
  "n_items": 1,
  "has_previous_response_id": false,
  "has_instructions": false,
  "n_tools": 0,
  "extra_keys": [],
  "user_agent": "Bun/1.3.14"
}
// Turno 2, misma conversación (7 minutos después)
{
  "stream": true,
  "model": null,
  "input_kind": "items",
  "n_items": 2,
  "has_previous_response_id": false,
  "has_instructions": false,
  "n_tools": 0,
  "extra_keys": [],
  "user_agent": "Bun/1.3.14"
}
```

Con eso las preguntas 1, 2, 4, 5, 6 y 12 de §8 pasan de ❓ a ✅. El hallazgo más importante:
**`n_items` creció de 1 a 2 mientras `has_previous_response_id` se quedó en `false` los dos
turnos** — la plataforma reproduce el transcript completo en `input`, no usa
`previous_response_id`. Confirma D10: el servicio es stateless de facto.

Sigue pendiente la forma exacta de `content` dentro de cada ítem (string vs. content parts) —
`request_shape` no la loguea, y es de baja prioridad porque el parser ya acepta ambas formas.

---

## 10b. Round-trip completo, contra el despliegue final

La captura de §10 probaba solo la *forma* del request — en ese momento la cuota de Vertex estaba
en 0 y el agente le devolvía error a quien probara el chat. Esta captura es posterior: CV real
cargado, `PROVIDER_BACKEND=anthropic_direct`, revisión `cv-agent-00017-7pp`. Confirma no solo la
forma del request sino el ciclo completo — tool calls reales y respuesta final entregada.

```json
// Turno A — 2026-09-03 22:14 (hora local), request_id e82b7f3f...
// request_shape: {"stream": true, "n_items": 3, "has_previous_response_id": false, "n_tools": 0}
// agent_iteration 1: stop_reason=tool_use, tool_calls=[compute_years, get_experience]
// tool_call compute_years: ok=true (0.1ms)
// tool_call get_experience: ok=true (0.1ms)
// agent_iteration 2: stop_reason=end_turn, tool_calls=[]
// request_out: status_code=200

// Turno B — 2026-09-03 22:16 (hora local), misma conversación, request_id 325a24c5...
// request_shape: {"stream": true, "n_items": 5, "has_previous_response_id": false, "n_tools": 0}
// agent_iteration 1: stop_reason=tool_use, tool_calls=[search_profile]
// tool_call search_profile: ok=true
// agent_iteration 2: stop_reason=end_turn, tool_calls=[]
// request_out: status_code=200
```

`n_items` volvió a crecer entre turnos (3→5) con `has_previous_response_id` en `false` los dos —
confirma otra vez el patrón de §4/§10 (reproducción de transcript), ahora contra el CV real. El
uso de `compute_years`, `get_experience` y `search_profile` en la misma sesión confirma que las
tres rutas de datos (estructurada, determinista y de respaldo/RAG) funcionan en producción, no
solo en local.

---

## 11. Evidencia de una implementación aceptada

Fuente: `[implementación anonimizada]`, aceptada para el mismo puesto. Ver
`09_BENCHMARK_COMPETIDOR.md`.

**Cómo se usa:** estrecha las probabilidades sobre lo que la plataforma tolera. **No** establece
el mínimo requerido, y su envío es de fecha anterior al formulario capturado, que muestra funciones
nuevas (tarjeta de agente, estado conversacional configurable, parámetros extra). Una plataforma en
evolución puede haber endurecido lo que antes toleraba.

| Observación | Implicación |
|---|---|
| Acepta `{role, content}` sin `type` | ⚠️ Nuestro parser debe tolerarlo. Corregido |
| Implementa "un subconjunto" del spec, declarado | La plataforma probablemente no valida el esquema completo |
| Devuelve 7 campos en el objeto `response` | Ídem — pero seguimos emitiendo todos (ver abajo) |
| Secuencia SSE sin `response.in_progress` | Ese evento es opcional en la práctica |
| `model` devuelto como string compuesto inventado | No se valida contra catálogo |
| `previous_response_id` con gestión de sesiones | El modo de estado conversacional lo usa |
| Ruta `/v1/responses` | Registró la base con `/v1`. Nuestro router dual cubre ambos |
| `GET /health` sin auth | Equivalente a nuestro `/healthz` |

### Qué NO se adopta

**El subconjunto.** Emitir el objeto de respuesta completo cuesta ~30 líneas de valores por
defecto; descubrir en la demo que faltaba un campo cuesta el reto. Con esa asimetría, la
completitud gana aunque la probabilidad de necesitarla sea baja.

Se mantiene la regla: **permisivo al aceptar, completo al emitir.** La referencia es más permisiva
que nosotros al aceptar (de ahí el hallazgo del `type`) e incompleta al emitir. Se toma lo primero.

### Higiene

Conformarse al contrato no es copiar: lo define el spec, no una implementación. Pero **no reusar su
vocabulario interno** (nombres de tablas, de campos de metadata, de conceptos propios). Los mismos
conceptos con nomenclatura propia. Si un evaluador lee ambos repositorios, las coincidencias de
nombres internos se notan.

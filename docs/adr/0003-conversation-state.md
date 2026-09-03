# ADR 0003 — Estado conversacional: `TTLCache` en memoria, revisado tras tráfico real

**Estado:** aceptado, revisado

## Contexto

El spec exige soportar `previous_response_id`: el modelo se muestrea sobre
`prev.input → prev.output → input`, preservando ese orden, así que el servidor debe poder
reconstruir el historial de una conversación anterior a partir de un id.

Riesgo de diseño conocido: si ese estado vive en memoria de un proceso y el servicio escala a
$k$ réplicas detrás de un balanceador, la probabilidad de que el turno $t+1$ caiga en la misma
réplica que guardó el turno $t$ es $1/k$ — con $k=2$ ya falla la mitad de las conversaciones de
forma intermitente.

## Decisión original

`cachetools.TTLCache` en memoria de un solo proceso (`--max-instances=1`), detrás de una interfaz
(`ResponseStore` Protocol) intercambiable por una implementación persistente si hiciera falta.

## Evidencia real que revisó la decisión

Verificado con tráfico real de la plataforma que consume este endpoint (dos turnos de la misma
conversación, vía logs correlacionados): el número de ítems del array `input` creció de un turno
a otro (de 1 a 2) mientras `previous_response_id` se mantuvo ausente en ambos. Esa plataforma
**reproduce el historial completo en `input` en cada turno**, no usa `previous_response_id`.

Para ese cliente real, el servicio es **stateless de facto**: la restricción de una sola réplica
deja de ser necesaria para la corrección de las conversaciones, aunque se mantiene por ahora por
simplicidad operativa (menos superficie que depurar durante el reto).

## Decisión final

Se mantiene `TTLCache` + `ResponseStore` — el costo de tenerlo ya está pagado, y el spec sigue
exigiéndolo para cualquier cliente que sí use `previous_response_id`. Se documenta como respaldo,
no como el mecanismo que de verdad sostiene la continuidad conversacional con el cliente
observado.

## Consecuencias

- Cero infraestructura adicional (sin Redis, sin base de datos externa) para el caso real.
- Si otro cliente del mismo endpoint sí dependiera de `previous_response_id` con el servicio
  escalado horizontalmente, la limitación de una sola réplica volvería a ser real para ese
  cliente específico.

## Criterio de reversión

Migrar `ResponseStore` a una implementación respaldada por Firestore (ya sin cambios en el resto
del código, solo la implementación detrás del Protocol) si: (a) se necesita escalar horizontalmente
y algún cliente real depende de `previous_response_id`, o (b) el servicio necesita sobrevivir
reinicios/despliegues sin perder conversaciones en curso.

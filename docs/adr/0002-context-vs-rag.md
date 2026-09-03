# ADR 0002 — Corpus completo en contexto, no RAG vectorial como arquitectura principal

**Estado:** aceptado

## Contexto

El agente necesita responder con precisión sobre un corpus estructurado (CV, proyectos,
habilidades) y una narrativa larga. La arquitectura por defecto para "un LLM que responde sobre
mis documentos" es RAG: trocear, indexar, recuperar top-$k$, inyectar. Había que decidir si ese
era el camino crítico aquí.

## Decisión

El corpus completo (curado, estructurado) va en el system prompt en cada llamada, cacheado. RAG
(BM25 + denso + RRF + MMR) existe como herramienta de **respaldo** para consultas semánticas
sobre la narrativa larga, no como el mecanismo principal de acceso a la información.

## Por qué

Sea $C$ el tamaño del corpus y $N$ la ventana de contexto del modelo. Para un CV senior
$C\approx 10^4$ tokens, $N\approx 2\times10^5$, es decir $C/N\approx 0.05$.

Condicionando la exactitud en $R$ = "el fragmento con la respuesta está en lo recuperado":

$$P(\text{correcto}) = P(\text{correcto}\mid R)P(R) + P(\text{correcto}\mid\neg R)P(\neg R)$$

Con contexto completo $P(R)=1$ por construcción. Con top-$k$, $P(R)<1$, y RAG solo puede *perder*
exactitud frente al contexto completo salvo que $C>N$ o que domine la degradación
*lost-in-the-middle* — no es el caso con $C/N=0.05$.

El contraargumento de costo (pagar $C$ tokens por llamada) se cae con *prompt caching*: con
escritura $\approx 1.25C$ y lectura $\approx 0.10C$, el caché gana desde la segunda llamada
dentro del TTL ($m>1.28$). En una conversación típica de varios turnos el ahorro es ~82% del
costo de input.

## Consecuencias

- Precisión más alta en preguntas factuales que top-$k$ con este corpus, sin coste adicional
  relevante gracias al caché.
- El corpus completo por sí solo no resuelve bien agregaciones/fechas — de ahí las herramientas
  deterministas (`compute_years`, etc.), que son la verdadera respuesta a "cómo se integra
  información confiable", no el retrieval.
- RAG sigue implementado y probado (demuestra la capacidad) pero fuera del camino crítico,
  reduciendo la superficie de fallo del flujo principal.

## Criterio de reversión

Si el corpus creciera de forma que $C/N$ deje de ser pequeño (mucho más contenido, o un modelo
con ventana más corta), o si el patrón de uso predominante pasara a preguntas de cola muy larga
sobre texto no estructurado, RAG pasaría a ser el camino principal.
